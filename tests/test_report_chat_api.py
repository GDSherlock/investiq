from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.database import Base, get_db
from apps.api.app.main import app
from apps.api.app.model_extraction_models import CanonicalOutput
from apps.api.app.report_chat_generator import ReportChatGenerationError
from apps.api.app.report_chat_schemas import ReportChatAssistantContent
from apps.api.app.routers.report_chat import (
    get_report_chat_generator,
    report_chat_owner_key,
)
from tests.calculation_rule_test_support import create_materialized_rule_model
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


class FakeReportChatGenerator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_next = False

    def generate(self, persona_id, request, history, catalog):
        self.calls.append(
            {
                "persona_id": persona_id,
                "request": request,
                "history_count": len(history),
                "evidence_ids": [item.id for item in catalog.items],
            }
        )
        if self.fail_next:
            self.fail_next = False
            raise ReportChatGenerationError("provider returned invalid JSON")
        title = {
            "IM": "Investment Committee Paper",
            "CF": "CFO Funding Note",
            "BD": "Board One-Pager",
            "FA": "Technical Sensitivity Summary",
            "PO": "Variance and Action Report",
        }[persona_id]
        citation = next(
            (item for item in catalog.items if item.source_type == "model"),
            None,
        )
        if citation is None:
            return ReportChatAssistantContent(
                kind="text", text="Please provide report evidence."
            )
        return ReportChatAssistantContent.model_validate(
            {
                "kind": "report",
                "report": {
                    "title": title,
                    "blocks": [
                        {
                            "kind": "paragraph",
                            "text": f"Generated for {persona_id}.",
                            "citation_ids": [citation.id],
                        }
                    ],
                    "citations": [
                        {
                            "id": citation.id,
                            "source_type": citation.source_type,
                            "label": citation.label,
                            "source_ref": citation.source_ref,
                        }
                    ],
                },
            }
        )


@pytest.fixture
def api_context(tmp_path):
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "report-chat-api.db")
    )
    Base.metadata.create_all(engine)
    with session_factory() as setup:
        _storage, _workbook, model, _parameter, _series, _series_value = (
            create_materialized_rule_model(setup)
        )
        output = setup.scalar(
            select(CanonicalOutput).where(
                CanonicalOutput.model_version_id == model.id
            )
        )
        output.business_role = "project_irr"
        setup.commit()
        model_id = model.id

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    fake_generator = FakeReportChatGenerator()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_report_chat_generator] = lambda: fake_generator
    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "model_version_id": model_id,
                "session_factory": session_factory,
                "generator": fake_generator,
            }
    finally:
        app.dependency_overrides.pop(get_report_chat_generator, None)
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _prepare_report_identity(api_context) -> tuple[str, str]:
    client = api_context["client"]
    model_id = api_context["model_version_id"]
    prepared = client.post(
        f"/api/v1/models/{model_id}/calculation/prepare", json={}
    ).json()
    baseline = client.post(
        f"/api/v1/models/{model_id}/calculations",
        json={
            "graph_version_id": prepared["graph_version_id"],
            "overrides": [],
            "idempotency_key": None,
        },
    ).json()
    return prepared["graph_version_id"], baseline["calculation_run_id"]


def _payload(
    client_id: str,
    graph_version_id: str,
    calculation_run_id: str,
    *,
    persona_id: str,
    message: str,
    idempotency_key: str,
) -> dict[str, object]:
    return {
        "client_id": client_id,
        "graph_version_id": graph_version_id,
        "calculation_run_id": calculation_run_id,
        "persona_id": persona_id,
        "message": message,
        "idempotency_key": idempotency_key,
    }


