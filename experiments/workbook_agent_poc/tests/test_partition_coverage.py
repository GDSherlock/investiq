"""Behavior tests for backend-owned partition coverage and binding."""

import os
import sys

import pytest
from openpyxl.utils import get_column_letter


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from partition_coverage import PartitionBindingError, PartitionCoverageTracker
from partition_planner import PartitionLimits, PartitionPlanner
from workbook_index import WorkbookIndex


def _fact(cell):
    return {
        "sheet_name": "Model",
        "cell": cell,
        "source_reference": f"Model!{cell}",
        "raw_value": f"value-{cell}-" + "x" * 300,
        "displayed_value": None,
        "formula": None,
        "formula_status": "static_value",
        "data_type": "s",
        "number_format": "General",
        "parse_warnings": [],
    }


def _index():
    facts = tuple(
        _fact(f"{get_column_letter(col)}{row}")
        for row in range(1, 5)
        for col in range(1, 5)
    )
    return WorkbookIndex(
        workbook_version="b" * 64,
        manifest={
            "sheet_count": 1,
            "hidden_sheet_count": 0,
            "sheets": [{
                "name": "Model",
                "state": "visible",
                "max_row": 4,
                "max_col": 4,
                "required_range": "A1:D4",
            }],
            "required_sheet_ranges": {"Model": "A1:D4"},
            "named_ranges": [],
            "external_links": [],
        },
        content_sheets=("Model",),
        required_ranges={"Model": "A1:D4"},
        facts={"Model": facts},
        formulas={},
        defined_names={},
        dependency_graph={
            "precedents": {},
            "dependents": {},
            "external_refs": {},
            "ranges": {},
        },
        non_empty_cell_count=16,
    )


def _limits():
    return PartitionLimits(
        max_total_tokens=12_000,
        max_raw_evidence_tokens=2_000,
        max_request_bytes=24_000,
    )


def _bound_empty_result(partition):
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


def test_submission_requires_every_planned_leaf_and_complete_primary_geometry():
    index = _index()
    partitions = PartitionPlanner(_limits()).plan(index)
    assert len(partitions) > 1
    tracker = PartitionCoverageTracker(index, partitions)

    for partition in partitions[:-1]:
        tracker.record_completed(partition, _bound_empty_result(partition))

    assert tracker.submission_allowed() is False
    assert tracker.summary()["missing_partition_ids"] == [
        partitions[-1].partition_id
    ]

    tracker.record_completed(
        partitions[-1],
        _bound_empty_result(partitions[-1]),
    )

    assert tracker.submission_allowed() is True
    assert tracker.summary()["missing_primary_ranges"] == {}


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("workbook_version", "wrong-hash"),
        ("partition_id", "wrong-partition"),
        ("sheet_name", "WrongSheet"),
        ("primary_range", "A1:A1"),
    ],
)
def test_wrong_partial_binding_is_rejected(field, bad_value):
    index = _index()
    partition = PartitionPlanner().plan(index)[0]
    payload = _bound_empty_result(partition)
    payload[field] = bad_value
    tracker = PartitionCoverageTracker(index, [partition])

    with pytest.raises(PartitionBindingError):
        tracker.record_completed(partition, payload)

    assert tracker.summary()["binding_error_count"] == 1
    assert tracker.submission_allowed() is False


def test_context_split_replaces_parent_with_children_without_coverage_gap():
    index = _index()
    planner = PartitionPlanner()
    parent = planner.plan(index)[0]
    children = planner.split(index, parent)
    tracker = PartitionCoverageTracker(index, [parent])

    tracker.replace_for_split(parent, children)
    for child in children:
        tracker.record_completed(child, _bound_empty_result(child))

    summary = tracker.summary()
    assert parent.partition_id not in summary["required_partition_ids"]
    assert summary["split_count"] == 1
    assert summary["missing_primary_ranges"] == {}
    assert tracker.submission_allowed() is True


def test_duplicate_partition_completion_is_rejected():
    index = _index()
    partition = PartitionPlanner().plan(index)[0]
    tracker = PartitionCoverageTracker(index, [partition])
    payload = _bound_empty_result(partition)
    tracker.record_completed(partition, payload)

    with pytest.raises(PartitionBindingError):
        tracker.record_completed(partition, payload)

    assert tracker.summary()["binding_error_count"] == 1
