"""Cited, structured report generation from server-owned evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from pydantic import ValidationError

from . import llm_service
from .report_chat_evidence import ReportEvidenceCatalog, ReportEvidenceItem
from .report_chat_schemas import (
    PersonaId,
    ReportChatAssistantContent,
    ReportCitation,
)
from .report_personas import get_report_persona


class ReportChatGenerationError(RuntimeError):
    """Raised when the model returns an unsafe or unsupported report shape."""


class ReportChatGenerator:
    def __init__(self, client=None, *, deployment: str | None = None) -> None:
        self._client = client
        self._deployment = deployment or llm_service._DEPLOYMENT

    def generate(
        self,
        persona_id: PersonaId,
        request: str,
        history: Sequence[object],
        catalog: ReportEvidenceCatalog,
    ) -> ReportChatAssistantContent:
        profile = get_report_persona(persona_id)
        switch_response = self._fixed_report_switch_response(persona_id, request)
        if switch_response is not None:
            return ReportChatAssistantContent(kind="text", text=switch_response)

        if self._client is None:
            self._client = llm_service._get_client()
        response = self._client.responses.create(
            model=self._deployment,
            input=[
                {
                    "role": "developer",
                    "content": self._developer_prompt(profile, catalog),
                },
                {
                    "role": "user",
                    "content": self._user_prompt(request, history),
                },
            ],
            max_output_tokens=8192,
        )
        return self._validate_output(response.output_text, profile.report_type, catalog)

    @staticmethod
    def _fixed_report_switch_response(
        persona_id: PersonaId, request: str
    ) -> str | None:
        normalized_request = request.strip().casefold()
        for candidate_id in ("IM", "CF", "BD", "FA", "PO"):
            if candidate_id == persona_id:
                continue
            candidate = get_report_persona(candidate_id)
            if normalized_request == candidate.primary_prompt.casefold():
                return (
                    f"Please switch to the {candidate.name} persona to generate "
                    f"its {candidate.report_type}."
                )
        return None

    @staticmethod
    def _developer_prompt(profile, catalog: ReportEvidenceCatalog) -> str:
        evidence_json = json.dumps(
            catalog.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            "You are InvestIQ's evidence-grounded report generator.\n"
            f"Generate only an English {profile.report_type}.\n"
            f"Persona focus: {', '.join(profile.focus)}.\n"
            f"Persona instruction: {profile.system_addendum}\n"
            "Use only facts in the supplied evidence catalog. Do not infer or "
            "invent missing facts. Always omit unsupported topics and sections; "
            "never narrate them as unavailable; later user corrections supersede "
            "earlier user statements. If model evidence and user evidence conflict, "
            "state model/user conflicts explicitly and cite both.\n"
            "Return JSON only. The root is either "
            '{"kind":"text","text":"..."} or '
            '{"kind":"report","report":{"title":"...","blocks":[...]}}. '
            "Allowed report blocks are heading, paragraph, bullet_list, "
            "numbered_list, and table. Every non-heading block must contain one "
            "or more citation_ids copied exactly from the evidence catalog. Do not "
            "return HTML or Markdown.\n"
            f"Evidence catalog: {evidence_json}"
        )

    @staticmethod
    def _user_prompt(request: str, history: Sequence[object]) -> str:
        history_entries: list[dict[str, Any]] = []
        for message in history[-20:]:
            role = getattr(message, "role", None)
            content = getattr(message, "content_json", None)
            if not isinstance(role, str) or not isinstance(content, Mapping):
                continue
            if isinstance(content.get("text"), str):
                history_entries.append(
                    {"role": role, "text": content["text"]}
                )
            elif isinstance(content.get("report"), Mapping):
                history_entries.append(
                    {
                        "role": role,
                        "report_title": content["report"].get("title"),
                    }
                )
        return (
            "Conversation history: "
            + json.dumps(history_entries, ensure_ascii=False)
            + "\nCurrent request: "
            + request
        )

    @staticmethod
    def _validate_output(
        output_text: str,
        report_type: str,
        catalog: ReportEvidenceCatalog,
    ) -> ReportChatAssistantContent:
        try:
            payload = json.loads(output_text)
            if isinstance(payload, dict):
                report = payload.get("report")
                if isinstance(report, dict):
                    report = dict(report)
                    report.pop("citations", None)
                    payload = {**payload, "report": report}
            content = ReportChatAssistantContent.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise ReportChatGenerationError(
                f"Invalid structured report response: {error}"
            ) from error

        if content.kind == "text":
            return content
        if content.report is None:
            raise ReportChatGenerationError("Report response has no document.")
        if content.report.title != report_type:
            raise ReportChatGenerationError(
                f"Expected report title '{report_type}', got "
                f"'{content.report.title}'."
            )

        used_ids: list[str] = []
        for block in content.report.blocks:
            if block.kind != "heading" and not block.citation_ids:
                raise ReportChatGenerationError(
                    "Every narrative report block requires citations."
                )
            for citation_id in block.citation_ids:
                if citation_id not in used_ids:
                    used_ids.append(citation_id)
        if not used_ids:
            raise ReportChatGenerationError(
                "A report must cite at least one available evidence item."
            )

        evidence_by_id = catalog.by_id()
        unknown_ids = [item_id for item_id in used_ids if item_id not in evidence_by_id]
        if unknown_ids:
            raise ReportChatGenerationError(
                "Unknown evidence citation IDs: " + ", ".join(unknown_ids)
            )
        content.report.citations = [
            ReportChatGenerator._citation(evidence_by_id[item_id])
            for item_id in used_ids
        ]
        return content

    @staticmethod
    def _citation(item: ReportEvidenceItem) -> ReportCitation:
        return ReportCitation(
            id=item.id,
            source_type=item.source_type,
            label=item.label,
            source_ref=item.source_ref,
            message_id=item.message_id,
        )
