"""Contract tests for the experimental workbook-agent API adapter."""

import json
from pathlib import Path

import pytest

from apps.api.app.workbook_validation import (
    AzureResponsesError,
    InvalidWorkbookError,
    run_workbook_validation,
)
import apps.api.app.workbook_validation as workbook_validation
from partition_driver import PartitionAuthenticationError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "experiments/workbook_agent_poc/fixtures/no_assumptions_sheet.xlsx"
FINANCIAL_MODEL = ROOT / "Financial_Model_Data.xlsx"
VALIDATION_RESPONSE_FIELDS = {
    "endpoint_mode",
    "filename",
    "runtime_seconds",
    "driver_meta",
    "submitted",
    "stop_reason",
    "coverage",
    "final_extraction",
    "validation_summary",
    "time_series_summary",
    "validation_results",
    "warnings",
    "errors",
    "trace",
    "trace_truncated",
}


def series_descriptor(series_id, label, sheet, row, category, *, unit=None):
    return {
        "series_id": series_id,
        "label": label,
        "semantic_role": "financial_series",
        "category": category,
        "unit": unit or ("x" if label == "DSCR" else "USD M"),
        "frequency": "annual",
        "period_range": f"{sheet}!C3:V3",
        "value_range": f"{sheet}!C{row}:V{row}",
        "label_reference": f"{sheet}!B{row}",
        "reasoning_summary": f"Complete evidenced annual {label} series.",
        "llm_confidence": 0.99,
    }


def legacy_complete_series(descriptor):
    legacy = dict(descriptor)
    period_range = legacy.pop("period_range")
    value_range = legacy.pop("value_range")
    legacy["period_axis"] = {
        "source_range": period_range,
        "periods": ["WRONG"] * 20,
    }
    legacy["value_axis"] = {
        "source_range": value_range,
        "values": [999] * 20,
    }
    legacy["calculation_type"] = "formula"
    legacy["formula_pattern"] = {"formula_cell_count": 999}
    return legacy


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


class PartitionedEmptyDriver:
    _deployment = "deterministic-partition-driver"
    usage_prompt = 17
    usage_completion = 5
    call_count = 0
    max_calls_per_operation = 1
    request_ids = []

    def extract(self, partition, _envelope):
        self.call_count += 1
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

    def resolve_conflict(self, _conflict):
        return None


class PartitionedAuthenticationFailureDriver(PartitionedEmptyDriver):
    def extract(self, partition, _envelope):
        self.call_count += 1
        raise PartitionAuthenticationError(
            "secret-value-must-not-escape"
        )


class PartitionedSourceLessDriver(PartitionedEmptyDriver):
    def __init__(self):
        self.call_count = 0
        self.emitted = False

    def extract(self, partition, envelope):
        result = super().extract(partition, envelope)
        if not self.emitted:
            self.emitted = True
            result["result"]["all_assumption_candidates"].append({
                "candidate_id": "source-less",
                "original_label": "Unbound candidate",
                "submitted_role": "hardcoded_input",
                "raw_value": 123,
                "source_references": [],
            })
        return result


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
                "financial_series": [
                    series_descriptor("revenue_total", "TOTAL REVENUE", "Revenue", 14, "revenue"),
                    series_descriptor("ebitda", "EBITDA", "PnL", 7, "profit_and_loss"),
                    series_descriptor("net_income", "NET INCOME", "PnL", 14, "profit_and_loss"),
                    series_descriptor(
                        "unlevered_fcf", "UNLEVERED FREE CASH FLOW", "CashFlows", 9, "cash_flow"
                    ),
                    series_descriptor("pv_of_fcf", "PV of FCF", "CashFlows", 18, "cash_flow"),
                    series_descriptor(
                        "total_debt_service", "Total debt service", "Debt_Schedule", 12, "debt"
                    ),
                    series_descriptor("dscr", "DSCR", "Debt_Schedule", 15, "debt"),
                    series_descriptor(
                        "cumulative_capex", "Cumulative capex", "Capex", 20, "capex"
                    ),
                ],
            }},
        })
        self.index = 0

    def next_tool_call(self, trace):
        call = self.calls[self.index]
        self.index += 1
        return call

    def observe(self, name, args, result):
        pass


