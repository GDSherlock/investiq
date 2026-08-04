"""Persistence records for shared persona report conversations."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
)

from .database import Base
from .model_extraction_models import utcnow


class ReportChatThreadRecord(Base):
    __tablename__ = "report_chat_threads"
    __table_args__ = (
        UniqueConstraint(
            "model_version_id",
            "owner_key",
            name="uq_report_chat_threads_model_owner",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    model_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_key = Column(String(160), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class ReportChatMessageRecord(Base):
    __tablename__ = "report_chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_report_chat_messages_role",
        ),
        CheckConstraint(
            "kind IN ('text', 'report', 'error')",
            name="ck_report_chat_messages_kind",
        ),
        CheckConstraint(
            "persona_id IN ('IM', 'CF', 'BD', 'FA', 'PO')",
            name="ck_report_chat_messages_persona",
        ),
        UniqueConstraint(
            "thread_id",
            "idempotency_key",
            name="uq_report_chat_messages_thread_idempotency",
        ),
        UniqueConstraint(
            "response_to_message_id",
            name="uq_report_chat_messages_response_to",
        ),
        Index(
            "ix_report_chat_messages_thread_created",
            "thread_id",
            "created_at",
            "id",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    thread_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("report_chat_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    response_to_message_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("report_chat_messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    role = Column(String(16), nullable=False)
    kind = Column(String(16), nullable=False)
    persona_id = Column(String(2), nullable=False)
    content_json = Column(JSON, nullable=False)
    graph_version_id = Column(Uuid(as_uuid=False), nullable=False)
    calculation_run_id = Column(Uuid(as_uuid=False), nullable=False)
    idempotency_key = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
