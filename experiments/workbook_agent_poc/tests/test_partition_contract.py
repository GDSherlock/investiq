"""Nested contract checks for partition function-call arguments."""

import os
import sys

import pytest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from partition_contract import validate_partition_tool_arguments


SOURCE_BOUND_BUCKETS = (
    "metadata",
    "all_assumption_candidates",
    "parameter_candidates",
    "derived_value_candidates",
    "output_candidates",
    "financial_series_candidates",
    "unclassified_inputs",
    "review_candidates",
    "scenario_structures",
    "sensitivity_structures",
)


def _valid_candidate():
    return {
        "candidate_id": "candidate-1",
        "original_label": "Tax rate",
        "submitted_role": "hardcoded_input",
        "raw_value": 0.25,
        "source_references": [{"sheet_name": "Inputs", "cell": "B2"}],
    }


def _arguments():
    return {
        "workbook_version": "a" * 64,
        "partition_id": "partition-1",
        "sheet_name": "Inputs",
        "primary_range": "A1:B2",
        "result": {
            "all_assumption_candidates": [],
            "output_candidates": [],
        },
    }


@pytest.mark.parametrize("bucket", SOURCE_BOUND_BUCKETS)
def test_source_defect_does_not_reject_complete_partition_arguments(bucket):
    arguments = _arguments()
    arguments["result"][bucket] = [{
        key: value
        for key, value in _valid_candidate().items()
        if key != "source_references"
    }]

    assert validate_partition_tool_arguments(arguments) is None


@pytest.mark.parametrize(
    "source_references",
    [
        [],
        ["Inputs!B2"],
        [{}],
        [{"sheet_name": "", "cell": "B2"}],
        [{"sheet_name": "Inputs", "cell": ""}],
        [{"sheet_name": 12, "cell": "B2"}],
        [{"sheet_name": "Inputs", "cell": None}],
    ],
)
def test_invalid_source_shape_is_deferred_to_candidate_validator(source_references):
    arguments = _arguments()
    candidate = _valid_candidate()
    candidate["source_references"] = source_references
    arguments["result"]["all_assumption_candidates"] = [candidate]

    assert validate_partition_tool_arguments(arguments) is None


def test_non_object_candidate_item_is_still_rejected():
    arguments = _arguments()
    arguments["result"]["all_assumption_candidates"] = ["Inputs!B2"]

    issue = validate_partition_tool_arguments(arguments)

    assert issue is not None
    assert issue.code == "partition_candidate_invalid"


@pytest.mark.parametrize(
    "field,value,expected_code",
    [
        ("result", None, "partition_result_missing"),
        ("all_assumption_candidates", None, "partition_bucket_invalid"),
        ("output_candidates", {}, "partition_bucket_invalid"),
    ],
)
def test_required_result_shape_is_rejected(field, value, expected_code):
    arguments = _arguments()
    if field == "result":
        arguments[field] = value
    else:
        arguments["result"][field] = value

    issue = validate_partition_tool_arguments(arguments)

    assert issue is not None
    assert issue.code == expected_code


def test_required_candidate_buckets_must_exist():
    arguments = _arguments()
    arguments["result"].pop("output_candidates")

    issue = validate_partition_tool_arguments(arguments)

    assert issue is not None
    assert issue.code == "partition_bucket_missing"


def test_canonical_financial_series_does_not_require_source_references():
    arguments = _arguments()
    arguments["result"]["financial_series"] = [{
        "series_id": "revenue",
        "label": "Revenue",
        "semantic_role": "financial_series",
        "business_role": "revenue",
        "category": "revenue",
        "unit": "USD",
        "frequency": "annual",
        "period_range": "Forecast!C3:J3",
        "value_range": "Forecast!C8:J8",
    }]

    assert validate_partition_tool_arguments(arguments) is None


def test_valid_source_bound_candidates_return_no_issue():
    arguments = _arguments()
    arguments["result"]["all_assumption_candidates"] = [_valid_candidate()]

    assert validate_partition_tool_arguments(arguments) is None
