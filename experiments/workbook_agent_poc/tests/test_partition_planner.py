"""Behavior tests for bounded workbook partition planning."""

import json
import os
import sys

import pytest
from openpyxl.utils import get_column_letter, range_boundaries


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from partition_contract import (
    SUBMIT_PARTITION_TOOL,
    SUBMIT_RECONCILIATION_TOOL,
    build_partition_envelope,
)
from partition_planner import (
    PLANNER_VERSION,
    PartitionLimits,
    PartitionPlanner,
    PartitionPlanningError,
    stable_partition_id,
)
from workbook_index import WorkbookIndex


def _fact(sheet, cell, value, formula=None):
    return {
        "sheet_name": sheet,
        "cell": cell,
        "source_reference": f"{sheet}!{cell}",
        "raw_value": value,
        "displayed_value": None,
        "formula": formula,
        "formula_status": (
            "formula_with_cached_value" if formula else "static_value"
        ),
        "data_type": "n" if isinstance(value, (int, float)) else "s",
        "number_format": "General",
        "parse_warnings": [],
    }


def _index(*, value_size=1_200):
    facts = []
    for row in range(1, 5):
        for col in range(1, 5):
            cell = f"{get_column_letter(col)}{row}"
            facts.append(_fact("Model", cell, f"{cell}-" + "x" * value_size))
    facts[-1] = _fact("Model", "D4", 2.0, formula="=Inputs!B2")
    dependency = _fact("Inputs", "B2", 1.0)
    return WorkbookIndex(
        workbook_version="a" * 64,
        manifest={
            "sheet_count": 2,
            "hidden_sheet_count": 0,
            "sheets": [
                {
                    "name": "Model",
                    "state": "visible",
                    "max_row": 4,
                    "max_col": 4,
                    "required_range": "A1:D4",
                },
                {
                    "name": "Inputs",
                    "state": "visible",
                    "max_row": 2,
                    "max_col": 2,
                    "required_range": "A1:B2",
                },
            ],
            "required_sheet_ranges": {
                "Model": "A1:D4",
                "Inputs": "A1:B2",
            },
            "named_ranges": [],
            "external_links": [],
        },
        content_sheets=("Model",),
        required_ranges={"Model": "A1:D4"},
        facts={"Model": tuple(facts), "Inputs": (dependency,)},
        formulas={"Model!D4": "=Inputs!B2"},
        defined_names={},
        dependency_graph={
            "precedents": {"Model!D4": ["Inputs!B2"]},
            "dependents": {"Inputs!B2": ["Model!D4"]},
            "external_refs": {},
            "ranges": {"Model!D4": []},
        },
        non_empty_cell_count=17,
    )


def _rectangle_cells(cell_range):
    min_col, min_row, max_col, max_row = range_boundaries(cell_range)
    return {
        (row, col)
        for row in range(min_row, max_row + 1)
        for col in range(min_col, max_col + 1)
    }


def test_planner_tiles_every_required_cell_without_primary_overlap():
    index = _index()
    limits = PartitionLimits(
        max_total_tokens=14_000,
        max_raw_evidence_tokens=4_000,
        max_request_bytes=30_000,
    )

    partitions = PartitionPlanner(limits).plan(index)

    assert partitions == PartitionPlanner(limits).plan(index)
    covered = set()
    coverage_count = 0
    for partition in partitions:
        cells = _rectangle_cells(partition.primary_range)
        covered.update(cells)
        coverage_count += len(cells)
    assert covered == _rectangle_cells("A1:D4")
    assert coverage_count == len(covered)
    assert all(partition.workbook_version == index.workbook_version for partition in partitions)


def test_partition_id_is_bound_to_hash_sheet_range_and_planner_version():
    index = _index(value_size=10)
    partition = PartitionPlanner().plan(index)[0]

    assert partition.partition_id == stable_partition_id(
        index.workbook_version,
        partition.sheet_name,
        partition.primary_range,
        PLANNER_VERSION,
    )


def test_exact_serialized_size_forces_split_even_when_token_estimate_fits():
    index = _index(value_size=2_000)
    limits = PartitionLimits(
        max_total_tokens=1_000_000,
        max_raw_evidence_tokens=1_000_000,
        max_request_bytes=24_000,
    )

    partitions = PartitionPlanner(limits).plan(index)

    assert len(partitions) > 1
    assert all(
        partition.request_bytes <= limits.max_request_bytes
        for partition in partitions
    )


def test_single_cell_larger_than_request_budget_fails_without_truncation():
    index = _index(value_size=30_000)
    index = WorkbookIndex(
        **{
            **index.__dict__,
            "required_ranges": {"Model": "A1:A1"},
            "facts": {"Model": (index.facts["Model"][0],), "Inputs": index.facts["Inputs"]},
            "formulas": {},
            "dependency_graph": {
                "precedents": {},
                "dependents": {},
                "external_refs": {},
                "ranges": {},
            },
        }
    )

    with pytest.raises(PartitionPlanningError) as exc:
        PartitionPlanner(PartitionLimits(max_request_bytes=12_000)).plan(index)

    assert exc.value.code == "partition_cell_too_large"
    assert exc.value.sheet_name == "Model"
    assert exc.value.cell == "A1"


def test_partition_envelope_contains_bound_primary_and_dependency_evidence():
    index = _index(value_size=10)
    partition = PartitionPlanner().plan(index)[0]

    envelope = build_partition_envelope(index, partition)

    assert envelope["workbook_version"] == index.workbook_version
    assert envelope["partition_id"] == partition.partition_id
    assert envelope["primary_range"] == partition.primary_range
    assert envelope["dependency_references"] == ["Inputs!B2"]
    assert envelope["dependency_evidence"][0]["source_reference"] == "Inputs!B2"


def test_partial_contract_requires_binding_and_has_no_final_submit_tool():
    parameters = SUBMIT_PARTITION_TOOL["function"]["parameters"]

    assert set(parameters["required"]) == {
        "workbook_version",
        "partition_id",
        "sheet_name",
        "primary_range",
        "result",
    }
    assert SUBMIT_PARTITION_TOOL["function"]["name"] == "submit_partition_result"
    assert "submit_extraction_result" not in json.dumps(SUBMIT_PARTITION_TOOL)


def test_reconciliation_contract_can_only_select_or_defer_a_conflict():
    properties = SUBMIT_RECONCILIATION_TOOL["function"]["parameters"][
        "properties"
    ]

    assert properties["resolution"]["enum"] == ["select", "review_required"]
    assert properties["selected_bucket"]["type"] == ["string", "null"]
    assert "raw_value" not in properties
