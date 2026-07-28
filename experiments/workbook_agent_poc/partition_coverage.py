"""Backend-owned binding and geometric coverage for partitioned extraction."""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

from openpyxl.utils import get_column_letter, range_boundaries

from partition_planner import WorkbookPartition
from workbook_index import WorkbookIndex


class PartitionBindingError(ValueError):
    pass


def _range_cells(cell_range: str) -> set[tuple[int, int]]:
    min_col, min_row, max_col, max_row = range_boundaries(cell_range)
    return {
        (row, col)
        for row in range(min_row, max_row + 1)
        for col in range(min_col, max_col + 1)
    }


def _compress_cells(cells: set[tuple[int, int]]) -> list[str]:
    return [
        f"{get_column_letter(col)}{row}"
        for row, col in sorted(cells)
    ]


class PartitionCoverageTracker:
    def __init__(
        self,
        index: WorkbookIndex,
        planned: Sequence[WorkbookPartition],
    ) -> None:
        self._index = index
        self._active_order: list[str] = []
        self._required_by_id: dict[str, WorkbookPartition] = {}
        self._completed_by_id: dict[str, dict[str, Any]] = {}
        self._binding_errors: list[str] = []
        self._split_count = 0

        for partition in planned:
            if partition.workbook_version != index.workbook_version:
                raise PartitionBindingError(
                    "Planned partition is bound to a different workbook."
                )
            if partition.partition_id in self._required_by_id:
                raise PartitionBindingError("Duplicate planned partition ID.")
            self._active_order.append(partition.partition_id)
            self._required_by_id[partition.partition_id] = partition

    def record_completed(
        self,
        partition: WorkbookPartition,
        partial_result: dict[str, Any],
    ) -> None:
        expected = self._required_by_id.get(partition.partition_id)
        if expected is None or expected != partition:
            self._raise_binding("Completion does not belong to an active partition.")
        if partition.partition_id in self._completed_by_id:
            self._raise_binding("Partition completion was recorded more than once.")

        expected_fields = {
            "workbook_version": partition.workbook_version,
            "partition_id": partition.partition_id,
            "sheet_name": partition.sheet_name,
            "primary_range": partition.primary_range,
        }
        for field, expected_value in expected_fields.items():
            actual = partial_result.get(field)
            if field == "primary_range" and isinstance(actual, str):
                actual = actual.upper()
            if actual != expected_value:
                self._raise_binding(
                    f"Partition result {field} does not match its planned binding."
                )
        if not isinstance(partial_result.get("result"), dict):
            self._raise_binding("Partition result is missing its structured result.")

        self._completed_by_id[partition.partition_id] = partial_result

    def replace_for_split(
        self,
        parent: WorkbookPartition,
        children: tuple[WorkbookPartition, WorkbookPartition],
    ) -> None:
        expected = self._required_by_id.get(parent.partition_id)
        if expected is None or expected != parent:
            self._raise_binding("Split parent is not an active partition.")
        if parent.partition_id in self._completed_by_id:
            self._raise_binding("A completed partition cannot be split.")

        parent_cells = _range_cells(parent.primary_range)
        child_cells = [_range_cells(child.primary_range) for child in children]
        if child_cells[0] & child_cells[1] or child_cells[0] | child_cells[1] != parent_cells:
            self._raise_binding("Split children do not exactly tile the parent range.")
        if any(
            child.workbook_version != self._index.workbook_version
            or child.parent_partition_id != parent.partition_id
            or child.sheet_name != parent.sheet_name
            for child in children
        ):
            self._raise_binding("Split children are bound to the wrong parent.")

        position = self._active_order.index(parent.partition_id)
        self._active_order[position:position + 1] = [
            child.partition_id for child in children
        ]
        del self._required_by_id[parent.partition_id]
        for child in children:
            if child.partition_id in self._required_by_id:
                self._raise_binding("Split produced a duplicate partition ID.")
            self._required_by_id[child.partition_id] = child
        self._split_count += 1

    def submission_allowed(self) -> bool:
        state = self._coverage_state()
        return (
            not self._binding_errors
            and not state["missing_partition_ids"]
            and not state["missing_primary_ranges"]
            and not state["primary_overlap_ranges"]
        )

    def summary(self) -> dict[str, Any]:
        state = self._coverage_state()
        return {
            "workbook_version": self._index.workbook_version,
            "planned_partition_count": len(self._active_order),
            "completed_partition_count": len(self._completed_by_id),
            "required_partition_ids": list(self._active_order),
            "missing_partition_ids": state["missing_partition_ids"],
            "missing_primary_ranges": state["missing_primary_ranges"],
            "primary_overlap_ranges": state["primary_overlap_ranges"],
            "binding_error_count": len(self._binding_errors),
            "split_count": self._split_count,
            "submission_allowed": self.submission_allowed(),
            "partition_telemetry": [
                {
                    "partition_id": partition.partition_id,
                    "sheet_name": partition.sheet_name,
                    "primary_range": partition.primary_range,
                    "estimated_total_tokens": partition.estimated_total_tokens,
                    "estimated_raw_tokens": partition.estimated_raw_tokens,
                    "request_bytes": partition.request_bytes,
                    "completed": partition.partition_id in self._completed_by_id,
                }
                for partition in (
                    self._required_by_id[partition_id]
                    for partition_id in self._active_order
                )
            ],
        }

    def _coverage_state(self) -> dict[str, Any]:
        missing_partition_ids = [
            partition_id
            for partition_id in self._active_order
            if partition_id not in self._completed_by_id
        ]
        completed_by_sheet: dict[str, set[tuple[int, int]]] = {
            sheet_name: set() for sheet_name in self._index.content_sheets
        }
        active_counts: dict[str, Counter[tuple[int, int]]] = {
            sheet_name: Counter() for sheet_name in self._index.content_sheets
        }
        for partition_id in self._active_order:
            partition = self._required_by_id[partition_id]
            cells = _range_cells(partition.primary_range)
            active_counts.setdefault(partition.sheet_name, Counter()).update(cells)
            if partition_id in self._completed_by_id:
                completed_by_sheet.setdefault(partition.sheet_name, set()).update(cells)

        missing_primary_ranges: dict[str, list[str]] = {}
        primary_overlap_ranges: dict[str, list[str]] = {}
        for sheet_name in self._index.content_sheets:
            required = _range_cells(self._index.required_ranges[sheet_name])
            missing = required - completed_by_sheet.get(sheet_name, set())
            if missing:
                missing_primary_ranges[sheet_name] = _compress_cells(missing)
            overlaps = {
                cell
                for cell, count in active_counts.get(sheet_name, Counter()).items()
                if count > 1
            }
            if overlaps:
                primary_overlap_ranges[sheet_name] = _compress_cells(overlaps)

        return {
            "missing_partition_ids": missing_partition_ids,
            "missing_primary_ranges": missing_primary_ranges,
            "primary_overlap_ranges": primary_overlap_ranges,
        }

    def _raise_binding(self, message: str) -> None:
        self._binding_errors.append(message)
        raise PartitionBindingError(message)


__all__ = ["PartitionBindingError", "PartitionCoverageTracker"]
