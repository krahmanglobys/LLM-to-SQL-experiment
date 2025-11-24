import os
import json
import numpy as np
import pandas as pd
import faiss
from azure.ai.inference import EmbeddingsClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ========= CONFIG =========

SCHEMA_CSV_PATH = os.getenv("SCHEMA_CSV_PATH")
FAISS_INDEX_PATH = os.getenv("FAISS_INDEX_PATH")
METADATA_PATH = os.getenv("METADATA_PATH")

# Azure OpenAI settings from environment
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
model_name = os.getenv("AZURE_OPENAI_MODEL_NAME")
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
api_version = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")

# Validate required environment variables
required_vars = {
    "AZURE_OPENAI_ENDPOINT": endpoint,
    "AZURE_OPENAI_API_KEY": AZURE_OPENAI_API_KEY,
    "AZURE_OPENAI_MODEL_NAME": model_name,
    "AZURE_OPENAI_DEPLOYMENT": deployment,
    "AZURE_OPENAI_API_VERSION": api_version,
    "SCHEMA_CSV_PATH": SCHEMA_CSV_PATH,
    "FAISS_INDEX_PATH": FAISS_INDEX_PATH,
    "METADATA_PATH": METADATA_PATH,
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise RuntimeError(f"Required environment variables are missing: {', '.join(missing_vars)}. Please set them in your .env file.")

AZURE_OPENAI_EMBEDDING_DEPLOYMENT = deployment
AZURE_OPENAI_API_VERSION = api_version


# ========= AZURE CLIENT =========

client = EmbeddingsClient(
    endpoint=endpoint,
    credential=AzureKeyCredential(AZURE_OPENAI_API_KEY),
)


# ========= SCHEMA → TEXT DESCRIPTION =========

def humanize_table_name(name: str) -> str:
    """
    Turn something like CUSTOMER_ORDERS or customer_orders into
    'customer orders' just to help the LLM a bit.
    """
    return name.replace("_", " ").lower()


def build_table_descriptions(df: pd.DataFrame) -> list[dict]:
    """
    Returns a list of {id, text, table_schema, table_name} entries,
    where `text` is a natural-language-ish description of the table + columns.
    """

    # Normalize booleans just in case
    for col in ["is_primary_key", "is_foreign_key"]:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)

    grouped = df.groupby(["table_schema", "table_name"])
    records: list[dict] = []

    for (schema, table), g in grouped:
        # simple auto description from table name
        auto_desc = f"This table stores data related to {humanize_table_name(table)}."

        col_lines = []
        fk_lines = []

        for _, row in g.iterrows():
            col_parts = [f"{row['column_name']} ({row['data_type']}"]

            # add type details if present
            if pd.notna(row.get("max_length")) and row["max_length"] > 0:
                col_parts.append(f"max_length={int(row['max_length'])}")
            if pd.notna(row.get("precision")) and row["precision"] > 0:
                col_parts.append(f"precision={int(row['precision'])}")
            if pd.notna(row.get("scale")) and row["scale"] > 0:
                col_parts.append(f"scale={int(row['scale'])}")

            col_parts.append(")")  # close the type

            # PK / FK / nullability
            if row["is_primary_key"] == 1:
                col_parts.append("[PK]")
            if row["is_foreign_key"] == 1:
                col_parts.append("[FK]")

            is_null = str(row["is_nullable"]).upper()
            col_parts.append("NOT NULL" if is_null == "NO" else "NULL")

            if pd.notna(row.get("column_default")):
                col_parts.append(f"default={row['column_default']}")

            if pd.notna(row.get("column_description")):
                col_parts.append(f"- {row['column_description']}")

            col_lines.append(" ".join(col_parts))

            # FK relationship line
            if (
                row["is_foreign_key"] == 1
                and pd.notna(row.get("referenced_table"))
                and pd.notna(row.get("referenced_column"))
            ):
                fk_lines.append(
                    f"{row['column_name']} references "
                    f"{row['referenced_schema']}.{row['referenced_table']}"
                    f"({row['referenced_column']})"
                )

        header = f"Table {schema}.{table}. {auto_desc}"

        columns_text = "Columns:\n- " + "\n- ".join(col_lines)

        fk_text = ""
        if fk_lines:
            fk_text = "\nForeign keys:\n- " + "\n- ".join(fk_lines)

        full_text = header + "\n" + columns_text + fk_text

        records.append(
            {
                "id": f"{schema}.{table}",
                "table_schema": schema,
                "table_name": table,
                "text": full_text,
            }
        )

    return records


# ========= EMBEDDINGS (AZURE OPENAI) =========

