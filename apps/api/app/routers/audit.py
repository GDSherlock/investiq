"""GET /audit/{entity_id} — full audit trail, paginated."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog

router = APIRouter()


@router.get("/audit/{entity_id}")
async def get_audit_trail(
    entity_id: str,
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Get full audit trail for an entity, paginated."""
    query = (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == entity_id)
        .order_by(AuditLog.timestamp.desc())
    )

    total = query.count()
    entries = query.offset(offset).limit(limit).all()

    return {
        "entity_id": entity_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": [
            {
                "id": e.id,
                "action": e.action,
                "entity_type": e.entity_type,
                "user_id": e.user_id,
                "session_id": e.session_id,
                "payload": e.payload,
                "timestamp": e.timestamp,
            }
            for e in entries
        ],
    }
