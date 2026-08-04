"""Repository for persistent, idempotent persona report conversations."""

from __future__ import annotations

from collections.abc import Mapping
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .report_chat_models import ReportChatMessageRecord, ReportChatThreadRecord
from .report_chat_schemas import PersonaId


class ReportChatRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_thread(
        self, model_version_id: str, owner_key: str
    ) -> ReportChatThreadRecord | None:
        return self._session.scalar(
            select(ReportChatThreadRecord).where(
                ReportChatThreadRecord.model_version_id == model_version_id,
                ReportChatThreadRecord.owner_key == owner_key,
            )
        )

    def get_or_create_thread(
        self, model_version_id: str, owner_key: str
    ) -> ReportChatThreadRecord:
        existing = self.find_thread(model_version_id, owner_key)
        if existing is not None:
            return existing

        row = ReportChatThreadRecord(
            id=str(uuid.uuid4()),
            model_version_id=model_version_id,
            owner_key=owner_key,
        )
        self._session.add(row)
        try:
            self._session.commit()
            return row
        except IntegrityError:
            self._session.rollback()
            concurrent = self.find_thread(model_version_id, owner_key)
            if concurrent is None:
                raise
            return concurrent

    def list_messages(
        self, thread_id: str, limit: int = 200
    ) -> list[ReportChatMessageRecord]:
        return list(
            self._session.scalars(
                select(ReportChatMessageRecord)
                .where(ReportChatMessageRecord.thread_id == thread_id)
                .order_by(
                    ReportChatMessageRecord.created_at,
                    ReportChatMessageRecord.id,
                )
                .limit(limit)
            )
        )

    def append_user_message(
        self,
        *,
        thread_id: str,
        persona_id: PersonaId,
        text: str,
        graph_version_id: str,
        calculation_run_id: str,
        idempotency_key: str,
    ) -> tuple[ReportChatMessageRecord, bool]:
        existing = self._session.scalar(
            select(ReportChatMessageRecord).where(
                ReportChatMessageRecord.thread_id == thread_id,
                ReportChatMessageRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing, False

        row = ReportChatMessageRecord(
            id=str(uuid.uuid4()),
            thread_id=thread_id,
            role="user",
            kind="text",
            persona_id=persona_id,
            content_json={"kind": "text", "text": text},
            graph_version_id=graph_version_id,
            calculation_run_id=calculation_run_id,
            idempotency_key=idempotency_key,
        )
        self._session.add(row)
        try:
            self._session.commit()
            return row, True
        except IntegrityError:
            self._session.rollback()
            concurrent = self._session.scalar(
                select(ReportChatMessageRecord).where(
                    ReportChatMessageRecord.thread_id == thread_id,
                    ReportChatMessageRecord.idempotency_key == idempotency_key,
                )
            )
            if concurrent is None:
                raise
            return concurrent, False

    def find_response(
        self, user_message_id: str
    ) -> ReportChatMessageRecord | None:
        return self._session.scalar(
            select(ReportChatMessageRecord).where(
                ReportChatMessageRecord.response_to_message_id
                == user_message_id
            )
        )

    def get_message(
        self, thread_id: str, message_id: str
    ) -> ReportChatMessageRecord | None:
        return self._session.scalar(
            select(ReportChatMessageRecord).where(
                ReportChatMessageRecord.thread_id == thread_id,
                ReportChatMessageRecord.id == message_id,
            )
        )

    def append_assistant_message(
        self,
        *,
        user_message_id: str,
        persona_id: PersonaId,
        content: Mapping[str, object],
        graph_version_id: str,
        calculation_run_id: str,
    ) -> ReportChatMessageRecord:
        existing = self.find_response(user_message_id)
        if existing is not None:
            return existing

        user_message = self._session.get(
            ReportChatMessageRecord, user_message_id
        )
        if user_message is None:
            raise ValueError("User report-chat message does not exist.")

        row = ReportChatMessageRecord(
            id=str(uuid.uuid4()),
            thread_id=user_message.thread_id,
            response_to_message_id=user_message_id,
            role="assistant",
            kind=str(content["kind"]),
            persona_id=persona_id,
            content_json=dict(content),
            graph_version_id=graph_version_id,
            calculation_run_id=calculation_run_id,
            idempotency_key=None,
        )
        self._session.add(row)
        try:
            self._session.commit()
            return row
        except IntegrityError:
            self._session.rollback()
            concurrent = self.find_response(user_message_id)
            if concurrent is None:
                raise
            return concurrent
