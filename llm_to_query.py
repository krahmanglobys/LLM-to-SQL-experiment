import os
import requests
import json
import re
import pandas as pd
from preprocess import query_schema
from dotenv import load_dotenv
from datetime import datetime
import uuid

# Load environment variables
load_dotenv()

# Configuration from environment variables
BASE_URL = os.getenv("MATCHA_BASE_URL")
API_KEY = os.getenv("MATCHA_API_KEY")
MISSION_ID_STR = os.getenv("MATCHA_MISSION_ID")

# Validate required environment variables
required_vars = {
    "MATCHA_BASE_URL": BASE_URL,
    "MATCHA_API_KEY": API_KEY,
    "MATCHA_MISSION_ID": MISSION_ID_STR,
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise RuntimeError(f"Required environment variables are missing: {', '.join(missing_vars)}. Please set them in your .env file.")

MISSION_ID = int(MISSION_ID_STR)

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "MATCHA-API-KEY": API_KEY,
}

def chat_once(prompt: str) -> str:
    url = f"{BASE_URL}/completions"

    payload = {
        "mission_id": MISSION_ID,
        "input": prompt,   # simple, single-turn
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=200)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "success":
        raise RuntimeError(f"Matcha error: {data.get('error')}")

    # first text block
    return data["output"][0]["content"][0]["text"]


def validate_sql_against_schema(sql_query: str, schema_text: str) -> dict:
    """
    Validate a SQL query against the provided schema.
    Returns a dictionary with validation results.
    """
    validation_results = {
        "is_valid": True,
        "errors": [],
        "warnings": []
    }
    
    try:
        # Extract table names from schema
        schema_tables = set()
        schema_columns = {}
        
        # Parse schema text to extract table and column information
        lines = schema_text.split('\n')
        current_table = None
        
        for line in lines:
            line = line.strip()
            if line.startswith('Table ') and ':' in line:
                # Extract table name
                table_part = line.split(':')[0].replace('Table ', '').strip()
                current_table = table_part
                schema_tables.add(current_table)
                schema_columns[current_table] = set()
            elif line.startswith('- ') and current_table and '(' in line:
                # Extract column name
                column_part = line.replace('- ', '').split('(')[0].strip()
                schema_columns[current_table].add(column_part)
        
        # Extract tables and columns referenced in the SQL query
        sql_upper = sql_query.upper()
        
        # Extract table names from FROM and JOIN clauses
        from_pattern = r'FROM\s+(\w+\.?\w+)'
        join_pattern = r'JOIN\s+(\w+\.?\w+)'
        
        referenced_tables = set()
        for match in re.finditer(from_pattern, sql_upper):
            referenced_tables.add(match.group(1))
        for match in re.finditer(join_pattern, sql_upper):
            referenced_tables.add(match.group(1))
        
        # Check if referenced tables exist in schema
        for table in referenced_tables:
            table_clean = table.replace('dbo.', '').strip()
            schema_table_matches = [st for st in schema_tables if table_clean.lower() in st.lower()]
            
            if not schema_table_matches:
                validation_results["errors"].append(f"Table '{table}' not found in provided schema")
                validation_results["is_valid"] = False
        
        # Basic SQL syntax checks
        if 'SELECT' not in sql_upper:
            validation_results["errors"].append("Query does not appear to be a valid SELECT statement")
            validation_results["is_valid"] = False
            
        # Check for common T-SQL syntax
        if sql_query.count('(') != sql_query.count(')'):
            validation_results["errors"].append("Unmatched parentheses in query")
            validation_results["is_valid"] = False
            
    except Exception as e:
        validation_results["errors"].append(f"Validation error: {str(e)}")
        validation_results["is_valid"] = False
    
    return validation_results


