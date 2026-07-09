"""GET /investments/{id}/monitor — MonitorAgent dashboard + alerts."""

import os
import sys
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

from ..database import get_db
from ..models import Investment, FinancialModel, Alert, AuditLog
from libs.tools.dscr_monitor import DSCRMonitor
from libs.calc_engine.dscr import compute_dscr

router = APIRouter()


@router.get("/investments/{investment_id}/monitor")
async def monitor_investment(
    investment_id: str,
    db: Session = Depends(get_db),
):
    """Get monitoring dashboard with KPIs, DSCR status, and alerts."""
    investment = db.query(Investment).filter(Investment.id == investment_id).first()
    if not investment:
        raise HTTPException(status_code=404, detail="Investment not found")

    # Get latest model
    model = (
        db.query(FinancialModel)
        .filter(FinancialModel.investment_id == investment_id)
        .order_by(FinancialModel.uploaded_at.desc())
        .first()
    )
    if not model or not model.parsed_json:
        raise HTTPException(status_code=404, detail="No parsed model found")

    parsed = model.parsed_json
    pnl_data = parsed.get("pnl", {})
    debt_data = parsed.get("debt_schedule", {})
    returns_data = parsed.get("returns", {})
    years = pnl_data.get("years", [])

    # DSCR monitoring
    ebitda = [float(v) if v else 0 for v in pnl_data.get("data", {}).get("EBITDA", [])]
    interest = [abs(float(v)) if v else 0 for v in debt_data.get("data", {}).get("Interest charge", [])]
    principal = [abs(float(v)) if v else 0 for v in debt_data.get("data", {}).get("(Scheduled repayment)", [])]

    dscr_result = compute_dscr(ebitda, interest, principal)
    monitor = DSCRMonitor(breach_threshold=1.25, amber_threshold=1.35)
    dscr_monitor_result = monitor.evaluate(dscr_result.get("annual_dscr", []), years)

    # Generate alerts in DB
    for alert_data in dscr_monitor_result.get("alerts", []):
        db.add(Alert(
            investment_id=investment_id,
            alert_type=alert_data["alert_type"],
            threshold=alert_data.get("threshold"),
            current_value=alert_data.get("dscr"),
            severity=alert_data["severity"],
            message=alert_data["message"],
        ))

    # KPIs from returns
    kpis = {}
    for m in returns_data.get("metrics", []):
        kpis[m.get("metric", "")] = {
            "base_case": m.get("base_case"),
            "hurdle": m.get("hurdle"),
            "status": m.get("status"),
        }

    # Revenue variance (actual vs plan placeholder)
    revenue_data = pnl_data.get("data", {}).get("Revenue (from Revenue sheet)", [])

    db.add(AuditLog(
        action="monitor_dashboard_view",
        entity_type="Investment",
        entity_id=investment_id,
    ))
    db.commit()

    return {
        "investment_id": investment_id,
        "investment_name": investment.name,
        "kpis": kpis,
        "dscr_status": dscr_monitor_result.get("dashboard", []),
        "alerts": dscr_monitor_result.get("alerts", []),
        "dscr_summary": dscr_result.get("result", {}),
        "revenue_trend": {
            "years": years,
            "values": revenue_data,
        },
        "variance_analysis": {
            "note": "Actual vs plan comparison requires actuals data upload",
        },
    }
