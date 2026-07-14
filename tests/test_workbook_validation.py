"""Contract tests for the experimental workbook-agent API adapter."""

from pathlib import Path

import pytest

from apps.api.app.workbook_validation import (
    InvalidWorkbookError,
    run_workbook_validation,
)
import apps.api.app.workbook_validation as workbook_validation


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "experiments/workbook_agent_poc/fixtures/no_assumptions_sheet.xlsx"
FINANCIAL_MODEL = ROOT / "Financial_Model_Data.xlsx"


class PlannedWorkbookDriver:
    """Deterministic driver that exercises the real loop, tools, gate, and validator."""

    _deployment = "deterministic-test-driver"
    usage_prompt = 101
    usage_completion = 23

    def __init__(self):
        sheets = ["Overview", "Operations", "Funding", "Calc", "Summary"]
        self.calls = [
            {"name": "get_workbook_metadata", "arguments": {}},
            {"name": "list_sheets", "arguments": {}},
        ]
        for sheet in sheets:
            self.calls.extend([
                {"name": "inspect_sheet", "arguments": {"sheet_name": sheet}},
                {"name": "read_range", "arguments": {"sheet_name": sheet, "cell_range": "A1:H20"}},
            ])
        self.calls.append({
            "name": "submit_extraction_result",
            "arguments": {
                "result": {
                    "all_assumption_candidates": [{
                        "candidate_id": "Funding!C3",
                        "original_label": "Base capex",
                        "submitted_role": "hardcoded_input",
                        "raw_value": 400,
                        "source_references": [{"sheet_name": "Funding", "cell": "C3"}],
                    }],
                    "output_candidates": [],
                }
            },
        })
        self.index = 0

    def next_tool_call(self, trace):
        if self.index >= len(self.calls):
            return None
        call = self.calls[self.index]
        self.index += 1
        return call

    def observe(self, name, args, result):
        pass


class IncompleteDriver:
    _deployment = "deterministic-incomplete-driver"
    usage_prompt = 0
    usage_completion = 0

    def next_tool_call(self, trace):
        return None

    def observe(self, name, args, result):
        pass


class FinancialModelCoverageDriver:
    _deployment = "deterministic-financial-model-coverage-driver"
    usage_prompt = 0
    usage_completion = 0

    def __init__(self):
        required_ranges = {
            "Cover": "A1:L43",
            "Assumptions": "A1:G74",
            "Revenue": "A1:W16",
            "Capex": "A1:W20",
            "PnL": "A1:W15",
            "Debt_Schedule": "A1:W18",
            "CashFlows": "A1:W18",
            "Returns": "A1:I28",
            "Sensitivity": "A1:K25",
            "Checks": "A1:G16",
            "Dashboard": "A1:M11",
        }
        self.calls = [
            {"name": "get_workbook_metadata", "arguments": {}},
            {"name": "list_sheets", "arguments": {}},
        ]
        for sheet, cell_range in required_ranges.items():
            self.calls.extend([
                {"name": "inspect_sheet", "arguments": {"sheet_name": sheet}},
                {"name": "read_range", "arguments": {
                    "sheet_name": sheet,
                    "cell_range": cell_range,
                }},
            ])
        self.calls.append({
            "name": "submit_extraction_result",
            "arguments": {"result": {
                "metadata": [{
                    "candidate_id": "Cover!B3",
                    "original_label": "Financial Model",
                    "submitted_role": "metadata",
                    "raw_value": (
                        "Financial Model — InvestIQ Production Grade | Version 1.0 | "
                        "April 2025"
                    ),
                    "source_references": [{"sheet_name": "Cover", "cell": "B3"}],
                }],
                "all_assumption_candidates": [],
                "output_candidates": [],
            }},
        })
        self.index = 0

    def next_tool_call(self, trace):
        call = self.calls[self.index]
        self.index += 1
        return call

    def observe(self, name, args, result):
        pass


