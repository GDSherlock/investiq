from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from apps.api.app.report_chat_evidence import ReportChatEvidenceBuilder
from apps.api.app.report_chat_generator import (
    ReportChatGenerationError,
    ReportChatGenerator,
)


class _FakeResponses:
    def __init__(self) -> None:
        self.output_text = ""
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class _FakeClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()


def _user_message(
    text: str,
    *,
    message_id: str = "11111111-1111-4111-8111-111111111111",
    created_at: datetime | None = None,
):
    return SimpleNamespace(
        id=message_id,
        role="user",
        content_json={"kind": "text", "text": text},
        created_at=created_at or datetime(2026, 8, 4, tzinfo=timezone.utc),
    )


def _catalog():
    return ReportChatEvidenceBuilder().build(
        snapshot={
            "calculation": {
                "overview": {
                    "kpis": [
                        {
                            "label": "Minimum DSCR",
                            "value": "1.3",
                            "unit": "x",
                            "availability_status": "available",
                            "source_ids": [
                                "22222222-2222-4222-8222-222222222222"
                            ],
                        }
                    ],
                    "charts": [],
                },
                "cash_flow": {"charts": []},
            },
            "assumptions": [],
            "sensitivity": None,
            "monte_carlo": None,
        },
        messages=[
            _user_message(
                "Generate a CFO Funding Note",
                message_id="44444444-4444-4444-8444-444444444444",
            ),
            _user_message("Construction will be delayed by two months"),
        ],
    )


def test_builder_omits_unavailable_values_and_labels_sources() -> None:
    catalog = ReportChatEvidenceBuilder().build(
        snapshot={
            "calculation": {
                "overview": {
                    "kpis": [
                        {
                            "label": "Project IRR",
                            "value": "0.12",
                            "availability_status": "available",
                            "source_ids": ["output-1"],
                        },
                        {
                            "label": "NPV",
                            "value": None,
                            "availability_status": "unavailable",
                            "source_ids": [],
                        },
                    ],
                    "charts": [],
                },
                "cash_flow": {"charts": []},
            },
            "assumptions": [],
            "sensitivity": None,
            "monte_carlo": None,
        },
        messages=[
            _user_message(
                "Generate a CFO Funding Note",
                message_id="44444444-4444-4444-8444-444444444444",
            ),
            _user_message("Construction will be delayed by two months"),
        ],
    )

    assert [item.id for item in catalog.items] == ["M1", "U1"]
    assert catalog.items[0].source_type == "model"
    assert catalog.items[0].source_ref == "output-1"
    assert catalog.items[1].source_type == "user"
    assert catalog.items[1].message_id == (
        "11111111-1111-4111-8111-111111111111"
    )
    assert "NPV" not in catalog.model_dump_json()


def test_generator_rejects_unknown_citation() -> None:
    client = _FakeClient()
    client.responses.output_text = json.dumps(
        {
            "kind": "report",
            "report": {
                "title": "CFO Funding Note",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "text": "DSCR is 1.3x.",
                        "citation_ids": ["M99"],
                    }
                ],
            },
        }
    )

    with pytest.raises(ReportChatGenerationError, match="M99"):
        ReportChatGenerator(client, deployment="test-deployment").generate(
            "CF",
            "Generate a CFO Funding Note",
            [],
            _catalog(),
        )


def test_other_personas_fixed_report_prompt_requests_a_switch_without_llm() -> None:
    client = _FakeClient()

    content = ReportChatGenerator(client).generate(
        "CF",
        "Generate a Board One-Pager",
        [],
        _catalog(),
    )

    assert content.kind == "text"
    assert "Board Director" in content.text
    assert "switch" in content.text.lower()
    assert client.responses.calls == []


def test_generation_prompt_prioritizes_later_user_corrections_and_conflicts() -> None:
    client = _FakeClient()
    client.responses.output_text = json.dumps(
        {
            "kind": "report",
            "report": {
                "title": "CFO Funding Note",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "text": "Minimum DSCR is 1.3x.",
                        "citation_ids": ["M1"],
                    }
                ],
            },
        }
    )

    ReportChatGenerator(client, deployment="test-deployment").generate(
        "CF",
        "Generate a CFO Funding Note",
        [
            _user_message("The delay is three months"),
            _user_message(
                "Correction: the delay is two months",
                message_id="33333333-3333-4333-8333-333333333333",
                created_at=datetime(2026, 8, 4, 1, tzinfo=timezone.utc),
            ),
        ],
        _catalog(),
    )

    developer_prompt = client.responses.calls[0]["input"][0]["content"]
    assert "later user corrections supersede earlier user statements" in (
        developer_prompt
    )
    assert "state model/user conflicts explicitly" in developer_prompt
    assert "omit unsupported topics" in developer_prompt


def test_valid_report_uses_server_owned_citation_metadata() -> None:
    client = _FakeClient()
    client.responses.output_text = json.dumps(
        {
            "kind": "report",
            "report": {
                "title": "CFO Funding Note",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "text": "Minimum DSCR is 1.3x.",
                        "citation_ids": ["M1"],
                    }
                ],
                "citations": [],
            },
        }
    )

    content = ReportChatGenerator(
        client, deployment="test-deployment"
    ).generate("CF", "Generate a CFO Funding Note", [], _catalog())

    assert content.report.citations[0].model_dump() == {
        "id": "M1",
        "source_type": "model",
        "label": "Minimum DSCR",
        "source_ref": "22222222-2222-4222-8222-222222222222",
        "message_id": None,
    }
