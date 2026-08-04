"""Application orchestration for persona report conversations."""

from __future__ import annotations

from datetime import UTC
from typing import cast

from .canonical_report_service import CanonicalReportService
from .report_chat_docx import ReportChatDocxRenderer, safe_docx_filename
from .report_chat_evidence import ReportChatEvidenceBuilder
from .report_chat_generator import ReportChatGenerator
from .report_chat_models import ReportChatMessageRecord
from .report_chat_repository import ReportChatRepository
from .report_chat_schemas import (
    PersonaId,
    ReportChatExchangeResponse,
    ReportChatMessageCreateRequest,
    ReportChatMessageResponse,
    ReportChatThreadResponse,
    ReportDocument,
)


class ReportChatNotFound(Exception):
    """The requested report thread or report message is inaccessible."""


class ReportChatService:
    def __init__(
        self,
        repository: ReportChatRepository,
        canonical_service: CanonicalReportService,
        evidence_builder: ReportChatEvidenceBuilder,
        generator: ReportChatGenerator,
        docx_renderer: ReportChatDocxRenderer,
    ) -> None:
        self._repository = repository
        self._canonical_service = canonical_service
        self._evidence_builder = evidence_builder
        self._generator = generator
        self._docx_renderer = docx_renderer

    def history(
        self, model_version_id: str, owner_key: str
    ) -> ReportChatThreadResponse:
        thread = self._repository.find_thread(model_version_id, owner_key)
        if thread is None:
            return ReportChatThreadResponse(
                thread_id=None,
                model_version_id=model_version_id,
                messages=[],
            )
        return ReportChatThreadResponse(
            thread_id=thread.id,
            model_version_id=model_version_id,
            messages=[
                self._message_response(row)
                for row in self._repository.list_messages(thread.id)
            ],
        )

    def send(
        self,
        model_version_id: str,
        owner_key: str,
        request: ReportChatMessageCreateRequest,
    ) -> ReportChatExchangeResponse:
        thread = self._repository.get_or_create_thread(
            model_version_id,
            owner_key,
        )
        user_row, _created = self._repository.append_user_message(
            thread_id=thread.id,
            persona_id=request.persona_id,
            text=request.message,
            graph_version_id=request.graph_version_id,
            calculation_run_id=request.calculation_run_id,
            idempotency_key=request.idempotency_key,
        )
        assistant_row = self._repository.find_response(user_row.id)
        if assistant_row is None:
            snapshot, _sensitivity_id, _monte_carlo_id = (
                self._canonical_service.freeze_analysis_evidence(
                    model_version_id,
                    graph_version_id=user_row.graph_version_id,
                    calculation_run_id=user_row.calculation_run_id,
                )
            )
            history = self._repository.list_messages(thread.id)
            catalog = self._evidence_builder.build(
                snapshot=snapshot,
                messages=history,
            )
            content = self._generator.generate(
                cast(PersonaId, user_row.persona_id),
                str(user_row.content_json["text"]),
                history,
                catalog,
            )
            assistant_row = self._repository.append_assistant_message(
                user_message_id=user_row.id,
                persona_id=cast(PersonaId, user_row.persona_id),
                content=content.model_dump(mode="json"),
                graph_version_id=user_row.graph_version_id,
                calculation_run_id=user_row.calculation_run_id,
            )
        return ReportChatExchangeResponse(
            thread_id=thread.id,
            user_message=self._message_response(user_row),
            assistant_message=self._message_response(assistant_row),
        )

    def export_docx(
        self,
        model_version_id: str,
        owner_key: str,
        message_id: str,
    ) -> tuple[str, bytes]:
        thread = self._repository.find_thread(model_version_id, owner_key)
        if thread is None:
            raise ReportChatNotFound("Report chat was not found.")
        row = self._repository.get_message(thread.id, message_id)
        if row is None or row.kind != "report":
            raise ReportChatNotFound("Report message was not found.")
        report = ReportDocument.model_validate(row.content_json["report"])
        return safe_docx_filename(report.title), self._docx_renderer.render(report)

    @staticmethod
    def _message_response(
        row: ReportChatMessageRecord,
    ) -> ReportChatMessageResponse:
        content = row.content_json
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        else:
            created_at = created_at.astimezone(UTC)
        return ReportChatMessageResponse(
            message_id=row.id,
            thread_id=row.thread_id,
            role=row.role,
            kind=row.kind,
            persona_id=row.persona_id,
            text=content.get("text"),
            report=content.get("report"),
            graph_version_id=row.graph_version_id,
            calculation_run_id=row.calculation_run_id,
            created_at=created_at,
        )