def embed_texts_azure(texts: list[str], batch_size: int = 16) -> np.ndarray:
    """
    Embed a list of strings using Azure AI Inference embeddings.
    Returns: numpy array of shape (len(texts), embedding_dim)
    """
    vectors: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        response = client.embed(
            input=batch,
            model=model_name
        )

        # response.data is in order of input
        for item in response.data:
            vectors.append(item.embedding)

    return np.array(vectors, dtype="float32")


def normalize_rows(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True) + 1e-10
    return x / norms


# ========= RETRIEVAL FUNCTIONS =========

def simple_retrieval(question: str, k: int = 5) -> str:
    """
    Simple embedding-based table retrieval.
    Returns top-k most similar tables based on cosine similarity.
    """
    # Load the FAISS index and metadata if not already loaded
    if not hasattr(simple_retrieval, 'index'):
        simple_retrieval.index = faiss.read_index(FAISS_INDEX_PATH)
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            simple_retrieval.metadata = json.load(f)
    
    # Embed the question
    q_vec = embed_texts_azure([question])
    q_vec = normalize_rows(q_vec)
    
    # Search for similar tables
    D, I = simple_retrieval.index.search(q_vec, k)
    
    # Build result
    results = []
    for rank, idx in enumerate(I[0]):
        table_info = simple_retrieval.metadata[idx]
        results.append(f"Rank {rank + 1} (Score: {D[0][rank]:.3f}):")
        results.append(f"{table_info['text']}")
        results.append("")  # blank line
    
    return "\n".join(results)


def chess_retrieval(question: str, k_cols: int = 40, max_tables: int = 5, max_cols_per_table: int = 10, max_char_per_table: int = 2000) -> str:
    """
    CHESS-style retrieval using the chess_preprocess module.
    """
    try:
        # Import here to avoid circular import
        from chess_preprocess import get_pruned_schema_for_question
        return get_pruned_schema_for_question(
            question=question,
            k_cols=k_cols,
            max_tables=max_tables,
            max_cols_per_table=max_cols_per_table,
            max_char_per_table=max_char_per_table
        )
    except ImportError as e:
        return f"Error: Could not import chess_preprocess module. {e}"
    except Exception as e:
        return f"Error in CHESS retrieval: {e}"


def query_schema(question: str, method: str = "simple", **kwargs) -> str:
    """
    Main query function that supports both retrieval methods.
    
    Args:
        question: The natural language question
        method: "simple" for basic retrieval, "chess" for CHESS-style retrieval
        **kwargs: Additional parameters for the chosen method
        
    Returns:
        Formatted schema information relevant to the question
    """
    if method.lower() == "simple":
        k = kwargs.get('k', 10)
        return simple_retrieval(question, k=k)
    elif method.lower() == "chess":
        k_cols = kwargs.get('k_cols', 40)
        max_tables = kwargs.get('max_tables', 5)
        max_cols_per_table = kwargs.get('max_cols_per_table', 10)
        max_char_per_table = kwargs.get('max_char_per_table', 2000)
        return chess_retrieval(question, k_cols, max_tables, max_cols_per_table, max_char_per_table)
    else:
        return f"Error: Unknown method '{method}'. Use 'simple' or 'chess'."


# ========= MAIN PIPELINE =========



def preprocess_faiss():
    """
    Build embeddings and FAISS index for table-level retrieval.
    This creates the foundation for both simple and CHESS retrieval methods.
    """
    # 1) Load schema CSV
    df = pd.read_csv(SCHEMA_CSV_PATH)
    print(f"Loaded schema CSV with {len(df)} rows")

    # 2) Build table descriptions
    table_docs = build_table_descriptions(df)
    print(f"Built {len(table_docs)} table descriptions")
    print("--- Example description ---")
    print(table_docs[0]["text"][:500])
    print("---------------------------")

    # 3) Create embeddings
    texts = [doc["text"] for doc in table_docs]
    print("Creating embeddings with Azure OpenAI...")
    vectors = embed_texts_azure(texts)
    print("Embeddings shape:", vectors.shape)

    # 4) Normalize for cosine similarity
    vectors = normalize_rows(vectors)

    # 5) Build FAISS index
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)   # inner product on normalized vectors = cosine sim
    index.add(vectors)
    print("FAISS index size:", index.ntotal)

    # 6) Save FAISS index + metadata
    faiss.write_index(index, FAISS_INDEX_PATH)
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(table_docs, f, ensure_ascii=False, indent=2)

    print(f"Saved FAISS index to {FAISS_INDEX_PATH}")
    print(f"Saved metadata to {METADATA_PATH}")
    print("✅ Done. Ready for both simple and CHESS retrieval.")





