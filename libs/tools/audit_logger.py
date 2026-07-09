"""
Audit Logger — append-only audit trail for all operations.

Every user action, API call, agent invocation, tool call, and model state change
must be written to the audit log. Append-only; exportable.
"""

import uuid
from datetime import datetime, timezone
from typing import Any


class AuditLogger:
    """Audit logger that writes to PostgreSQL (via repository injection)."""

    def __init__(self, db_session=None):
        self._db = db_session
        self._buffer: list[dict[str, Any]] = []

    def log(
        self,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Record an audit entry.

        Args:
            action: What happened (e.g., 'model_upload', 'agent_invocation').
            entity_type: Type of entity (e.g., 'FinancialModel', 'Scenario').
            entity_id: ID of the affected entity.
            user_id: Who performed the action.
            session_id: Session context.
            payload: Additional data (inputs, outputs, etc.).

        Returns:
            The audit entry created.
        """
        entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "user_id": user_id,
            "session_id": session_id,
            "payload": payload or {},
        }

        self._buffer.append(entry)

        if self._db:
            self._persist(entry)

        return entry

    def _persist(self, entry: dict[str, Any]) -> None:
        """Persist entry to database."""
        if self._db:
            from apps.api.app.models import AuditLog
            record = AuditLog(**entry)
            self._db.add(record)
            self._db.commit()

    def get_entries(
        self,
        entity_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve audit entries, optionally filtered by entity_id."""
        if entity_id:
            return [e for e in self._buffer if e.get("entity_id") == entity_id][offset:offset+limit]
        return self._buffer[offset:offset+limit]

    def export(self) -> list[dict[str, Any]]:
        """Export full audit trail."""
        return list(self._buffer)
