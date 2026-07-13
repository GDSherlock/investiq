"""Trace contract tests for the backend-owned workbook agent loop."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent_loop import run_loop


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


def test_trace_marks_a_truncated_result_preview():
    run = run_loop(_OneCallDriver(), _Tools(large_result=True))

    assert run["trace"][0]["result_preview"].endswith("…")
    assert run["trace"][0]["result_truncated"] is True


def test_trace_marks_a_complete_result_preview():
    run = run_loop(_OneCallDriver(), _Tools(large_result=False))

    assert not run["trace"][0]["result_preview"].endswith("…")
    assert run["trace"][0]["result_truncated"] is False