def test_adapter_runs_real_tools_gate_and_validator():
    result = run_workbook_validation(
        FIXTURE.read_bytes(),
        FIXTURE.name,
        driver_factory=PlannedWorkbookDriver,
    )

    assert result["endpoint_mode"] == "experimental_workbook_agent_validation"
    assert result["driver_meta"] == {
        "api": "responses",
        "deployment": "deterministic-test-driver",
        "prompt_tokens": 101,
        "completion_tokens": 23,
    }
    assert result["submitted"] is True
    assert result["stop_reason"] == "submitted"
    assert result["coverage"]["total_sheets"] == 5
    assert result["coverage"]["inspected_sheets"] == 5
    assert result["final_extraction"]["all_assumption_candidates"]
    assert result["validation_summary"]["candidate_count"] == 1
    assert result["validation_summary"]["validated"] == 1
    assert len(result["validation_results"]) == 1
    assert isinstance(result["warnings"], list)
    assert result["errors"] == []
    assert result["trace"]
    assert result["trace_truncated"] == any(
        event["result_truncated"] for event in result["trace"]
    )


def test_incomplete_run_returns_evidence_and_structured_error():
    result = run_workbook_validation(
        FIXTURE.read_bytes(),
        FIXTURE.name,
        driver_factory=IncompleteDriver,
    )

    assert result["submitted"] is False
    assert result["stop_reason"] == "model_returned_no_tool_call"
    assert result["coverage"]["total_sheets"] == 5
    assert result["validation_results"] == []
    assert result["errors"][0]["code"] == "AGENT_INCOMPLETE"


def test_financial_model_data_completes_geometric_coverage_without_rejection():
    result = run_workbook_validation(
        FINANCIAL_MODEL.read_bytes(),
        FINANCIAL_MODEL.name,
        driver_factory=FinancialModelCoverageDriver,
    )

    coverage = result["coverage"]
    assert coverage["inspected_sheets"] == coverage["total_sheets"] == 11
    assert coverage["fully_observed_sheets"] == coverage["content_sheets"]
    assert all(
        not telemetry["missing_ranges"]
        for telemetry in coverage["observation_telemetry"].values()
    )
    assert coverage["coverage_rejections"] == 0
    assert coverage["submit_attempts"] == 1
    assert result["submitted"] is True
    assert result["stop_reason"] == "submitted"
    assert result["final_extraction"]["metadata"]
    assert result["errors"] == []
    assert all(
        "range_too_large" not in event["result_preview"]
        for event in result["trace"]
    )


def test_invalid_xlsx_raises_typed_error():
    with pytest.raises(InvalidWorkbookError):
        run_workbook_validation(
            b"not an OOXML workbook",
            "broken.xlsx",
            driver_factory=PlannedWorkbookDriver,
        )


@pytest.mark.parametrize("valid_upload", [True, False])
def test_temporary_workbook_is_removed_after_success_and_failure(monkeypatch, valid_upload):
    real_temporary_directory = workbook_validation.tempfile.TemporaryDirectory
    created_paths: list[Path] = []

    class TrackingTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self.delegate = real_temporary_directory(*args, **kwargs)

        def __enter__(self):
            path = Path(self.delegate.__enter__())
            created_paths.append(path)
            return str(path)

        def __exit__(self, *args):
            return self.delegate.__exit__(*args)

    monkeypatch.setattr(
        workbook_validation.tempfile,
        "TemporaryDirectory",
        TrackingTemporaryDirectory,
    )

    if valid_upload:
        run_workbook_validation(
            FIXTURE.read_bytes(),
            FIXTURE.name,
            driver_factory=IncompleteDriver,
        )
    else:
        with pytest.raises(InvalidWorkbookError):
            run_workbook_validation(
                b"not an OOXML workbook",
                "broken.xlsx",
                driver_factory=PlannedWorkbookDriver,
            )

    assert created_paths
    assert all(not path.exists() for path in created_paths)
