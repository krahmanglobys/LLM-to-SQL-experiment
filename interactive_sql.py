#!/usr/bin/env python3
"""
Interactive LLM-to-SQL Query Generator with Feedback
Ask natural language questions and get SQL queries with feedback collection.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from llm_to_query import generate_sql_with_feedback

def main():
    """Interactive query interface with feedback collection."""
    print("🔍 Interactive LLM-to-SQL Query Generator")
    print("=" * 50)
    print("Ask natural language questions to generate SQL queries.")
    print("You'll be able to rate each response to help improve the system.")
    print("Type 'quit' or 'exit' to stop.\n")
    
    while True:
        try:
            # Get user question
            question = input("❓ Enter your question: ").strip()
            
            if question.lower() in ['quit', 'exit', 'q']:
                print("👋 Goodbye!")
                break
            
            if not question:
                print("❌ Please enter a question.")
                continue
            
            print("\n🤖 Generating SQL query...")
            print("-" * 50)
            
            # Generate SQL with feedback collection
            try:
                full_response, sql_query = generate_sql_with_feedback(
                    question, 
                    max_attempts=3, 
                    collect_feedback=True
                )
                
                print("\n" + "="*60)
                print("📋 FULL RESPONSE:")
                print("="*60)
                print(full_response)
                print("\n" + "="*60)
                print("🗂️  SQL QUERY ONLY:")
                print("="*60)
                print(sql_query)
                print("="*60)
                
            except Exception as e:
                print(f"❌ Error generating SQL: {e}")
                print("Please try again with a different question.")
            
            print("\n" + "-" * 50)
            print("Ready for next question!\n")
            
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except EOFError:
            print("\n\n👋 Goodbye!")
            break


if __name__ == "__main__":
    main()