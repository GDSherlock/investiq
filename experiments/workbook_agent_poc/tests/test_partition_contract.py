"""Nested contract checks for partition function-call arguments."""

from copy import deepcopy
import os
import sys

import pytest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extraction_contract import SUBMIT_RESULT_SCHEMA


LEGACY_SCHEMA_SNAPSHOT = deepcopy(SUBMIT_RESULT_SCHEMA)


from partition_contract import (
    PARTITION_RESULT_BUCKETS,
    PARTITION_SYSTEM_PROMPT,
    SUBMIT_PARTITION_TOOL,
    validate_partition_tool_arguments,
)


UNSUPPORTED_STRICT_KEYWORDS = {
    "minItems",
    "maxItems",
    "uniqueItems",
    "pattern",
    "format",
    "minimum",
    "maximum",
}


def _resolve_ref(root, schema):
    ref = schema.get("$ref") if isinstance(schema, dict) else None
    if not ref:
        return schema
    assert ref.startswith("#/$defs/")
    return root["$defs"][ref.rsplit("/", 1)[-1]]


def _walk_schema(root, schema, *, seen_refs=None):
    seen_refs = set() if seen_refs is None else seen_refs
    if not isinstance(schema, dict):
        return
    assert not (UNSUPPORTED_STRICT_KEYWORDS & set(schema))
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen_refs:
            return
        seen_refs.add(ref)
        yield from _walk_schema(
            root,
            _resolve_ref(root, schema),
            seen_refs=seen_refs,
        )
        return
    schema_type = schema.get("type")
    if schema_type == "object":
        properties = schema.get("properties", {})
        assert schema.get("additionalProperties") is False
        assert set(schema.get("required", [])) == set(properties)
        yield schema
        for child in properties.values():
            yield from _walk_schema(root, child, seen_refs=seen_refs)
    elif schema_type == "array" or (
        isinstance(schema_type, list) and "array" in schema_type
    ):
        yield from _walk_schema(root, schema.get("items"), seen_refs=seen_refs)


def _logical_object_depth(root, schema, *, active_refs=()):
    if not isinstance(schema, dict):
        return 0
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref not in active_refs
        return _logical_object_depth(
            root,
            _resolve_ref(root, schema),
            active_refs=(*active_refs, ref),
        )
    schema_type = schema.get("type")
    if schema_type == "object":
        children = [
            _logical_object_depth(root, child, active_refs=active_refs)
            for child in schema.get("properties", {}).values()
        ]
        return 1 + max(children, default=0)
    if schema_type == "array" or (
        isinstance(schema_type, list) and "array" in schema_type
    ):
        return _logical_object_depth(
            root,
            schema.get("items"),
            active_refs=active_refs,
        )
    return 0


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
        "result": {bucket: [] for bucket in PARTITION_RESULT_BUCKETS},
    }


def test_partition_tool_uses_closed_strict_schema_without_changing_legacy():
    function = SUBMIT_PARTITION_TOOL["function"]
    parameters = function["parameters"]

    assert function["strict"] is True
    object_nodes = list(_walk_schema(parameters, parameters))
    assert object_nodes
    assert sum(len(node["properties"]) for node in object_nodes) <= 100
    assert _logical_object_depth(parameters, parameters) <= 5
    assert SUBMIT_RESULT_SCHEMA == LEGACY_SCHEMA_SNAPSHOT
    assert "strict" not in SUBMIT_RESULT_SCHEMA


def test_partition_result_requires_exactly_the_eleven_backend_buckets():
    result_schema = SUBMIT_PARTITION_TOOL["function"]["parameters"][
        "properties"
    ]["result"]

    assert tuple(result_schema["properties"]) == PARTITION_RESULT_BUCKETS
    assert set(result_schema["required"]) == set(PARTITION_RESULT_BUCKETS)
    assert "coverage_declaration" not in result_schema["properties"]
    assert all(
        schema["type"] == "array"
        for schema in result_schema["properties"].values()
    )


def test_prompt_contains_exact_mandatory_bucket_and_source_contract():
    for bucket in PARTITION_RESULT_BUCKETS:
        assert bucket in PARTITION_SYSTEM_PROMPT
    assert "MANDATORY OUTPUT CONTRACT" in PARTITION_SYSTEM_PROMPT
    assert "return []" in PARTITION_SYSTEM_PROMPT
    assert "Never omit a bucket" in PARTITION_SYSTEM_PROMPT
    assert "Never fabricate a reference" in PARTITION_SYSTEM_PROMPT
    assert "coverage_declaration" in PARTITION_SYSTEM_PROMPT


def test_financial_series_ranges_are_described_as_qualified_a1_addresses():
    financial_series = SUBMIT_PARTITION_TOOL["function"]["parameters"]["$defs"][
        "financial_series"
    ]["properties"]

    assert "fully qualified Excel A1 address" in PARTITION_SYSTEM_PROMPT
    assert "not a label span such as 2027-2053 or 0-26" in PARTITION_SYSTEM_PROMPT
    assert "fully qualified Excel A1 address" in financial_series["period_range"][
        "description"
    ]
    assert "not a label span" in financial_series["period_range"]["description"]
    assert "fully qualified Excel A1 address" in financial_series["value_range"][
        "description"
    ]


@pytest.mark.parametrize("bucket", PARTITION_RESULT_BUCKETS)
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
    assert issue.field_path == "result.all_assumption_candidates[0]"


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


def test_any_missing_partition_bucket_is_rejected_with_safe_field_path():
    for bucket in PARTITION_RESULT_BUCKETS:
        arguments = _arguments()
        arguments["result"].pop(bucket)

        issue = validate_partition_tool_arguments(arguments)

        assert issue is not None
        assert issue.code == "partition_bucket_missing"
        assert issue.field_path == f"result.{bucket}"


def test_unknown_partition_bucket_is_rejected():
    arguments = _arguments()
    arguments["result"]["coverage_declaration"] = {}

    issue = validate_partition_tool_arguments(arguments)

    assert issue is not None
    assert issue.code == "partition_bucket_unexpected"
    assert issue.field_path == "result.coverage_declaration"


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
