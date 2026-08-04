"""Regression coverage for the Azure OpenAI v1 Responses integration."""

import importlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from openai import OpenAI


def test_chat_response_uses_v1_responses_url_and_response_output(monkeypatch):
    """The application must target one v1 /responses endpoint without api-version."""
    monkeypatch.setenv(
        "AZURE_OPENAI_ENDPOINT",
        "https://example-resource.services.ai.azure.com/openai/v1/",
    )
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-5.4-mini")

    from apps.api.app import llm_service

    llm_service = importlib.reload(llm_service)
    captured_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "model": "gpt-5.4-mini",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "CONNECTION_OK",
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    llm_service._client = OpenAI(
        base_url="https://example-resource.services.ai.azure.com/openai/v1/",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = llm_service.chat_response(
        persona={"name": "Investor"},
        model_context="Model context",
        query="Confirm the connection.",
    )

    assert result == "CONNECTION_OK"
    assert captured_request["url"] == (
        "https://example-resource.services.ai.azure.com/openai/v1/responses"
    )
    body = captured_request["body"]
    assert body["model"] == "gpt-5.4-mini"
    assert body["input"][0]["role"] == "developer"
    assert "## Financial Model Context\nModel context" in body["input"][0]["content"]
    assert body["input"][-1] == {"role": "user", "content": "Confirm the connection."}


def test_llm_service_defaults_to_the_deployed_gpt_5_4_mini(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_GPT_DEPLOYMENT", raising=False)

    from apps.api.app import llm_service

    llm_service = importlib.reload(llm_service)

    assert llm_service._DEPLOYMENT == "gpt-5.4-mini"


def test_report_chat_uses_v1_responses_with_only_available_evidence(
    monkeypatch,
):
    monkeypatch.setenv(
        "AZURE_OPENAI_ENDPOINT",
        "https://example-resource.services.ai.azure.com/openai/v1/",
    )
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_GPT_DEPLOYMENT", "report-deployment")

    from apps.api.app import llm_service
    from apps.api.app.report_chat_evidence import ReportChatEvidenceBuilder
    from apps.api.app.report_chat_generator import ReportChatGenerator

    llm_service = importlib.reload(llm_service)
    captured_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["body"] = json.loads(request.content)
        report_json = json.dumps(
            {
                "kind": "report",
                "report": {
                    "title": "CFO Funding Note",
                    "blocks": [
                        {
                            "kind": "paragraph",
                            "text": "Minimum DSCR is 1.3x and the user expects a delay.",
                            "citation_ids": ["M1", "U1"],
                        }
                    ],
                },
            }
        )
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp_report",
                "object": "response",
                "created_at": 0,
                "model": "report-deployment",
                "output": [
                    {
                        "id": "msg_report",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": report_json,
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    client = OpenAI(
        base_url="https://example-resource.services.ai.azure.com/openai/v1/",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    user_message = SimpleNamespace(
        id="11111111-1111-4111-8111-111111111111",
        role="user",
        content_json={"kind": "text", "text": "Delay is two months"},
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    catalog = ReportChatEvidenceBuilder().build(
        snapshot={
            "calculation": {
                "overview": {
                    "kpis": [
                        {
                            "label": "Minimum DSCR",
                            "value": "1.3",
                            "availability_status": "available",
                            "source_ids": [
                                "22222222-2222-4222-8222-222222222222"
                            ],
                        },
                        {
                            "label": "Unavailable NPV",
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
        messages=[user_message],
    )

    content = ReportChatGenerator(client).generate(
        "CF",
        "Generate a CFO Funding Note",
        [user_message],
        catalog,
    )

    assert content.report.title == "CFO Funding Note"
    assert [citation.id for citation in content.report.citations] == ["M1", "U1"]
    assert captured_request["url"] == (
        "https://example-resource.services.ai.azure.com/openai/v1/responses"
    )
    body = captured_request["body"]
    assert body["model"] == "report-deployment"
    assert "CFO Funding Note" in body["input"][0]["content"]
    assert '"id":"M1"' in body["input"][0]["content"]
    assert '"id":"U1"' in body["input"][0]["content"]
    assert "Unavailable NPV" not in body["input"][0]["content"]