def fix_sql_with_feedback(original_query: str, validation_errors: list, schema_text: str, user_question: str) -> str:
    """
    Attempt to fix SQL query based on validation errors.
    Intelligently includes hierarchy context only when ID-related errors are detected.
    """
    # Check if errors are related to ID confusion or hierarchy issues
    id_related_keywords = ['id', 'account', 'organization', 'client', 'user', 'sub_account', 'statement', 'hierarchy']
    needs_hierarchy_context = any(
        any(keyword in error.lower() for keyword in id_related_keywords) 
        for error in validation_errors
    )
    
    # Also check if the user question mentions IDs or relationships
    question_needs_context = any(keyword in user_question.lower() for keyword in id_related_keywords)
    
    feedback_prompt = f"""
The following SQL query has validation errors and needs to be corrected:

ORIGINAL QUERY:
```sql
{original_query}
```

VALIDATION ERRORS:
{chr(10).join(validation_errors)}

AVAILABLE SCHEMA:
{schema_text}

USER QUESTION:
{user_question}
"""
    
    # Add hierarchy context only when ID-related errors are detected
    if needs_hierarchy_context or question_needs_context:
        try:
            with open("DATA_HIERARCHY_CONTEXT.md", "r", encoding="utf-8") as f:
                hierarchy_context = f.read()
            feedback_prompt += f"""

{hierarchy_context}

IMPORTANT: The validation errors suggest confusion about ID relationships. Use the hierarchy context above to understand the correct relationships between different ID types.
"""
        except FileNotFoundError:
            print("Warning: DATA_HIERARCHY_CONTEXT.md not found. Proceeding without hierarchy context.")
    
    feedback_prompt += """
Please provide a corrected T-SQL query that:
1. Fixes all the validation errors listed above
2. Uses only tables and columns that exist in the provided schema
3. Still answers the original user question accurately

Return ONLY the corrected SQL query without any explanation:
"""
    
    return chat_once(feedback_prompt)
    



