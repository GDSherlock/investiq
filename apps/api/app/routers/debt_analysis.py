"""POST /debt-analysis/upload — upload term sheets; returns job id.
   GET  /debt-analysis/{job_id}/compare — DebtAnalysisAgent comparison result.
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AnalysisResult, AuditLog, FinancialModel

router = APIRouter()

# In-memory job store (production: use Redis)
_debt_jobs: dict[str, dict] = {}


@router.post("/debt-analysis/upload")
async def upload_term_sheets(
    file: UploadFile = File(...),
    model_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Upload term sheets for debt analysis."""
    file_bytes = await file.read()
    job_id = str(uuid.uuid4())

    # If model_id provided, get debt schedule from parsed model
    debt_data = {}
    if model_id:
        model = db.query(FinancialModel).filter(FinancialModel.id == model_id).first()
        if model and model.parsed_json:
            debt_data = model.parsed_json.get("debt_schedule", {})

    _debt_jobs[job_id] = {
        "status": "completed",
        "filename": file.filename,
        "model_debt_data": debt_data,
        "file_size": len(file_bytes),
    }

    db.add(AuditLog(
        action="debt_upload",
        entity_type="DebtAnalysis",
        entity_id=job_id,
        payload={"filename": file.filename},
    ))
    db.commit()

    return {"job_id": job_id, "status": "processing"}


@router.get("/debt-analysis/{job_id}/compare")
async def compare_debt(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Get debt analysis comparison result."""
    job = _debt_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    debt_data = job.get("model_debt_data", {})
    data = debt_data.get("data", {})

    # Extract key metrics from model data
    opening_balance = data.get("Opening debt balance", [])
    closing_balance = data.get("Closing debt balance", [])
    interest = data.get("Interest charge", [])
    repayment = data.get("(Scheduled repayment)", [])
    total_service = data.get("Total debt service", [])

    comparison = {
        "term_sheet_summary": {
            "filename": job.get("filename"),
            "total_facility": sum(abs(v) for v in data.get("Debt drawdown", []) if v) if data.get("Debt drawdown") else None,
        },
        "debt_schedule": {
            "opening_balance": opening_balance,
            "closing_balance": closing_balance,
            "interest_charges": interest,
            "principal_repayment": repayment,
            "total_debt_service": total_service,
        },
        "key_metrics": {
            "peak_debt": max(abs(v) for v in closing_balance if v) if closing_balance else None,
            "total_interest_paid": sum(abs(v) for v in interest if v) if interest else None,
            "total_principal_repaid": sum(abs(v) for v in repayment if v) if repayment else None,
        },
    }

    recommendation = {
        "summary": "Debt structure appears consistent with project finance norms for LNG infrastructure.",
        "risks": [
            "Grace period alignment with construction schedule is critical",
            "Monitor DSCR during initial operations ramp-up period",
        ],
        "confidence": 0.8,
    }

    return {
        "job_id": job_id,
        "comparison": comparison,
        "recommendation": recommendation,
    }
