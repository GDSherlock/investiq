"""WS /assistant/chat — AssistantAgent streaming chat responses.
POST /assistant/chat-persona — Persona-toned LLM chat."""

import os
import sys
import json
from typing import Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

from ..database import get_db, SessionLocal
from ..models import FinancialModel, AuditLog
from ..llm_service import chat_response as llm_chat_response
from ..vector_service import similarity_search

router = APIRouter()


class PersonaChatRequest(BaseModel):
    model_id: str
    query: str
    persona: dict[str, Any]
    history: list[dict[str, str]] = []


@router.post("/assistant/chat-persona")
async def persona_chat(
    req: PersonaChatRequest,
    db: Session = Depends(get_db),
):
    """Persona-toned chat response using Azure OpenAI LLM."""
    model = db.query(FinancialModel).filter(FinancialModel.id == req.model_id).first()
    if not model or not model.parsed_json:
        raise HTTPException(status_code=404, detail="Model not found or not parsed")

    parsed = model.parsed_json
    cover = parsed.get("cover", {})
    returns = parsed.get("returns", {})
    assumptions = parsed.get("assumptions", [])
    sensitivity = parsed.get("sensitivity", {})
    capex = parsed.get("capex", {})
    debt = parsed.get("debt_schedule", {})

    # Build concise model context
    context_parts = []
    context_parts.append("## Project")
    for k in ["Project", "Operator", "Location", "Total Capex", "Financing",
              "Construction", "Operations", "Project IRR", "NPV @ WACC", "DSCR (avg)", "Payback"]:
        if k in cover:
            context_parts.append(f"- {k}: {cover[k]}")

    context_parts.append("\n## Returns")
    for m in returns.get("metrics", []):
        context_parts.append(
            f"- {m.get('metric','')}: Base={m.get('base_case','')}, "
            f"Stress={m.get('stress_case','')}, Upside={m.get('upside_case','')}, "
            f"Status={m.get('status','')}"
        )

    context_parts.append("\n## Key Assumptions")
    for a in assumptions[:15]:
        context_parts.append(f"- {a.get('name')}: {a.get('value')}")

    context_parts.append("\n## Sensitivity (Top 5)")
    for item in sensitivity.get("one_way", [])[:5]:
        context_parts.append(
            f"- {item.get('assumption','')}: Base {item.get('base_case','')}, "
            f"-20%={item.get('stress_minus_20','')}, +20%={item.get('upside_plus_20','')}"
        )

    cap_data = capex.get("data", {})
    cons = cap_data.get("Construction capex total", [])
    if cons:
        context_parts.append(f"\n## Capex: Construction={cons[:3]}, Total base={sum(float(c or 0) for c in cons)}")

    debt_data = debt.get("data", {})
    dscr_vals = debt_data.get("DSCR", [])
    if dscr_vals:
        context_parts.append(f"## DSCR by year: {dscr_vals}")

    model_context = "\n".join(context_parts)

    # RAG: Retrieve relevant chunks from vector store for this query
    rag_chunks = []
    try:
        rag_chunks = similarity_search(db, req.query, req.model_id, top_k=5)
    except Exception as e:
        print(f"[assistant] RAG retrieval warning (non-fatal): {e}")
        db.rollback()

    try:
        answer = llm_chat_response(req.persona, model_context, req.query, req.history, rag_chunks=rag_chunks)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM chat failed: {str(e)}")

    # Build citation sources from retrieved chunks
    sources = []
    for chunk in rag_chunks:
        meta = chunk.get("metadata", {})
        sources.append({
            "section": chunk.get("section", ""),
            "source_sheet": meta.get("source_sheet", ""),
            "source_file": meta.get("source_file", ""),
            "similarity": chunk.get("similarity", 0),
        })

    db.add(AuditLog(
        action="assistant_chat_persona",
        entity_type="AssistantChat",
        payload={
            "query": req.query,
            "model_id": req.model_id,
            "persona": req.persona.get("name", "Unknown"),
            "rag_chunks_used": len(rag_chunks),
        },
    ))
    db.commit()

    return {
        "response": answer,
        "persona": req.persona.get("name", "Unknown"),
        "confidence": 0.9,
        "sources": sources,
    }