def build_sql_prompt(user_question: str, relevant_schema: str, include_hierarchy_context: bool = False) -> str:
    """
    Build the user-facing prompt that will be sent to the chat model.
    
    Args:
        user_question: The user's natural language question
        relevant_schema: The database schema context
        include_hierarchy_context: Whether to include the full hierarchy context (used for error correction)
    """
    # Base prompt without hierarchy context (for initial attempts)
    prompt = f"""
You are an expert T-SQL assistant. You write correct and efficient queries for Microsoft SQL Server.

User question:
{user_question}

# Role Definition

You are an expert T-SQL database developer with deep expertise in query optimization, schema analysis, and translating natural language questions into precise, efficient SQL queries. Your queries will be automatically validated against the provided schema, so accuracy is critical.

# Data Structure Awareness

This system follows a strict hierarchical data structure with specific ID relationships:
- **Client ID** → **Product/Bundle ID** → **Organization ID** → **Account ID** → **User ID / Sub_Account ID**
- Be especially careful when distinguishing between **Account ID** (customer entity) and **Sub_Account ID** (specific services/usage data)
- When queries involve multiple ID types, consider their hierarchical relationships
- If your initial query fails validation due to ID relationship issues, additional hierarchy context will be provided

# Important ID Guidelines

- For usage/data queries: Focus on **Sub_Account ID** level
- For customer/billing queries: Focus on **Account ID** level  
- For organizational structure: Focus on **Organization ID** level
- Always verify ID relationships match the hierarchical structure"""
    
    # Only add hierarchy context when needed (error correction attempts)
    if include_hierarchy_context:
        try:
            with open("DATA_HIERARCHY_CONTEXT.md", "r", encoding="utf-8") as f:
                hierarchy_context = f.read()
            prompt = f"""
You are an expert T-SQL assistant. You write correct and efficient queries for Microsoft SQL Server.

User question:
{user_question}

{hierarchy_context}

# Role Definition

You are an expert T-SQL database developer with deep expertise in query optimization, schema analysis, and translating natural language questions into precise, efficient SQL queries. Your queries will be automatically validated against the provided schema, so accuracy is critical."""
        except FileNotFoundError:
            print("Warning: DATA_HIERARCHY_CONTEXT.md not found. Proceeding without hierarchy context.")
    
    prompt += f"""

# CRITICAL: Schema Validation Process

 **IMPORTANT**: Your generated SQL will be automatically validated against the provided schema. Queries that reference non-existent tables or columns will be rejected and you'll be asked to fix them. To avoid validation errors:

1. **Use ONLY the tables explicitly listed in the schema below**
2. **Use ONLY the columns that exist in those tables**
3. **Match table names exactly as they appear in the schema**
4. **Pay attention to schema prefixes (e.g., dbo.table_name)**

# Contextual Information

You will be provided with:
- A curated list of the most relevant database tables with their complete schemas
- Table names, column names, data types, constraints, and relationships
- A natural language question that requires a SQL query to answer

The tables provided have been pre-selected as the most relevant to the user's question through semantic search. You are working within a T-SQL environment (SQL Server/Azure SQL Database).

# Available Schema

{relevant_schema}

# Task Description and Goals

Your primary goal is to generate a precise, executable T-SQL query that accurately answers the user's question using the provided table schemas. The query should be:

1. **Schema-Compliant**: Uses only tables and columns that exist in the provided schema
2. **Accurate**: Directly answers the specific question asked
3. **Efficient**: Uses appropriate joins, filters, and indexing strategies
4. **Executable**: Valid T-SQL syntax that will run without errors
5. **Readable**: Well-formatted with clear aliasing and logical structure

# Instructional Guidance and Constraints

Follow this systematic approach:

1. **Schema Analysis First**: Before writing any SQL, carefully review the provided schema to identify:
   - Exact table names and how they're referenced (with/without schema prefix)
   - Available columns in each table and their data types
   - Primary keys ([PK]) and foreign keys ([FK]) for joins
   - Relationships between tables based on foreign key references

2. **Question Analysis**: Break down what the user is asking for:
   - Required columns for the output
   - Filtering conditions needed
   - Aggregations or calculations required
   - Relationships between tables needed

3. **Query Construction**:
   - Start with the main table that contains the core data
   - Add JOINs only for tables that are necessary and exist in the schema
   - Use explicit JOIN syntax (INNER JOIN, LEFT JOIN, etc.)
   - Reference columns exactly as they appear in the schema
   - Add WHERE clauses for filtering
   - Include appropriate ORDER BY, GROUP BY, or HAVING clauses

4. **Pre-Validation Checklist** (CRITICAL - Follow Before Writing SQL):
   ✅ Verify ALL table names exist exactly as shown in the schema above
   ✅ Verify ALL column names exist in their respective tables 
   ✅ Ensure JOIN conditions use valid foreign key relationships from the schema
   ✅ Check that data types are compatible for comparisons and operations
   ✅ Confirm SQL syntax follows valid T-SQL standards
   ✅ Double-check that no assumptions are made about tables/columns not in the schema

5. **Schema Validation Requirements**:
   - **MANDATORY**: Every table name in your query MUST appear in the schema above
   - **MANDATORY**: Every column name in your query MUST exist in the specified table
   - **MANDATORY**: Use exact naming conventions including schema prefixes (e.g., dbo.table_name)
   - If you're unsure about a table or column, do NOT include it - only use what's explicitly provided

6. **Query Requirements**:
   - Use explicit JOIN syntax rather than implicit joins
   - Include appropriate WHERE clauses for filtering
   - Use proper aggregation functions when needed
   - Add ORDER BY when the question implies specific ordering
   - Use table aliases for readability
   - Handle potential NULL values appropriately

# Expected Output Format

Your response should follow this structure:

```
## Query Analysis
[Brief explanation of what you're trying to achieve and which tables/columns you'll use]

## Schema Validation Check
[Confirm that all tables and columns in your query exist in the provided schema - list the specific tables and key columns you're using]

## T-SQL Query
```sql
[Your complete, executable T-SQL query using only schema-provided tables/columns]
```

## Business Logic Explanation
[Explain in plain English what this query is doing, how the data flows through the system, and why these specific tables are connected. Help someone unfamiliar with the database understand the business relationships and data structure.]

## Assumptions
[List any assumptions made about the data or relationships]
```

## Few-Shot Examples
**Example:**
```
User Question: "Get a list of org id, account id with their billed amount for which they have autopay enabled."
Tables Provided:
- t_acct_payment_info
- t_billed

Query Analysis:
Need to find billing records for accounts that have autopay enabled by connecting payment information to billing data.

Schema Validation Check:
- t_acct_payment_info: Contains autopay_enabled column and acct_id for joining
- t_billed: Contains billing amounts and acct_id for joining

T-SQL Query:
```sql
WITH autopay_on AS (
    SELECT DISTINCT acct_id
    FROM dbo.t_acct_payment_info
    WHERE autopay_enabled IS NOT NULL
)
SELECT b.org_id, b.acct_id, b.billed_amount
FROM dbo.t_billed AS b
JOIN autopay_on AS ap
    ON b.acct_id = ap.acct_id;
```

Business Logic Explanation:
This query is looking for customers who have automatic payment set up and retrieving their billing information. In our system, customer payment preferences (like autopay) are stored separately from billing records. We first identify all accounts that have autopay enabled, then connect that information to the billing table to get the actual billing amounts. This gives us a list of customers who pay automatically along with how much they're being billed.


Assumptions:
- autopay_enabled IS NOT NULL indicates autopay is active
- acct_id is the common key between payment info and billing tables
```

# Any Additional Notes on Scope or Limitations

- You should only generate queries using the tables explicitly provided to you
- If the provided tables are clearly insufficient to answer the question, state this explicitly and explain what additional tables or information would be needed
- Do not fabricate table names, column names, or relationships not present in the provided schema
- If the question is ambiguous, state your interpretation and proceed with the most logical query
- Focus on standard T-SQL syntax compatible with SQL Server 2016 and later versions
- Prioritize correctness over performance, but note any obvious optimization opportunities"""
    return prompt.strip()





