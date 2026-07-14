"""Regression coverage for the Azure OpenAI v1 Responses integration."""

import importlib
import json

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