@router.websocket("/assistant/chat")
async def assistant_chat(websocket: WebSocket):
    """WebSocket endpoint for NL Q&A with model context."""
    await websocket.accept()
    db = SessionLocal()

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            query = message.get("query", "")
            model_id = message.get("model_id")

            # Get model context if provided
            context = {}
            if model_id:
                model = db.query(FinancialModel).filter(FinancialModel.id == model_id).first()
                if model and model.parsed_json:
                    context = {
                        "cover": model.parsed_json.get("cover", {}),
                        "returns": model.parsed_json.get("returns", {}),
                        "assumptions_count": len(model.parsed_json.get("assumptions", [])),
                    }

            # Process query and generate response
            response = _process_query(query, context)

            db.add(AuditLog(
                action="assistant_query",
                entity_type="AssistantChat",
                payload={"query": query, "model_id": model_id},
            ))
            db.commit()

            await websocket.send_json({
                "response": response["answer"],
                "sources": response.get("sources", []),
                "confidence": response.get("confidence", 0.7),
            })

    except WebSocketDisconnect:
        pass
    finally:
        db.close()


def _process_query(query: str, context: dict) -> dict:
    """Process a natural language query against model context."""
    query_lower = query.lower()

    # Pattern-match common financial queries
    if any(w in query_lower for w in ["irr", "return", "internal rate"]):
        returns = context.get("returns", {})
        metrics = returns.get("metrics", [])
        irr_metrics = [m for m in metrics if "IRR" in m.get("metric", "")]
        if irr_metrics:
            answer = "Based on the financial model:\n"
            for m in irr_metrics:
                answer += f"- **{m['metric']}**: Base={m.get('base_case')}, Stress={m.get('stress_case')}, Upside={m.get('upside_case')} (Hurdle: {m.get('hurdle')}, Status: {m.get('status')})\n"
            return {"answer": answer, "sources": ["Returns sheet"], "confidence": 0.95}

    if any(w in query_lower for w in ["npv", "net present value"]):
        returns = context.get("returns", {})
        metrics = returns.get("metrics", [])
        npv_metrics = [m for m in metrics if "NPV" in m.get("metric", "")]
        if npv_metrics:
            m = npv_metrics[0]
            return {
                "answer": f"NPV @ WACC: Base Case = {m.get('base_case')} USD M, Stress = {m.get('stress_case')} USD M, Upside = {m.get('upside_case')} USD M.",
                "sources": ["Returns sheet"],
                "confidence": 0.95,
            }

    if any(w in query_lower for w in ["dscr", "debt service", "covenant"]):
        returns = context.get("returns", {})
        metrics = returns.get("metrics", [])
        dscr_metrics = [m for m in metrics if "DSCR" in m.get("metric", "")]
        if dscr_metrics:
            answer = "DSCR Analysis:\n"
            for m in dscr_metrics:
                answer += f"- **{m['metric']}**: Base={m.get('base_case')}, Stress={m.get('stress_case')} (Status: {m.get('status')})\n"
            return {"answer": answer, "sources": ["Returns sheet", "Debt_Schedule sheet"], "confidence": 0.9}

    if any(w in query_lower for w in ["project", "summary", "overview"]):
        cover = context.get("cover", {})
        if cover:
            answer = "**Project Summary:**\n"
            for k, v in cover.items():
                answer += f"- {k}: {v}\n"
            return {"answer": answer, "sources": ["Cover sheet"], "confidence": 0.95}

    return {
        "answer": f"I can help with financial model analysis. Try asking about IRR, NPV, DSCR, project summary, or specific assumptions. Your query: '{query}'",
        "sources": [],
        "confidence": 0.5,
    }