def chat_once(prompt: str) -> str:
    url = f"{BASE_URL}/completions"
    payload = {
        "mission_id": MISSION_ID,
        "input": prompt,   # or use "messages" if you want full chat structure
    }

    print("🤖 Sending request to Matcha API... Please wait for response.")
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=500)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "success":
        raise RuntimeError(f"Matcha error: {data.get('error')}")

    # grab first text block
    first_output = data["output"][0]["content"][0]["text"]
    return first_output


def generate_sql_from_question(question: str, max_attempts: int = 3) -> tuple[str, str]:
    """
    Generate SQL from a natural language question with validation feedback loop.
    
    Args:
        question: Natural language question
        max_attempts: Maximum number of attempts to generate valid SQL
    
    Returns:
        Tuple of (full_response_with_explanations, validated_sql_query)
    """
    # 1) Retrieve small schema slice with better parameters
    pruned_schema = query_schema(
        question, 
        method="chess",
        k_cols=5,           # Reduce to get more focused results
        max_tables=100,        # Fewer tables for clearer schema
        max_cols_per_table=10, # Focus on most relevant columns
        max_char_per_table=1000  # Allow more characters per table
    )
    print("=== Schema Retrieved ===")
    print(pruned_schema)
    print("========================")
    
    # 2) Generate and validate SQL with feedback loop
    for attempt in range(max_attempts):
        print(f"\n🔄 Attempt {attempt + 1}/{max_attempts}")
        
        # Build prompt for Matcha (include hierarchy context only for retry attempts or ID-related questions)
        id_keywords = ['id', 'account', 'organization', 'client', 'user', 'sub_account', 'statement', 'hierarchy']
        needs_context = attempt > 0 or any(keyword in question.lower() for keyword in id_keywords)
        
        prompt = build_sql_prompt(question, pruned_schema, include_hierarchy_context=needs_context)
        
        # Generate SQL
        print("🤖 Generating SQL query...")
        sql = chat_once(prompt)
        
        # Extract just the SQL query from the response (remove markdown formatting)
        sql_query = extract_sql_from_response(sql)
        
        print(f"📝 Generated SQL:\n{sql_query}")
        
        # Validate the SQL query
        print("🔍 Validating SQL against schema...")
        validation = validate_sql_against_schema(sql_query, pruned_schema)
        
        if validation["is_valid"]:
            print("✅ SQL validation passed!")
            if validation["warnings"]:
                print(f"⚠️  Warnings: {'; '.join(validation['warnings'])}")
            return sql, sql_query  # Return both full response and SQL query
        else:
            print(f"❌ SQL validation failed: {'; '.join(validation['errors'])}")
            
            if attempt < max_attempts - 1:
                print(f"🔧 Attempting to fix SQL (attempt {attempt + 2}/{max_attempts})...")
                # Try to fix the SQL with feedback
                sql_query = fix_sql_with_feedback(sql_query, validation["errors"], pruned_schema, question)
            else:
                print("⚠️  Maximum attempts reached. Returning last generated SQL with validation errors.")
                print(f"Final validation errors: {'; '.join(validation['errors'])}")
                return sql, sql_query  # Return both even with errors
    
    return sql, sql_query  # Fallback return


