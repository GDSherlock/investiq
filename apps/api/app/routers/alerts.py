"""GET /alerts/active — active alerts."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Alert

router = APIRouter()


@router.get("/alerts/active")
async def get_active_alerts(
    investment_id: str | None = None,
    severity: str | None = None,
    db: Session = Depends(get_db),
):
    """Get active (unresolved) alerts."""
    query = db.query(Alert).filter(Alert.resolved_at.is_(None))

    if investment_id:
        query = query.filter(Alert.investment_id == investment_id)
    if severity:
        query = query.filter(Alert.severity == severity)

    alerts = query.order_by(Alert.created_at.desc()).limit(100).all()

    return {
        "count": len(alerts),
        "alerts": [
            {
                "id": a.id,
                "investment_id": a.investment_id,
                "alert_type": a.alert_type,
                "threshold": a.threshold,
                "current_value": a.current_value,
                "severity": a.severity,
                "message": a.message,
                "created_at": a.created_at,
            }
            for a in alerts
        ],
    }