class LegacyFinancialModelCoverageDriver(FinancialModelCoverageDriver):
    """Latest successful response shape: complete series in the legacy candidate bucket."""

    _deployment = "deterministic-legacy-financial-model-driver"

    def __init__(self):
        super().__init__()
        result = self.calls[-1]["arguments"]["result"]
        descriptors = [
            *result.pop("financial_series"),
            series_descriptor(
                "utilisation", "Throughput utilisation", "Revenue", 5, "operations", unit="%"
            ),
            series_descriptor(
                "throughput", "Throughput volume (MMBtu M)", "Revenue", 6, "operations",
                unit="MMBtu M",
            ),
            series_descriptor(
                "maintenance_capex", "Maintenance capex", "Capex", 17, "capex"
            ),
        ]
        result["financial_series_candidates"] = [
            legacy_complete_series(descriptor) for descriptor in descriptors
        ]


def test_adapter_runs_real_tools_gate_and_validator():
    result = run_workbook_validation(
        FIXTURE.read_bytes(),
        FIXTURE.name,
        driver_factory=PlannedWorkbookDriver,
        partitioned=False,
    )

    assert result["endpoint_mode"] == "experimental_workbook_agent_validation"
    assert {
        key: result["driver_meta"][key]
        for key in (
            "api",
            "deployment",
            "prompt_tokens",
            "completion_tokens",
        )
    } == {
        "api": "responses",
        "deployment": "deterministic-test-driver",
        "prompt_tokens": 101,
        "completion_tokens": 23,
    }
    assert result["driver_meta"]["partitioned"] is False
    assert result["submitted"] is True
    assert result["stop_reason"] == "submitted"
    assert result["coverage"]["total_sheets"] == 5
    assert result["coverage"]["inspected_sheets"] == 5
    assert result["final_extraction"]["all_assumption_candidates"]
    assert result["validation_summary"]["candidate_count"] == 1
    assert result["validation_summary"]["validated"] == 1
    assert result["time_series_summary"] == {
        "submitted_descriptors": 0,
        "legacy_series_detected": 0,
        "submitted_series": 0,
        "materialized_series": 0,
        "validated_series": 0,
        "validated_with_warning": 0,
        "rejected_series": 0,
        "representative_cell_only": 0,
        "period_value_mismatches": 0,
        "duplicate_series": 0,
        "backend_range_reads": 0,
        "reclassified_series": 0,
    }
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
        partitioned=False,
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
        partitioned=False,
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
    assert coverage["logical_model_tool_calls"] == 25
    assert result["driver_meta"]["prompt_tokens"] == 0
    assert result["driver_meta"]["completion_tokens"] == 0
    assert result["submitted"] is True
    assert result["stop_reason"] == "submitted"
    assert result["final_extraction"]["metadata"]
    assert len(result["final_extraction"]["financial_series"]) == 8
    assert result["time_series_summary"] == {
        "submitted_descriptors": 8,
        "legacy_series_detected": 0,
        "submitted_series": 8,
        "materialized_series": 8,
        "validated_series": 8,
        "validated_with_warning": 4,
        "rejected_series": 0,
        "representative_cell_only": 0,
        "period_value_mismatches": 0,
        "duplicate_series": 0,
        "backend_range_reads": 13,
        "reclassified_series": 0,
    }
    canonical_results = [
        item for item in result["validation_results"]
        if item.get("result_type") == "financial_series"
    ]
    assert {item["label"] for item in canonical_results} >= {
        "TOTAL REVENUE", "EBITDA", "NET INCOME", "UNLEVERED FREE CASH FLOW",
        "Total debt service", "DSCR", "Cumulative capex",
    }
    assert all(item["number_of_periods"] == 20 for item in canonical_results)
    assert all(len(item["validated_periods"]) == len(item["validated_values"]) for item in canonical_results)
    assert all(item["source_ranges"]["period_axis"] for item in canonical_results)
    assert all(item["source_ranges"]["value_axis"] for item in canonical_results)
    formula_results = {
        item["label"]: item for item in canonical_results
        if item["label"] in {"TOTAL REVENUE", "PV of FCF", "Total debt service", "Cumulative capex"}
    }
    assert all(item["semantic_role"] == "financial_series" for item in formula_results.values())
    assert all(item["calculation_type"] == "formula" for item in formula_results.values())
    assert result["final_extraction"]["financial_series_descriptors"]
    assert all(
        "periods" not in descriptor and "values" not in descriptor
        for descriptor in result["final_extraction"]["financial_series_descriptors"]
    )
    assert result["errors"] == []
    assert all(
        "range_too_large" not in event["result_preview"]
        for event in result["trace"]
    )


