"""POST /reports/generate — ReportAgent; generates IC papers / board packs."""

import json
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Report, Investment, FinancialModel, Scenario, AuditLog
from ..llm_service import generate_report as llm_generate_report
from ..vector_service import similarity_search

router = APIRouter()


class PersonaReportRequest(BaseModel):
    model_id: str
    persona: dict[str, Any]


@router.post("/reports/persona-generate")
async def persona_generate_report(
    req: PersonaReportRequest,
    db: Session = Depends(get_db),
):
    """Generate a persona-toned report using Azure OpenAI LLM."""
    model = db.query(FinancialModel).filter(FinancialModel.id == req.model_id).first()
    if not model or not model.parsed_json:
        raise HTTPException(status_code=404, detail="Model not found or not parsed")

    parsed = model.parsed_json
    cover = parsed.get("cover", {})
    returns = parsed.get("returns", {})
    sensitivity = parsed.get("sensitivity", {})
    assumptions = parsed.get("assumptions", [])
    checks = parsed.get("checks", [])
    capex = parsed.get("capex", {})
    debt = parsed.get("debt_schedule", {})

    # Build comprehensive model context for the LLM
    context_parts = []

    context_parts.append("## Project Overview")
    for k, v in cover.items():
        context_parts.append(f"- {k}: {v}")

    context_parts.append("\n## Key Assumptions")
    for a in assumptions[:20]:
        context_parts.append(f"- {a.get('name')}: {a.get('value')} (Source: {a.get('source', 'Assumptions sheet')})")

    context_parts.append("\n## Investment Returns")
    context_parts.append("| Metric | Base Case | Stress Case | Upside Case | Hurdle | Status |")
    context_parts.append("|--------|-----------|-------------|-------------|--------|--------|")
    for m in returns.get("metrics", []):
        context_parts.append(
            f"| {m.get('metric','')} | {m.get('base_case','')} | {m.get('stress_case','')} "
            f"| {m.get('upside_case','')} | {m.get('hurdle','')} | {m.get('status','')} |"
        )

    context_parts.append("\n## Sensitivity Analysis (Top Drivers)")
    for item in sensitivity.get("one_way", [])[:8]:
        context_parts.append(
            f"- {item.get('assumption','')}: Base IRR {item.get('base_case','')}, "
            f"Range: {item.get('stress_minus_20','')}-{item.get('upside_plus_20','')}, "
            f"Key variable: {item.get('key_variable','')}"
        )

    context_parts.append("\n## Capex Schedule")
    cap_years = capex.get("years", [])
    construction_total = capex.get("data", {}).get("Construction capex total", [])
    maint = capex.get("data", {}).get("Maintenance capex", [])
    if cap_years:
        context_parts.append(f"- Years: {cap_years[0]}-{cap_years[-1]}")
        context_parts.append(f"- Construction capex by year: {construction_total[:5]}")
        context_parts.append(f"- Maintenance capex (first 5yr ops): {maint[3:8] if len(maint) > 3 else maint}")

    context_parts.append("\n## Debt Structure")
    debt_data = debt.get("data", {})
    interest = debt_data.get("Interest charge", [])
    repayment = debt_data.get("(Scheduled repayment)", [])
    if interest:
        context_parts.append(f"- Interest charges (first 5yr): {interest[:5]}")
        context_parts.append(f"- Repayments (first 5yr): {repayment[:5]}")

    context_parts.append("\n## Model Integrity Checks")
    for c in checks[:10]:
        context_parts.append(
            f"- {c.get('description','')}: Value={c.get('value','')}, "
            f"Expected={c.get('expected','')}, Status={c.get('status','')}"
        )

    model_context = "\n".join(context_parts)

    # RAG: Retrieve relevant chunks from vector store
    rag_chunks = []
    try:
        report_type_hint = req.persona.get("report_system_addendum", {}).get("report_type_default", "Report")
        query_text = f"Generate {report_type_hint} covering returns, assumptions, debt, sensitivity"
        rag_chunks = similarity_search(db, query_text, model_id, top_k=8)
    except Exception as e:
        print(f"[reports] RAG retrieval warning (non-fatal): {e}")

    # Call LLM with RAG context
    try:
        content_md = llm_generate_report(req.persona, model_context, rag_chunks=rag_chunks)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {str(e)}")

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

    persona_name = req.persona.get("name", "Unknown")
    report_type = req.persona.get("report_system_addendum", {}).get(
        "report_type_default", "Report"
    )

    report = Report(
        id=str(uuid.uuid4()),
        investment_id=None,
        report_type=report_type,
        audience=persona_name,
        content_md=content_md,
        model_snapshot_id=model.id,
    )
    db.add(report)
    db.add(AuditLog(
        action="report_generate_persona",
        entity_type="Report",
        entity_id=report.id,
        payload={"persona": persona_name, "report_type": report_type, "model_id": req.model_id},
    ))
    db.commit()

    return {
        "report_id": report.id,
        "status": "completed",
        "content": content_md,
        "format": "markdown",
        "report_type": report_type,
        "persona": persona_name,
        "sources": sources,
    }


