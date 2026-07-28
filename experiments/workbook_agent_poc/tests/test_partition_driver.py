"""Behavior tests for stateless Azure Responses partition calls."""

import json
import logging
import os
import sys

import httpx
import pytest
from openai import OpenAI


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from partition_driver import (
    AzurePartitionDriver,
    PartitionAuthenticationError,
    PartitionContextLimitError,
)
from partition_planner import WorkbookPartition


def _partition(identifier, cell_range):
    fact = {
        "sheet_name": "Model",
        "cell": cell_range.split(":")[0],
        "source_reference": f"Model!{cell_range.split(':')[0]}",
        "raw_value": "secret-cell-sentinel",
        "formula": None,
        "formula_status": "static_value",
        "number_format": "General",
        "data_type": "s",
    }
    return WorkbookPartition(
        workbook_version="c" * 64,
        partition_id=identifier,
        parent_partition_id=None,
        split_depth=0,
        sheet_name="Model",
        primary_range=cell_range,
        primary_facts=(fact,),
        dependency_references=(),
        dependency_facts=(),
        raw_evidence_bytes=100,
        estimated_raw_tokens=50,
        estimated_total_tokens=100,
        request_bytes=200,
    )


def _envelope(partition):
    return {
        "workbook_version": partition.workbook_version,
        "partition_id": partition.partition_id,
        "sheet_name": partition.sheet_name,
        "primary_range": partition.primary_range,
        "manifest": {"sheets": [{"name": "Model"}]},
        "primary_evidence": list(partition.primary_facts),
        "dependency_references": [],
        "dependency_evidence": [],
    }


def _partition_args(partition):
    return {
        "workbook_version": partition.workbook_version,
        "partition_id": partition.partition_id,
        "sheet_name": partition.sheet_name,
        "primary_range": partition.primary_range,
        "result": {
            "all_assumption_candidates": [],
            "output_candidates": [],
        },
    }


def _response(request, *, response_id, tool_name, arguments):
    return httpx.Response(
        200,
        request=request,
        headers={"x-request-id": f"request-{response_id}"},
        json={
            "id": response_id,
            "object": "response",
            "created_at": 0,
            "model": "custom-full-deployment",
            "usage": {"input_tokens": 120, "output_tokens": 20, "total_tokens": 140},
            "output": [{
                "id": f"fc-{response_id}",
                "type": "function_call",
                "call_id": f"call-{response_id}",
                "name": tool_name,
                "arguments": json.dumps(arguments),
            }],
        },
    )


def _driver(monkeypatch, handler, *, max_retries=2):
    monkeypatch.setenv("AZURE_OPENAI_GPT_DEPLOYMENT", "custom-full-deployment")
    monkeypatch.setenv("AZURE_OPENAI_MAX_OUTPUT_TOKENS", "66298")
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "medium")
    client = OpenAI(
        base_url="https://example-resource.services.ai.azure.com/openai/v1/",
        api_key="secret-api-key-sentinel",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    return AzurePartitionDriver(
        client=client,
        max_retries_per_call=max_retries,
        sleeper=lambda _seconds: None,
    )


def test_each_partition_request_starts_without_previous_response_id(monkeypatch):
    partitions = [_partition("partition-1", "A1:B2"), _partition("partition-2", "A3:B4")]
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        partition = partitions[len(bodies) - 1]
        return _response(
            request,
            response_id=f"resp-{len(bodies)}",
            tool_name="submit_partition_result",
            arguments=_partition_args(partition),
        )

    driver = _driver(monkeypatch, handler)
    for partition in partitions:
        assert driver.extract(partition, _envelope(partition))["partition_id"] == (
            partition.partition_id
        )

    assert len(bodies) == 2
    assert all("previous_response_id" not in body for body in bodies)
    assert all(
        body["tool_choice"] == {
            "type": "function",
            "name": "submit_partition_result",
        }
        for body in bodies
    )
    assert all(body["parallel_tool_calls"] is False for body in bodies)


def test_driver_consumes_deployment_output_and_reasoning_environment(monkeypatch):
    partition = _partition("partition-config", "A1:B2")
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return _response(
            request,
            response_id="resp-config",
            tool_name="submit_partition_result",
            arguments=_partition_args(partition),
        )

    driver = _driver(monkeypatch, handler)
    driver.extract(partition, _envelope(partition))

    assert bodies[0]["model"] == "custom-full-deployment"
    assert bodies[0]["max_output_tokens"] == 66298
    assert bodies[0]["reasoning"] == {"effort": "medium"}
    assert driver.usage_prompt == 120
    assert driver.usage_completion == 20
    assert driver.request_ids == ["request-resp-config"]


def test_invalid_output_gets_one_same_partition_correction_only(monkeypatch):
    first = _partition("partition-first", "A1:B2")
    second = _partition("partition-second", "A3:B4")
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "resp-invalid",
                    "object": "response",
                    "created_at": 0,
                    "model": "custom-full-deployment",
                    "output": [],
                },
            )
        partition = first if len(bodies) == 2 else second
        return _response(
            request,
            response_id=f"resp-{len(bodies)}",
            tool_name="submit_partition_result",
            arguments=_partition_args(partition),
        )

    driver = _driver(monkeypatch, handler)
    driver.extract(first, _envelope(first))
    driver.extract(second, _envelope(second))

    assert bodies[1]["previous_response_id"] == "resp-invalid"
    assert "previous_response_id" not in bodies[2]


