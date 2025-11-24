import os
import requests
import json
import re
import pandas as pd
from preprocess import query_schema
from dotenv import load_dotenv

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

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
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
    """
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

Please provide a corrected T-SQL query that:
1. Fixes all the validation errors listed above
2. Uses only tables and columns that exist in the provided schema
3. Still answers the original user question accurately

Return ONLY the corrected SQL query without any explanation:
"""
    
    return chat_once(feedback_prompt)
    



def build_sql_prompt(user_question: str, relevant_schema: str) -> str:
    """
    Build the user-facing prompt that will be sent to the chat model.
    """
    prompt = f"""
You are an expert T-SQL assistant. You write correct and efficient queries for Microsoft SQL Server.

User question:
{user_question}

# Role Definition

You are an expert T-SQL database developer with deep expertise in query optimization, schema analysis, and translating natural language questions into precise, efficient SQL queries. Your role is to analyze provided table schemas, understand user requirements, and construct accurate T-SQL queries that directly answer the user's question.

# Contextual Information

You will be provided with:
- A list of the most relevant database tables with their schemas (table names, column names, data types, and relationships)
- A natural language question from the user that requires a SQL query to answer

The tables provided have been pre-selected as the most relevant to the user's question, but you must determine the optimal way to query them. You are working within a T-SQL environment (SQL Server/Azure SQL Database).

# Task Description and Goals

Your primary goal is to generate a precise, executable T-SQL query that accurately answers the user's question using the provided table schemas. The query should be:

1. **Accurate**: Directly answers the specific question asked
2. **Efficient**: Uses appropriate joins, filters, and indexing strategies
3. **Specific**: Targets the exact data needed without over-fetching
4. **Readable**: Well-formatted with clear aliasing and logical structure

# Instructional Guidance and Constraints

Follow this systematic approach:

1. **Analyze the Question**: Break down what the user is asking for—identify required columns, filtering conditions, aggregations, and relationships between tables.

2. **Review Provided Tables**: Examine the table schemas to understand:
   - Which columns contain the needed data
   - How tables relate to each other (foreign keys, common columns)
   - What data types you're working with
   {relevant_schema}

3. **Iterative Query Construction**: Attempt to build the most specific query first, following this progression:
   - **Attempt 1**: Construct a highly specific query targeting exact columns and relationships you've identified
   - **Attempt 2**: If the first approach has limitations or uncertainties, try an alternative approach with different joins or filtering logic
   - **Attempt 3**: If specific approaches are problematic, broaden the query slightly while maintaining precision
   - **Final Resort**: Only if the above attempts are insufficient, construct a more general query that captures the needed data with additional filtering that can be applied post-query

4. **Query Requirements**:
   - Use explicit JOIN syntax (INNER JOIN, LEFT JOIN, etc.) rather than implicit joins
   - Include WHERE clauses for any filtering conditions
   - Use appropriate aggregation functions (COUNT, SUM, AVG, etc.) when needed
   - Add ORDER BY clauses when the question implies a specific ordering
   - Include TOP or OFFSET-FETCH for limited result sets when appropriate
   - Use table aliases for readability
   - Comment complex logic within the query

5. **Validation Checks**:
   - Ensure all referenced columns exist in the provided tables
   - Verify join conditions are logical and complete
   - Confirm the output matches what the question asks for
   - Check for potential NULL handling issues

# Expected Output Format and Examples

Your response should follow this structure:

```
## Query Analysis
[Brief 2-3 sentence explanation of what the user is asking for and your approach]

## T-SQL Query
```sql
[Your complete, executable T-SQL query]
```

## Query Explanation
[Explain the key components: joins used, filtering logic, aggregations, and why this approach answers the question]

## Assumptions
[List any assumptions made about the data or relationships]
```

## Few-Shot Examples
**Example :**
```
User Question: "Get a list of org id, account id with their billed amount for which they have autopay enabled."
Tables Provided:
- t_acct
- t_billed

Query Analysis:
Get a list of org id, account id with their billed amount for which they have autopay enabled.

T-SQL Query:
```sql
WITH autopay_on AS (
    SELECT DISTINCT acct_id
    FROM dbo.t_acct_payment_info
    WHERE autopay_enabled IS NOT NULL
)
SELECT a.*
FROM dbo.t_billed AS a
JOIN autopay_on AS ap
    ON a.acct_id = ap.acct_id;
```

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
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=200)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "success":
        raise RuntimeError(f"Matcha error: {data.get('error')}")

    # grab first text block
    first_output = data["output"][0]["content"][0]["text"]
    return first_output


def generate_sql_from_question(question: str, max_attempts: int = 3) -> str:
    """
    Generate SQL from a natural language question with validation feedback loop.
    
    Args:
        question: Natural language question
        max_attempts: Maximum number of attempts to generate valid SQL
    
    Returns:
        Validated SQL query string
    """
    # 1) Retrieve small schema slice with better parameters
    pruned_schema = query_schema(
        question, 
        method="chess",
        k_cols=30,           # Reduce to get more focused results
        max_tables=3,        # Fewer tables for clearer schema
        max_cols_per_table=5, # Focus on most relevant columns
        max_char_per_table=3000  # Allow more characters per table
    )
    print("=== Schema Retrieved ===")
    print(pruned_schema)
    print("========================")
    
    # 2) Generate and validate SQL with feedback loop
    for attempt in range(max_attempts):
        print(f"\n🔄 Attempt {attempt + 1}/{max_attempts}")
        
        # Build prompt for Matcha
        prompt = build_sql_prompt(question, pruned_schema)
        
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
            return sql_query
        else:
            print(f"❌ SQL validation failed: {'; '.join(validation['errors'])}")
            
            if attempt < max_attempts - 1:
                print(f"🔧 Attempting to fix SQL (attempt {attempt + 2}/{max_attempts})...")
                # Try to fix the SQL with feedback
                sql_query = fix_sql_with_feedback(sql_query, validation["errors"], pruned_schema, question)
            else:
                print("⚠️  Maximum attempts reached. Returning last generated SQL with validation errors.")
                print(f"Final validation errors: {'; '.join(validation['errors'])}")
                return sql_query
    
    return sql_query


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


if __name__ == "__main__":
    user_q = """I need a list of users in orgs that have the permission id 860 this does not work SELECT 
    op.organization_id
FROM 
    attwln_config_prod_db.dbo.t_organization_permission AS op
WHERE 
    op.permission_id = 860
    AND op.negative = 0;

"""
    sql_query = generate_sql_from_question(user_q)
    print("Generated SQL Query:\n")
    print(sql_query)

"""
To Do:
billingid, orgid, acctid these are getting interchanged and are assumed to be the same
need to update the prompt so that the assumptions are less and it checks the schema more
    need to avoid statements such as found billing in some random table so gonna go with that
    need to make sure that every table and column name is visible(DONE)



wanna add some sort of feed back mechanics
read up on chess paper again and see if anything is missing and understand it
need to do a lot of testing 
"""