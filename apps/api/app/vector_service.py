"""Vector embedding service — chunks financial model data and stores in pgvector."""

import json
import os
import uuid
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy import text

_EMBEDDING_MODEL = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazily create the Azure OpenAI client so the API can boot without LLM credentials configured."""
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/",
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
        )
    return _client


def get_embedding(text_input: str) -> list[float]:
    """Get embedding vector for a text string."""
    response = _get_client().embeddings.create(
        input=text_input,
        model=_EMBEDDING_MODEL,
    )
    return response.data[0].embedding


def chunk_model_data(parsed_json: dict, filename: str) -> list[dict]:
    """
    Chunk parsed financial model into semantically meaningful segments.
    Each chunk includes: section, content text, and metadata for traceability.
    """
    chunks = []

    # Cover / Project Overview
    cover = parsed_json.get("cover", {})
    if cover:
        lines = [f"{k}: {v}" for k, v in cover.items()]
        chunks.append({
            "section": "cover",
            "content": f"Project Overview from '{filename}':\n" + "\n".join(lines),
            "metadata": {"source_sheet": "Cover", "source_file": filename, "keys": list(cover.keys())},
        })

    # Assumptions - chunk in groups of 5
    assumptions = parsed_json.get("assumptions", [])
    for i in range(0, len(assumptions), 5):
        batch = assumptions[i:i+5]
        lines = []
        for a in batch:
            name = a.get("name", "")
            value = a.get("value", "")
            source = a.get("source", "Assumptions sheet")
            unit = a.get("unit", "")
            lines.append(f"- {name}: {value} {unit} (Source: {source})")
        chunks.append({
            "section": "assumptions",
            "content": f"Key Assumptions (items {i+1}-{i+len(batch)}) from '{filename}':\n" + "\n".join(lines),
            "metadata": {
                "source_sheet": "Assumptions",
                "source_file": filename,
                "item_range": f"{i+1}-{i+len(batch)}",
                "assumption_names": [a.get("name", "") for a in batch],
            },
        })

    # Returns / Investment Metrics
    returns = parsed_json.get("returns", {})
    if returns.get("metrics"):
        lines = []
        for m in returns["metrics"]:
            lines.append(
                f"- {m.get('metric','')}: Base={m.get('base_case','')}, "
                f"Stress={m.get('stress_case','')}, Upside={m.get('upside_case','')}, "
                f"Hurdle={m.get('hurdle','')}, Status={m.get('status','')}"
            )
        chunks.append({
            "section": "returns",
            "content": f"Investment Returns from '{filename}':\n" + "\n".join(lines),
            "metadata": {
                "source_sheet": "Returns",
                "source_file": filename,
                "metrics": [m.get("metric", "") for m in returns["metrics"]],
            },
        })

    # Sensitivity
    sensitivity = parsed_json.get("sensitivity", {})
    one_way = sensitivity.get("one_way", [])
    if one_way:
        lines = []
        for item in one_way[:10]:
            lines.append(
                f"- {item.get('assumption','')}: Base IRR={item.get('base_case','')}, "
                f"Stress(-20%)={item.get('stress_minus_20','')}, "
                f"Upside(+20%)={item.get('upside_plus_20','')}, "
                f"Key variable: {item.get('key_variable','')}"
            )
        chunks.append({
            "section": "sensitivity",
            "content": f"Sensitivity Analysis from '{filename}':\n" + "\n".join(lines),
            "metadata": {
                "source_sheet": "Sensitivity",
                "source_file": filename,
                "variables": [item.get("assumption", "") for item in one_way[:10]],
            },
        })

    # Capex
    capex = parsed_json.get("capex", {})
    if capex.get("years"):
        years = capex["years"]
        data = capex.get("data", {})
        lines = [f"- Years: {years[0]}-{years[-1]}"]
        for key, values in list(data.items())[:5]:
            lines.append(f"- {key}: {values[:5]}...")
        chunks.append({
            "section": "capex",
            "content": f"Capital Expenditure Schedule from '{filename}':\n" + "\n".join(lines),
            "metadata": {
                "source_sheet": "Capex",
                "source_file": filename,
                "year_range": f"{years[0]}-{years[-1]}",
                "line_items": list(data.keys()),
            },
        })

    # Debt Schedule
    debt = parsed_json.get("debt_schedule", {})
    if debt.get("data"):
        data = debt["data"]
        lines = []
        for key, values in list(data.items())[:6]:
            lines.append(f"- {key}: {values[:5]}...")
        chunks.append({
            "section": "debt_schedule",
            "content": f"Debt Schedule from '{filename}':\n" + "\n".join(lines),
            "metadata": {
                "source_sheet": "Debt_Schedule",
                "source_file": filename,
                "line_items": list(data.keys()),
            },
        })

    # Checks
    checks = parsed_json.get("checks", [])
    if checks:
        lines = []
        for c in checks[:10]:
            lines.append(
                f"- {c.get('description','')}: Value={c.get('value','')}, "
                f"Expected={c.get('expected','')}, Status={c.get('status','')}"
            )
        chunks.append({
            "section": "checks",
            "content": f"Model Integrity Checks from '{filename}':\n" + "\n".join(lines),
            "metadata": {
                "source_sheet": "Checks",
                "source_file": filename,
                "check_count": len(checks),
            },
        })

    # Cash flows (if available)
    cashflows = parsed_json.get("cashflows", parsed_json.get("cash_flows", {}))
    if cashflows and isinstance(cashflows, dict) and cashflows.get("data"):
        data = cashflows["data"]
        lines = []
        for key, values in list(data.items())[:5]:
            lines.append(f"- {key}: {values[:5]}...")
        chunks.append({
            "section": "cashflows",
            "content": f"Cash Flow Projections from '{filename}':\n" + "\n".join(lines),
            "metadata": {
                "source_sheet": "CashFlows",
                "source_file": filename,
                "line_items": list(data.keys()),
            },
        })

    return chunks


def vectorize_and_store(
    db: Session,
    model_id: str,
    parsed_json: dict,
    filename: str,
    user_id: str | None = None,
) -> int:
    """
    Vectorize a parsed financial model and store chunks with embeddings in pgvector.
    Returns number of chunks stored.
    """
    # Delete existing chunks for this model (re-vectorization)
    db.execute(text("DELETE FROM document_chunks WHERE model_id = :mid"), {"mid": model_id})

    chunks = chunk_model_data(parsed_json, filename)
    stored = 0

    for idx, chunk in enumerate(chunks):
        try:
            embedding = get_embedding(chunk["content"])
            chunk_id = str(uuid.uuid4())

            # Insert with pgvector embedding
            db.execute(
                text("""
                    INSERT INTO document_chunks (id, model_id, user_id, chunk_index, section, content, metadata, embedding)
                    VALUES (:id, :model_id, :user_id, :chunk_index, :section, :content, :metadata, CAST(:embedding AS vector))
                """),
                {
                    "id": chunk_id,
                    "model_id": model_id,
                    "user_id": user_id,
                    "chunk_index": idx,
                    "section": chunk["section"],
                    "content": chunk["content"],
                    "metadata": json.dumps(chunk["metadata"]),
                    "embedding": str(embedding),
                },
            )
            stored += 1
        except Exception as e:
            print(f"[vectorize] Error embedding chunk {idx} ({chunk['section']}): {e}")
            continue

    db.commit()
    return stored


def similarity_search(
    db: Session,
    query: str,
    model_id: str,
    top_k: int = 5,
    section_filter: str | None = None,
) -> list[dict]:
    """
    Perform cosine similarity search against vectorized model chunks.
    Returns top_k most relevant chunks with their metadata.
    """
    query_embedding = get_embedding(query)

    section_clause = ""
    params: dict[str, Any] = {
        "embedding": str(query_embedding),
        "model_id": model_id,
        "top_k": top_k,
    }

    if section_filter:
        section_clause = "AND section = :section"
        params["section"] = section_filter

    results = db.execute(
        text(f"""
            SELECT id, section, content, metadata,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM document_chunks
            WHERE model_id = :model_id {section_clause}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """),
        params,
    ).fetchall()

    return [
        {
            "chunk_id": str(row[0]),
            "section": row[1],
            "content": row[2],
            "metadata": row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {},
            "similarity": round(float(row[4]), 4),
        }
        for row in results
    ]