@pytest.mark.parametrize("status_code", [401, 403])
def test_authentication_errors_are_not_retried(monkeypatch, status_code):
    partition = _partition("partition-auth", "A1:B2")

    def handler(request):
        return httpx.Response(
            status_code,
            request=request,
            json={"error": {"code": "unauthorized", "message": "denied"}},
        )

    driver = _driver(monkeypatch, handler)

    with pytest.raises(PartitionAuthenticationError):
        driver.extract(partition, _envelope(partition))

    assert driver.call_count == 1


def test_context_length_error_is_typed_and_not_retried(monkeypatch):
    partition = _partition("partition-context", "A1:B2")

    def handler(request):
        return httpx.Response(
            400,
            request=request,
            json={
                "error": {
                    "code": "context_length_exceeded",
                    "message": "input too large",
                }
            },
        )

    driver = _driver(monkeypatch, handler)

    with pytest.raises(PartitionContextLimitError):
        driver.extract(partition, _envelope(partition))

    assert driver.call_count == 1


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_transient_errors_use_bounded_retry(monkeypatch, status_code):
    partition = _partition(f"partition-{status_code}", "A1:B2")
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                status_code,
                request=request,
                json={"error": {"code": "transient", "message": "retry"}},
            )
        return _response(
            request,
            response_id="resp-retry",
            tool_name="submit_partition_result",
            arguments=_partition_args(partition),
        )

    driver = _driver(monkeypatch, handler)

    assert driver.extract(partition, _envelope(partition))["partition_id"] == (
        partition.partition_id
    )
    assert driver.call_count == 2


def test_conflict_resolution_uses_independent_bounded_tool(monkeypatch):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        return _response(
            request,
            response_id="resp-conflict",
            tool_name="submit_partition_reconciliation",
            arguments={
                "conflict_id": "conflict-1",
                "resolution": "review_required",
                "selected_bucket": None,
                "reasoning_summary": "Workbook evidence is ambiguous.",
            },
        )

    driver = _driver(monkeypatch, handler)

    assert driver.resolve_conflict({
        "conflict_id": "conflict-1",
        "allowed_buckets": ["output_candidates", "review_candidates"],
        "validated_facts": [{"source_reference": "Model!A1"}],
    }) is None
    assert "previous_response_id" not in bodies[0]
    assert [tool["name"] for tool in bodies[0]["tools"]] == [
        "submit_partition_reconciliation"
    ]


def test_logs_never_include_raw_cells_or_api_keys(monkeypatch, caplog):
    partition = _partition("partition-log", "A1:B2")

    def handler(request):
        return _response(
            request,
            response_id="resp-log",
            tool_name="submit_partition_result",
            arguments=_partition_args(partition),
        )

    caplog.set_level(logging.INFO)
    driver = _driver(monkeypatch, handler)
    driver.extract(partition, _envelope(partition))

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "secret-cell-sentinel" not in rendered
    assert "secret-api-key-sentinel" not in rendered