@router.post("/reports/generate")
async def generate_report(
    investment_id: str,
    report_type: str = "ic_paper",
    audience: str = "investment_committee",
    db: Session = Depends(get_db),
):
    """Generate a structured report (IC paper / board pack)."""
    investment = db.query(Investment).filter(Investment.id == investment_id).first()
    if not investment:
        raise HTTPException(status_code=404, detail="Investment not found")

    model = (
        db.query(FinancialModel)
        .filter(FinancialModel.investment_id == investment_id)
        .order_by(FinancialModel.uploaded_at.desc())
        .first()
    )
    if not model or not model.parsed_json:
        raise HTTPException(status_code=404, detail="No parsed model found")

    parsed = model.parsed_json
    cover = parsed.get("cover", {})
    returns = parsed.get("returns", {})
    sensitivity = parsed.get("sensitivity", {})
    checks = parsed.get("checks", [])

    # Generate markdown report
    metrics_table = ""
    for m in returns.get("metrics", []):
        metrics_table += f"| {m.get('metric', '')} | {m.get('base_case', '')} | {m.get('stress_case', '')} | {m.get('upside_case', '')} | {m.get('hurdle', '')} | {m.get('status', '')} |\n"

    checks_table = ""
    for c in checks:
        checks_table += f"| {c.get('description', '')} | {c.get('value', '')} | {c.get('expected', '')} | {c.get('status', '')} |\n"

    content_md = f"""# Investment Committee Paper — {investment.name}

## Executive Summary

**Project:** {cover.get('Project', investment.name)}
**Operator:** {cover.get('Operator', 'N/A')}
**Location:** {cover.get('Location', 'N/A')}
**Total Capex:** {cover.get('Total Capex', 'N/A')}
**Financing:** {cover.get('Financing', 'N/A')}

## Investment Returns

| Metric | Base Case | Stress Case | Upside Case | Hurdle | Status |
|--------|-----------|-------------|-------------|--------|--------|
{metrics_table}

## Key Sensitivities

Top risk drivers identified from sensitivity analysis:
"""

    for item in sensitivity.get("one_way", [])[:5]:
        content_md += f"- **{item.get('assumption', '')}**: IRR range {item.get('irr_range', 'N/A')} — {item.get('key_variable', 'N/A')}\n"

    content_md += f"""

## Model Integrity

| Check | Value | Expected | Status |
|-------|-------|----------|--------|
{checks_table}

## Recommendation

Based on the financial analysis, the project meets the investment criteria with a base-case
Project IRR of {cover.get('Project IRR', 'N/A')} and Equity IRR of {cover.get('Equity IRR', 'N/A')}.

---
*Generated by InvestIQ ReportAgent | Model: {model.original_filename} | Health Score: {model.health_score}*
"""

    report = Report(
        id=str(uuid.uuid4()),
        investment_id=investment_id,
        report_type=report_type,
        audience=audience,
        content_md=content_md,
        model_snapshot_id=model.id,
    )
    db.add(report)
    db.add(AuditLog(
        action="report_generate",
        entity_type="Report",
        entity_id=report.id,
        payload={"report_type": report_type, "audience": audience},
    ))
    db.commit()

    return {
        "report_id": report.id,
        "status": "completed",
        "content": content_md,
        "format": "markdown",
    }


@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    db: Session = Depends(get_db),
):
    """Get a generated report."""
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return {
        "id": report.id,
        "investment_id": report.investment_id,
        "report_type": report.report_type,
        "audience": report.audience,
        "content": report.content_md,
        "version": report.version,
        "created_at": report.created_at,
    }
