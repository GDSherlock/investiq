"""Regression coverage for the experimental Azure v1 Responses driver."""

import json
import os
import sys

import httpx
from openai import OpenAI


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent_loop import AzureDriver, run_loop, serialize_observation_payload
from coverage_gate import HardCaps
from workbook_tools import WorkbookToolset


def test_observation_payload_is_complete_json_and_never_string_truncated():
    result = {"cells": [{"value": "x" * 13_000}]}

    payload = serialize_observation_payload(result, max_bytes=20_000)

    assert len(payload) > 12_000
    assert json.loads(payload) == result
    assert payload.endswith("}")


def test_observation_payload_too_large_is_a_complete_structured_error():
    result = {"cells": [{"value": "x" * 13_000}]}

    payload = serialize_observation_payload(result, max_bytes=12_000)
    parsed = json.loads(payload)

    assert parsed["error"]["code"] == "payload_too_large"
    assert parsed["error"]["serialized_bytes"] > 12_000
    assert payload.endswith("}")


def test_azure_driver_batches_runtime_chunks_as_separate_complete_json_inputs():
    driver = object.__new__(AzureDriver)
    driver._pending_id = "call-range"
    results = [
        {"chunk_id": "chunk-1", "has_more": True},
        {"chunk_id": "chunk-2", "has_more": False},
    ]

    driver.observe_many("read_range", {}, results)

    assert driver._next_input[0]["type"] == "function_call_output"
    assert json.loads(driver._next_input[0]["output"]) == results[0]
    assert driver._next_input[1]["role"] == "user"
    assert json.loads(driver._next_input[1]["content"]) == results[1]

    driver.append_runtime_status({"observation_complete": True})
    assert driver._next_input[2]["role"] == "user"
    assert json.loads(driver._next_input[2]["content"])["observation_complete"] is True


def test_azure_driver_uses_v1_responses_for_function_calls(monkeypatch):
    monkeypatch.setenv(
        "AZURE_OPENAI_ENDPOINT",
        "https://example-resource.services.ai.azure.com/openai/v1/",
    )
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-5.4-mini")
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
                        "id": "fc_test",
                        "type": "function_call",
                        "call_id": "call_test",
                        "name": "list_sheets",
                        "arguments": "{}",
                    }
                ],
            },
        )

    driver = AzureDriver()
    driver._client = OpenAI(
        base_url="https://example-resource.services.ai.azure.com/openai/v1/",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert driver.next_tool_call([]) == {"name": "list_sheets", "arguments": {}}
    assert captured_request["url"] == (
        "https://example-resource.services.ai.azure.com/openai/v1/responses"
    )
    assert captured_request["body"]["model"] == "gpt-5.4-mini"
    assert captured_request["body"]["tools"][0] == {
        "type": "function",
        "name": "list_sheets",
        "description": "List every worksheet with state (incl. hidden/veryHidden) and dimensions.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }


def test_azure_driver_can_force_the_reserved_submit_call(monkeypatch):
    monkeypatch.setenv(
        "AZURE_OPENAI_ENDPOINT",
        "https://example-resource.services.ai.azure.com/openai/v1/",
    )
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp_submit",
                "object": "response",
                "created_at": 0,
                "model": "gpt-5.4-mini",
                "output": [{
                    "id": "fc_submit",
                    "type": "function_call",
                    "call_id": "call_submit",
                    "name": "submit_extraction_result",
                    "arguments": json.dumps({"result": {
                        "all_assumption_candidates": [], "output_candidates": [],
                    }}),
                }],
            },
        )

    driver = AzureDriver()
    driver._client = OpenAI(
        base_url="https://example-resource.services.ai.azure.com/openai/v1/",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    driver.require_submission()

    call = driver.next_tool_call([])

    assert call["name"] == "submit_extraction_result"
    assert captured["tool_choice"] == {
        "type": "function", "name": "submit_extraction_result",
    }


def test_responses_protocol_one_logical_read_observes_all_chunks_then_submits(
    monkeypatch, tmp_path
):
    path = tmp_path / "protocol.xlsx"
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for row in range(1, 4):
        ws.cell(row, 1, f"row-{row}-" + "x" * 500)
    wb.save(path)

    monkeypatch.setenv(
        "AZURE_OPENAI_ENDPOINT",
        "https://example-resource.services.ai.azure.com/openai/v1/",
    )
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    calls = []
    names = [
        ("get_workbook_metadata", {}),
        ("inspect_sheet", {"sheet_name": "Sheet1"}),
        ("read_range", {"sheet_name": "Sheet1", "cell_range": "A1:A3"}),
        ("submit_extraction_result", {"result": {
            "all_assumption_candidates": [], "output_candidates": [],
        }}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        index = len(calls) - 1
        name, arguments = names[index]
        return httpx.Response(
            200,
            request=request,
            json={
                "id": f"resp_{index}",
                "object": "response",
                "created_at": 0,
                "model": "gpt-5.4-mini",
                "output": [{
                    "id": f"fc_{index}",
                    "type": "function_call",
                    "call_id": f"call_{index}",
                    "name": name,
                    "arguments": json.dumps(arguments),
                }],
            },
        )

    driver = AzureDriver()
    driver.observation_payload_budget = 1_500
    driver._client = OpenAI(
        base_url="https://example-resource.services.ai.azure.com/openai/v1/",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    run = run_loop(
        driver,
        WorkbookToolset(file_path=str(path)),
        caps=HardCaps(max_tool_calls=4, max_iterations=6),
    )

    assert run["submitted"] is True
    assert run["stop_reason"] == "submitted"
    assert run["coverage"]["logical_model_tool_calls"] == 4
    assert run["coverage"]["internal_chunk_fetches"] >= 1
    assert [name for name, _ in names].count("read_range") == 1

    post_read_input = calls[3]["input"]
    function_outputs = [
        item for item in post_read_input if item.get("type") == "function_call_output"
    ]
    assert len(function_outputs) == 1
    chunk_payloads = [json.loads(function_outputs[0]["output"])] + [
        json.loads(item["content"])
        for item in post_read_input[1:]
        if "chunk_id" in item.get("content", "")
    ]
    assert len(chunk_payloads) >= 2
    assert all("continuation_token" not in chunk for chunk in chunk_payloads)
    status = json.loads(post_read_input[-1]["content"])
    assert status["observed_chunk_count"] == len(chunk_payloads)
    assert status["observation_complete"] is True
    assert status["submission_allowed"] is True
    assert calls[3]["tool_choice"] == {
        "type": "function", "name": "submit_extraction_result",
    }