def extract_sql_from_response(response: str) -> str:
    """
    Extract SQL query from LLM response, removing markdown formatting.
    """
    # Look for SQL code blocks
    sql_pattern = r'```sql\s*(.*?)\s*```'
    match = re.search(sql_pattern, response, re.DOTALL | re.IGNORECASE)
    
    if match:
        return match.group(1).strip()
    
    # If no code block found, try to find SELECT statement
    lines = response.split('\n')
    sql_lines = []
    in_sql = False
    
    for line in lines:
        line_stripped = line.strip()
        if line_stripped.upper().startswith('SELECT'):
            in_sql = True
        
        if in_sql:
            sql_lines.append(line)
            # Stop if we hit a line that looks like it's after the SQL
            if line_stripped.endswith(';') or (line_stripped and not any(keyword in line_stripped.upper() for keyword in ['SELECT', 'FROM', 'WHERE', 'JOIN', 'GROUP', 'ORDER', 'HAVING', 'AND', 'OR', 'ON', 'AS', 'INNER', 'LEFT', 'RIGHT'])):
                break
    
    if sql_lines:
        return '\n'.join(sql_lines).strip()
    
    # Fallback: return the whole response
    return response.strip()


def save_feedback(session_id: str, user_question: str, full_response: str, sql_query: str, rating: str, user_comments: str = "") -> None:
    """
    Save user feedback to a JSON file.
    
    Args:
        session_id: Unique identifier for this query session
        user_question: Original user question
        full_response: Full LLM response with explanations
        sql_query: Extracted SQL query
        rating: User rating ('good', 'bad', or 'neutral')
        user_comments: Optional user comments about the response
    """
    feedback_data = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "user_question": user_question,
        "full_response": full_response,
        "sql_query": sql_query,
        "rating": rating,
        "user_comments": user_comments,
        "metadata": {
            "response_length": len(full_response),
            "sql_length": len(sql_query),
            "has_validation_errors": "validation failed" in full_response.lower()
        }
    }
    
    feedback_file = "feedback_data.jsonl"
    
    try:
        # Append to JSONL file (one JSON object per line)
        with open(feedback_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(feedback_data) + "\n")
        print(f"✅ Feedback saved to {feedback_file}")
    except Exception as e:
        print(f"❌ Error saving feedback: {e}")