def test_legacy_complete_series_are_materialized_and_summary_is_nonzero():
    result = run_workbook_validation(
        FINANCIAL_MODEL.read_bytes(),
        FINANCIAL_MODEL.name,
        driver_factory=LegacyFinancialModelCoverageDriver,
        partitioned=False,
    )

    summary = result["time_series_summary"]
    assert summary["submitted_descriptors"] == 0
    assert summary["legacy_series_detected"] == 11
    assert summary["materialized_series"] == 11
    assert summary["validated_series"] == 11
    assert summary["rejected_series"] == 0
    assert result["validation_summary"]["rejected"] == 0
    assert result["validation_summary"]["validated_with_warning"] == 11
    assert len(result["final_extraction"]["financial_series"]) == 11
    assert len(result["final_extraction"]["financial_series_candidates"]) == 11
    assert all(
        "LEGACY_VALUE_ARRAY_DISAGREEMENT" in series["warnings"]
        for series in result["final_extraction"]["financial_series"]
    )


def test_descriptor_submission_payload_is_smaller_than_legacy_full_arrays():
    driver = FinancialModelCoverageDriver()
    descriptors = driver.calls[-1]["arguments"]["result"]["financial_series"]
    legacy = [legacy_complete_series(descriptor) for descriptor in descriptors]

    compact_bytes = len(json.dumps(descriptors, separators=(",", ":")).encode())
    legacy_bytes = len(json.dumps(legacy, separators=(",", ":")).encode())

    assert compact_bytes < legacy_bytes


def test_invalid_xlsx_raises_typed_error():
    with pytest.raises(InvalidWorkbookError):
        run_workbook_validation(
            b"not an OOXML workbook",
            "broken.xlsx",
            driver_factory=PlannedWorkbookDriver,
            partitioned=False,
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
            partitioned=False,
        )
    else:
        with pytest.raises(InvalidWorkbookError):
            run_workbook_validation(
                b"not an OOXML workbook",
                "broken.xlsx",
                driver_factory=PlannedWorkbookDriver,
                partitioned=False,
            )

    assert created_paths
    assert all(not path.exists() for path in created_paths)


def test_adapter_uses_partitioned_pipeline_by_default(monkeypatch):
    monkeypatch.delenv(
        "WORKBOOK_AGENT_PARTITIONED_EXTRACTION_ENABLED",
        raising=False,
    )

    result = run_workbook_validation(
        FIXTURE.read_bytes(),
        FIXTURE.name,
        partition_driver_factory=PartitionedEmptyDriver,
    )

    assert set(result) == VALIDATION_RESPONSE_FIELDS
    assert result["submitted"] is True
    assert result["stop_reason"] == "submitted"
    assert result["driver_meta"]["partitioned"] is True
    assert result["coverage"]["planned_partition_count"] > 0
    assert (
        result["coverage"]["completed_partition_count"]
        == result["coverage"]["planned_partition_count"]
    )
    assert result["coverage"]["submission_allowed"] is True


def test_partition_source_rejection_does_not_fail_workbook():
    result = run_workbook_validation(
        FIXTURE.read_bytes(),
        FIXTURE.name,
        partition_driver_factory=PartitionedSourceLessDriver,
    )

    assert result["submitted"] is True
    assert result["stop_reason"] == "submitted"
    assert result["errors"] == []
    assert result["validation_summary"]["rejected"] == 1
    assert any(
        item["candidate_id"] == "source-less"
        and item["validation_status"] == "rejected"
        and item["invalid_source"] is True
        for item in result["validation_results"]
    )


def test_false_environment_switch_uses_current_agent_loop(monkeypatch):
    monkeypatch.setenv(
        "WORKBOOK_AGENT_PARTITIONED_EXTRACTION_ENABLED",
        "false",
    )

    result = run_workbook_validation(
        FIXTURE.read_bytes(),
        FIXTURE.name,
        driver_factory=IncompleteDriver,
    )

    assert result["submitted"] is False
    assert result["stop_reason"] == "model_returned_no_tool_call"
    assert result["driver_meta"]["partitioned"] is False


def test_partition_azure_failure_maps_to_existing_sanitized_error():
    with pytest.raises(AzureResponsesError) as exc:
        run_workbook_validation(
            FIXTURE.read_bytes(),
            FIXTURE.name,
            partition_driver_factory=PartitionedAuthenticationFailureDriver,
        )

    assert str(exc.value) == "Azure Responses API execution failed."
    assert "secret-value" not in str(exc.value)
