"""
CHESS-style schema retrieval:
- Column filtering
- Table selection
- Final column filtering

This script:
- Loads the column-level FAISS index + metadata
- Given a natural-language question, returns a pruned schema block
  you can plug into your LLM SQL prompt.
"""

import json
from typing import List, Dict

import faiss

from preprocess import embed_texts_azure, normalize_rows  # reuse your embedding logic

# ---- paths to your index / metadata files ----
COLUMN_FAISS_PATH = "/Users/krahman/LLM-to-SQL-experiment/schema_tables.faiss"
COLUMN_METADATA_PATH = "/Users/krahman/LLM-to-SQL-experiment/schema_tables_metadata.json"


# ========= LOAD COLUMN INDEX + METADATA =========

def load_column_index_and_metadata():
    index = faiss.read_index(COLUMN_FAISS_PATH)
    with open(COLUMN_METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    return index, metadata


column_index, column_meta = load_column_index_and_metadata()


# ========= CHESS STEPS =========

def column_filtering(question: str, k_cols: int = 40) -> List[Dict]:
    """
    Step 1: Column filtering.
    Use FAISS + Azure embeddings to find the top-k relevant columns
    for a natural language question.
    """
    q_vec = embed_texts_azure([question])
    q_vec = normalize_rows(q_vec)

    D, I = column_index.search(q_vec, k_cols)

    results = []
    for rank, idx in enumerate(I[0]):
        m = column_meta[idx]
        results.append(
            {
                "rank": rank + 1,
                "score": float(D[0][rank]),
                **m,  # includes: id, table_schema, table_name, column_name, text
            }
        )
    return results


def table_selection(filtered_columns: List[Dict], max_tables: int = 5) -> List[str]:
    """
    Step 2: Table selection.
    Aggregate column scores per table and pick the top-N tables.

    Returns list of table ids: "schema.table"
    """
    scores = {}
    for c in filtered_columns:
        tid = f"{c['table_schema']}.{c['table_name']}"
        # you can also use sum instead of max depending on preference
        scores[tid] = max(scores.get(tid, 0.0), c["score"])

    sorted_tables = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_tables = [tid for tid, _ in sorted_tables[:max_tables]]
    return top_tables


def final_column_filtering(
    filtered_columns: List[Dict],
    selected_tables: List[str],
    max_cols_per_table: int = 10,
) -> Dict[str, List[Dict]]:
    """
    Step 3: Final column filtering.
    For each selected table, keep only the most relevant columns
    (up to max_cols_per_table).
    """
    selected_set = set(selected_tables)
    per_table: Dict[str, List[Dict]] = {tid: [] for tid in selected_tables}

    for c in filtered_columns:
        tid = f"{c['table_schema']}.{c['table_name']}"
        if tid in selected_set:
            per_table[tid].append(c)

    # keep top-N columns per table
    for tid in per_table:
        per_table[tid].sort(key=lambda x: x["score"], reverse=True)
        per_table[tid] = per_table[tid][:max_cols_per_table]

    return per_table


def build_chess_schema_block(per_table_columns: Dict[str, List[Dict]], max_char_per_table: int = 2000) -> str:
    """
    Build a human-/LLM-friendly schema snippet from the
    CHESS-selected columns with smart truncation that preserves column information.
    """
    lines = []
    for tid, cols in per_table_columns.items():
        lines.append(f"Table {tid}:")
        for c in cols:
            table_text = c['text']
            
            # If the table description is too long, smart truncate
            if len(table_text) > max_char_per_table:
                # Try to preserve the columns section
                if "Columns:" in table_text:
                    parts = table_text.split("Columns:")
                    header = parts[0]
                    columns_section = "Columns:" + parts[1]
                    
                    # Keep full columns section if possible, truncate header if needed
                    if len(columns_section) <= max_char_per_table - 100:
                        if len(header) > 100:
                            header = header[:100] + "..."
                        table_text = header + "\n" + columns_section
                    else:
                        # Truncate but ensure we show critical column info
                        table_text = table_text[:max_char_per_table-50] + "\n... [Schema truncated, key columns shown above]"
                else:
                    table_text = table_text[:max_char_per_table] + "... [Schema truncated]"
            
            lines.append(f"{table_text}")
        lines.append("")  # blank line between tables
    return "\n".join(lines).rstrip()


def get_pruned_schema_for_question(
    question: str,
    k_cols: int = 40,
    max_tables: int = 5,
    max_cols_per_table: int = 10,
    max_char_per_table: int = 2000,  # Add character limit per table
) -> str:
    """
    Convenience wrapper:
    Given a user question, run all CHESS steps and return a single
    pruned schema block (string) to drop into your LLM prompt.
    """
    # 1) Column filtering
    col_hits = column_filtering(question, k_cols=k_cols)

    # 2) Table selection
    top_tables = table_selection(col_hits, max_tables=max_tables)

    # 3) Final column filtering per table
    per_table_cols = final_column_filtering(
        col_hits,
        selected_tables=top_tables,
        max_cols_per_table=max_cols_per_table,
    )

    # 4) Build schema block with smart truncation
    schema_block = build_chess_schema_block(per_table_cols, max_char_per_table)
    return schema_block


# ========= SIMPLE CLI TEST =========