def collect_user_feedback(session_id: str, user_question: str, full_response: str, sql_query: str) -> None:
    """
    Collect feedback from user about the generated response.
    
    Args:
        session_id: Unique identifier for this query session
        user_question: Original user question
        full_response: Full LLM response with explanations
        sql_query: Extracted SQL query
    """
    print("\n" + "="*60)
    print("📝 FEEDBACK REQUEST")
    print("="*60)
    print("Please rate the quality of the generated response:")
    print("  [G] Good - The response was helpful and accurate")
    print("  [B] Bad - The response had issues or was incorrect")
    print("  [N] Neutral - The response was okay but could be better")
    print("-"*60)
    
    while True:
        try:
            feedback_input = input("Enter your rating [G/B/N]: ").strip().upper()
            
            if feedback_input in ['G', 'B', 'N']:
                break
            else:
                print("❌ Invalid input. Please enter G, B, or N.")
        except KeyboardInterrupt:
            print("\n⚠️  Feedback is required. Please provide a rating.")
            continue
        except EOFError:
            print("\n⚠️  Feedback is required. Please provide a rating.")
            continue
    
    # Map input to full rating
    rating_map = {'G': 'good', 'B': 'bad', 'N': 'neutral'}
    rating = rating_map[feedback_input]
    
    # Collect optional comments
    user_comments = ""
    if rating in ['bad', 'neutral']:
        print("\n💬 Optional: Please share what could be improved (press Enter to skip):")
        try:
            user_comments = input("Comments: ").strip()
        except (KeyboardInterrupt, EOFError):
            user_comments = ""
    
    # Save feedback
    save_feedback(session_id, user_question, full_response, sql_query, rating, user_comments)
    
    # Show thank you message
    if rating == 'good':
        print("🎉 Thank you for the positive feedback!")
    elif rating == 'bad':
        print("🔧 Thank you for the feedback. We'll work on improving the system.")
    else:
        print("👍 Thank you for your feedback!")


def generate_sql_with_feedback(question: str, max_attempts: int = 3) -> tuple[str, str]:
    """
    Generate SQL from a natural language question with mandatory feedback collection.
    
    Args:
        question: Natural language question
        max_attempts: Maximum number of attempts to generate valid SQL
    
    Returns:
        Tuple of (full_response_with_explanations, validated_sql_query)
    """
    # Generate unique session ID
    session_id = str(uuid.uuid4())[:8]
    
    print(f"🔍 Session ID: {session_id}")
    print(f"❓ Question: {question[:100]}{'...' if len(question) > 100 else ''}")
    
    # Generate SQL using existing function
    full_response, sql_query = generate_sql_from_question(question, max_attempts)
    
    # Always collect feedback (mandatory)
    collect_user_feedback(session_id, question, full_response, sql_query)
    
    return full_response, sql_query


if __name__ == "__main__":
    user_q = """ Please resolve the following error:  They are getting an error message: You don't have any accounts set up for Business center. The issue is that I provisioned it for them and the account numbers are still billing.	GCC-42748	Medium	"ISSUE_WITH: Billing Account

COMPANY_NAME: FELLOWES
CUSTOMER_ACCOUNT: 8310015049855
CSR_CONTACT_NAME: 00000
CUSTOMER_USERID: [phogan@fellowes.com|mailto:phogan@fellowes.com]
BROWSER: Billing (new)
PROBLEM_SUMMARY: They are getting an error message: You don't have any accounts set up for Business center. The issue is that I provisioned it for them and the account numbers are still billing,
PROBLEM_DESCRIPTION: They are getting an error message: You don't have any accounts set up for Business center. The issue is that I provisioned it for them and the account numbers are still billing.
ISSUE_REPLICATION_STEPS: You to the dashboard, go to the Billing (new) tab."	Nov/13/2025 4:51 AM	Nov/19/2025 6:00 PM	AT&T Wireline Support	Bill Analyst	Account Modification
"""
    # Use the new feedback-enabled function
    full_response, sql_query = generate_sql_with_feedback(user_q, max_attempts=3, collect_feedback=True)
    
    print("\n" + "="*80)
    print("FULL RESPONSE WITH EXPLANATIONS:")
    print("="*80)
    print(full_response)
    print("\n" + "="*80)
    print("EXTRACTED SQL QUERY ONLY:")
    print("="*80)
    print(sql_query)



"""

To Do:
billingid, orgid, acctid these are getting interchanged and are assumed to be the same(Done-Testing)
need to update the prompt so that the assumptions are less and it checks the schema more
    need to avoid statements such as found billing in some random table so gonna go with that
    need to make sure that every table and column name is visible(DONE)



read up on chess paper again and see if anything is missing and understand it
need to do a lot of testing 
"""