def test_personas_share_one_report_chat_thread(api_context) -> None:
    client = api_context["client"]
    model_id = api_context["model_version_id"]
    client_id = str(uuid.uuid4())
    graph_id, run_id = _prepare_report_identity(api_context)

    first = client.post(
        f"/api/v1/models/{model_id}/report-chat/messages",
        json=_payload(
            client_id,
            graph_id,
            run_id,
            persona_id="IM",
            message="Generate an Investment Committee Paper",
            idempotency_key="message-1",
        ),
    )
    second = client.post(
        f"/api/v1/models/{model_id}/report-chat/messages",
        json=_payload(
            client_id,
            graph_id,
            run_id,
            persona_id="CF",
            message="Generate a CFO Funding Note",
            idempotency_key="message-2",
        ),
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["thread_id"] == second.json()["thread_id"]

    history = client.get(
        f"/api/v1/models/{model_id}/report-chat",
        params={"client_id": client_id},
    )
    assert history.status_code == 200
    assert [item["persona_id"] for item in history.json()["messages"]] == [
        "IM",
        "IM",
        "CF",
        "CF",
    ]
    assert [item["role"] for item in history.json()["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_duplicate_and_failed_generation_retry_reuse_the_same_messages(
    api_context,
) -> None:
    client = api_context["client"]
    model_id = api_context["model_version_id"]
    client_id = str(uuid.uuid4())
    graph_id, run_id = _prepare_report_identity(api_context)
    payload = _payload(
        client_id,
        graph_id,
        run_id,
        persona_id="IM",
        message="Generate an Investment Committee Paper",
        idempotency_key="message-1",
    )

    first = client.post(
        f"/api/v1/models/{model_id}/report-chat/messages", json=payload
    )
    duplicate = client.post(
        f"/api/v1/models/{model_id}/report-chat/messages", json=payload
    )
    assert duplicate.json() == first.json()
    assert len(api_context["generator"].calls) == 1

    api_context["generator"].fail_next = True
    retry_payload = {
        **payload,
        "persona_id": "CF",
        "message": "Generate a CFO Funding Note",
        "idempotency_key": "message-2",
    }
    failed = client.post(
        f"/api/v1/models/{model_id}/report-chat/messages",
        json=retry_payload,
    )
    completed_retry = client.post(
        f"/api/v1/models/{model_id}/report-chat/messages",
        json=retry_payload,
    )

    assert failed.status_code == 502
    assert failed.json()["detail"]["code"] == "REPORT_CHAT_GENERATION_FAILED"
    assert completed_retry.status_code == 200
    history = client.get(
        f"/api/v1/models/{model_id}/report-chat",
        params={"client_id": client_id},
    ).json()["messages"]
    assert [item["role"] for item in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_report_chat_preserves_identity_errors_and_validates_persona(
    api_context,
) -> None:
    client = api_context["client"]
    model_id = api_context["model_version_id"]
    client_id = str(uuid.uuid4())
    _graph_id, run_id = _prepare_report_identity(api_context)

    mismatch = client.post(
        f"/api/v1/models/{model_id}/report-chat/messages",
        json=_payload(
            client_id,
            str(uuid.uuid4()),
            run_id,
            persona_id="IM",
            message="Generate an Investment Committee Paper",
            idempotency_key="bad-identity",
        ),
    )
    invalid_persona = client.post(
        f"/api/v1/models/{model_id}/report-chat/messages",
        json=_payload(
            client_id,
            str(uuid.uuid4()),
            run_id,
            persona_id="XX",
            message="Generate a report",
            idempotency_key="bad-persona",
        ),
    )

    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == (
        "REPORT_CALCULATION_IDENTITY_MISMATCH"
    )
    assert invalid_persona.status_code == 422


def test_owner_key_prefers_authenticated_user_and_separates_clients() -> None:
    user = SimpleNamespace(id="user-1")

    assert report_chat_owner_key(user, "client-1") == "user:user-1"
    assert report_chat_owner_key(None, "client-1") == "client:client-1"
    assert report_chat_owner_key(None, "client-2") == "client:client-2"


def test_docx_endpoint_exports_the_selected_earlier_report(api_context) -> None:
    client = api_context["client"]
    model_id = api_context["model_version_id"]
    client_id = str(uuid.uuid4())
    graph_id, run_id = _prepare_report_identity(api_context)
    first = client.post(
        f"/api/v1/models/{model_id}/report-chat/messages",
        json=_payload(
            client_id,
            graph_id,
            run_id,
            persona_id="IM",
            message="Generate an Investment Committee Paper",
            idempotency_key="message-1",
        ),
    ).json()
    client.post(
        f"/api/v1/models/{model_id}/report-chat/messages",
        json=_payload(
            client_id,
            graph_id,
            run_id,
            persona_id="CF",
            message="Generate a CFO Funding Note",
            idempotency_key="message-2",
        ),
    )

    exported = client.get(
        f"/api/v1/models/{model_id}/report-chat/messages/"
        f"{first['assistant_message']['message_id']}/docx",
        params={"client_id": client_id},
    )

    assert exported.status_code == 200
    assert exported.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "Investment Committee Paper.docx" in exported.headers[
        "content-disposition"
    ]
    assert b"PK" == exported.content[:2]
