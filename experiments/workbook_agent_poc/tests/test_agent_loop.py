"""Trace contract tests for the backend-owned workbook agent loop."""

import json
import os
import sys

import openpyxl

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent_loop import run_loop
from coverage_gate import HardCaps
from workbook_tools import WorkbookToolset


class _Tools:
    def __init__(self, *, large_result: bool):
        self.large_result = large_result

    def get_workbook_metadata(self):
        return {
            "sheets": [{"name": "Sheet1", "state": "visible"}],
            "named_ranges": [],
            "external_links": [],
        }

    def content_sheets(self):
        return {"Sheet1"}

    def iter_formulas(self):
        return iter(())

    def list_sheets(self):
        marker = "x" * 500 if self.large_result else "short"
        return {"sheets": [{"name": "Sheet1", "marker": marker}]}

    def inspect_sheet(self, sheet_name):
        return {"sheet_name": sheet_name, "preview_only": True}

    def submit_extraction_result(self, result):
        return {"received": True}


class _ChunkTools(_Tools):
    def __init__(self):
        super().__init__(large_result=False)
        self.tokens = {None: 0, "next-1": 1, "next-2": 2}
        self.read_calls = 0

    def read_range(
        self,
        sheet_name,
        cell_range,
        continuation_token=None,
        *,
        max_serialized_bytes=11_000,
    ):
        self.read_calls += 1
        index = self.tokens[continuation_token]
        result = {
            "request_id": "request-1",
            "chunk_id": f"chunk-{index}",
            "chunk_index": index,
            "chunk_count": 3,
            "sheet_name": sheet_name,
            "requested_range": cell_range,
            "returned_range": f"A{index + 1}:A{index + 1}",
            "cell_count": 1,
            "range_cell_count": 1,
            "serialized_bytes": 0,
            "workbook_version": "version-1",
            "is_complete": True,
            "has_more": index < 2,
            "next_range": f"A{index + 2}:A{index + 2}" if index < 2 else None,
            "continuation_token": f"next-{index + 1}" if index < 2 else None,
            "cells": [{"cell": f"A{index + 1}"}],
        }
        while True:
            size = len(json.dumps(
                result, default=str, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8"))
            if result["serialized_bytes"] == size:
                return result
            result["serialized_bytes"] = size


class _OneCallDriver:
    def __init__(self):
        self.called = False

    def next_tool_call(self, trace):
        if self.called:
            return None
        self.called = True
        return {"name": "list_sheets", "arguments": {}}

    def observe(self, name, args, result):
        pass


class _ReadRangeDriver:
    observation_payload_budget = 11_000

    def __init__(self):
        self.called = False
        self.observed = []
        self.runtime_statuses = []

    def next_tool_call(self, trace):
        if self.called:
            return None
        self.called = True
        return {
            "name": "read_range",
            "arguments": {"sheet_name": "Sheet1", "cell_range": "A1:A3"},
        }

    def observe_many(self, name, args, results):
        self.observed.extend(results)

    def append_runtime_status(self, status):
        self.runtime_statuses.append(status)


class _SubmitAfterCompleteDriver(_ReadRangeDriver):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.submission_required = False

    def next_tool_call(self, trace):
        plan = [
            {"name": "get_workbook_metadata", "arguments": {}},
            {"name": "inspect_sheet", "arguments": {"sheet_name": "Sheet1"}},
            {"name": "read_range", "arguments": {
                "sheet_name": "Sheet1", "cell_range": "A1:A3",
            }},
            {"name": "submit_extraction_result", "arguments": {"result": {
                "all_assumption_candidates": [], "output_candidates": [],
            }}},
        ]
        call = plan[len(self.calls)] if len(self.calls) < len(plan) else None
        if call:
            self.calls.append(call)
        return call

    def require_submission(self):
        self.submission_required = True

    def observe(self, name, args, result):
        pass


class _SmallLimitReadRangeDriver(_ReadRangeDriver):
    observation_payload_budget = 4_000
    max_observation_bytes = 2_000

    def next_tool_call(self, trace):
        if self.called:
            return None
        self.called = True
        return {
            "name": "read_range",
            "arguments": {"sheet_name": "Sheet1", "cell_range": "A1:D4"},
        }

    def observe_many(self, name, args, results):
        assert all(
            len(json.dumps(result, default=str, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            <= self.max_observation_bytes
            for result in results
        )
        super().observe_many(name, args, results)


class _DuplicateReadDriver(_ReadRangeDriver):
    def __init__(self):
        super().__init__()
        self.call_count = 0

    def next_tool_call(self, trace):
        self.call_count += 1
        if self.call_count > 2:
            return None
        return {
            "name": "read_range",
            "arguments": {"sheet_name": "Sheet1", "cell_range": "A1:A3"},
        }


def test_trace_marks_a_truncated_result_preview():
    run = run_loop(_OneCallDriver(), _Tools(large_result=True))

    assert run["trace"][0]["result_preview"].endswith("…")
    assert run["trace"][0]["result_truncated"] is True


def test_trace_marks_a_complete_result_preview():
    run = run_loop(_OneCallDriver(), _Tools(large_result=False))

    assert not run["trace"][0]["result_preview"].endswith("…")
    assert run["trace"][0]["result_truncated"] is False


def test_runtime_auto_drains_and_observes_every_range_chunk():
    driver = _ReadRangeDriver()

    run = run_loop(driver, _ChunkTools())

    assert [chunk["chunk_id"] for chunk in driver.observed] == [
        "chunk-0",
        "chunk-1",
        "chunk-2",
    ]
    assert [event["chunk_id"] for event in run["trace"]] == [
        "chunk-0",
        "chunk-1",
        "chunk-2",
    ]
    assert run["trace"][0]["auto_pulled"] is False
    assert run["trace"][1]["auto_pulled"] is True

    coverage = run["coverage"]
    assert coverage["logical_model_tool_calls"] == 1
    assert coverage["tool_call_count"] == 1
    assert coverage["internal_chunk_fetches"] == 2
    assert coverage["driver_observations"] == 3
    assert coverage["logical_call_tally"] == [{
        "tool_name": "read_range",
        "sheet_name": "Sheet1",
        "requested_range": "A1:A3",
        "call_count": 1,
    }]
    assert coverage["last_logical_operations"][-1]["tool_name"] == "read_range"


def test_runtime_keeps_continuation_private_and_reports_completion():
    driver = _ReadRangeDriver()

    run = run_loop(driver, _ChunkTools())

    assert all("continuation_token" not in chunk for chunk in driver.observed)
    assert all(chunk["continuation_managed_by_runtime"] for chunk in driver.observed)
    assert driver.runtime_statuses[-1]["request_id"] == "request-1"
    assert driver.runtime_statuses[-1]["observation_complete"] is True
    assert driver.runtime_statuses[-1]["observed_chunk_count"] == 3
    assert run["coverage"]["request_telemetry"][0]["coverage_complete"] is True


def test_one_logical_multichunk_read_preserves_reserved_submit_call():
    driver = _SubmitAfterCompleteDriver()

    run = run_loop(
        driver,
        _ChunkTools(),
        caps=HardCaps(max_tool_calls=4, max_iterations=8, reserved_submit_call=1),
    )

    assert run["submitted"] is True
    assert run["stop_reason"] == "submitted"
    assert [call["name"] for call in driver.calls].count("read_range") == 1
    assert driver.submission_required is True
    assert run["coverage"]["logical_model_tool_calls"] == 4
    assert run["coverage"]["internal_chunk_fetches"] == 2
    assert run["coverage"]["driver_observations"] == 6


def test_internal_chunk_cap_does_not_consume_logical_tool_budget():
    driver = _ReadRangeDriver()

    run = run_loop(
        driver,
        _ChunkTools(),
        caps=HardCaps(max_internal_chunks_per_request=1),
    )

    assert run["coverage"]["logical_model_tool_calls"] == 1
    assert run["coverage"]["internal_chunk_fetches"] == 0
    assert driver.observed[0]["error"]["code"] == "internal_chunk_limit_exceeded"


def test_internal_chunk_run_cap_is_independent_from_logical_budget():
    driver = _ReadRangeDriver()

    run = run_loop(
        driver,
        _ChunkTools(),
        caps=HardCaps(
            max_tool_calls=60,
            max_internal_chunks_per_request=64,
            max_internal_chunks_per_run=1,
        ),
    )

    assert run["coverage"]["logical_model_tool_calls"] == 1
    assert run["coverage"]["internal_chunk_fetches"] == 0
    assert driver.observed[0]["error"]["code"] == "internal_chunk_limit_exceeded"


def test_observed_byte_cap_blocks_delivery_without_marking_chunks_observed():
    driver = _ReadRangeDriver()

    run = run_loop(
        driver,
        _ChunkTools(),
        caps=HardCaps(max_observed_bytes_per_run=1_000),
    )

    assert run["coverage"]["logical_model_tool_calls"] == 1
    assert run["coverage"]["internal_chunk_fetches"] == 2
    assert run["coverage"]["request_telemetry"] == []
    assert driver.observed[0]["error"]["code"] == "observed_bytes_limit_exceeded"


def test_runtime_deduplicates_an_already_observed_requested_range():
    driver = _DuplicateReadDriver()
    tools = _ChunkTools()

    run = run_loop(driver, tools)

    assert tools.read_calls == 3
    assert run["coverage"]["logical_model_tool_calls"] == 2
    assert run["coverage"]["internal_chunk_fetches"] == 2
    assert run["coverage"]["duplicate_range_requests"] == 1
    assert driver.observed[-1]["already_observed"] is True


def test_runtime_retries_read_range_with_smaller_chunks_for_driver_guard(tmp_path):
    path = tmp_path / "retry.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for row in range(1, 5):
        for col in range(1, 5):
            ws.cell(row, col, "x" * 180)
    wb.save(path)
    driver = _SmallLimitReadRangeDriver()

    run = run_loop(driver, WorkbookToolset(file_path=str(path)))

    assert len(driver.observed) > 1
    assert all(chunk["serialized_bytes"] <= 1_488 for chunk in driver.observed)
    assert run["coverage"]["payload_retry_count"] >= 1
