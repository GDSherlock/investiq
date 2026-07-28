"""Deterministic, request-scoped workbook index for partitioned extraction."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from openpyxl.utils.cell import coordinate_to_tuple, range_boundaries

from dependency import build_dependency_graph
from workbook_tools import WorkbookToolset


@dataclass(frozen=True, order=True)
class CellAddress:
    sheet_name: str
    cell: str

    @property
    def source_reference(self) -> str:
        return f"{self.sheet_name}!{self.cell}"


@dataclass(frozen=True)
class WorkbookIndex:
    workbook_version: str
    manifest: dict[str, Any]
    content_sheets: tuple[str, ...]
    required_ranges: dict[str, str]
    facts: dict[str, tuple[dict[str, Any], ...]]
    formulas: dict[str, str]
    defined_names: dict[str, str]
    dependency_graph: dict[str, Any]
    non_empty_cell_count: int

    def facts_for_range(
        self,
        sheet_name: str,
        cell_range: str,
    ) -> tuple[dict[str, Any], ...]:
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
        selected = []
        for fact in self.facts.get(sheet_name, ()):
            row, col = coordinate_to_tuple(fact["cell"])
            if min_row <= row <= max_row and min_col <= col <= max_col:
                selected.append(deepcopy(fact))
        return tuple(selected)

    def related_references(
        self,
        sheet_name: str,
        cell_range: str,
    ) -> tuple[str, ...]:
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
        related: set[str] = set()
        precedents = self.dependency_graph.get("precedents", {})
        ranges = self.dependency_graph.get("ranges", {})

        for formula_ref in self.formulas:
            formula_sheet, formula_cell = formula_ref.rsplit("!", 1)
            if formula_sheet != sheet_name:
                continue
            row, col = coordinate_to_tuple(formula_cell)
            if not (min_row <= row <= max_row and min_col <= col <= max_col):
                continue
            for reference in (*precedents.get(formula_ref, ()), *ranges.get(formula_ref, ())):
                if not _reference_is_inside(
                    reference,
                    sheet_name=sheet_name,
                    bounds=(min_col, min_row, max_col, max_row),
                ):
                    related.add(reference)
        return tuple(sorted(related))


def _reference_is_inside(
    reference: str,
    *,
    sheet_name: str,
    bounds: tuple[int, int, int, int],
) -> bool:
    try:
        reference_sheet, cell_range = reference.rsplit("!", 1)
        ref_min_col, ref_min_row, ref_max_col, ref_max_row = range_boundaries(cell_range)
    except (TypeError, ValueError):
        return False
    min_col, min_row, max_col, max_row = bounds
    return (
        reference_sheet == sheet_name
        and min_col <= ref_min_col <= ref_max_col <= max_col
        and min_row <= ref_min_row <= ref_max_row <= max_row
    )


class WorkbookIndexBuilder:
    def build(self, tools: WorkbookToolset) -> WorkbookIndex:
        manifest = tools.get_workbook_metadata()
        content_sheet_names = tools.content_sheets()
        content_sheets = tuple(
            sheet["name"]
            for sheet in manifest["sheets"]
            if sheet["name"] in content_sheet_names
        )
        required_ranges = {
            sheet["name"]: sheet["required_range"]
            for sheet in manifest["sheets"]
            if sheet["name"] in content_sheet_names
        }

        facts: dict[str, tuple[dict[str, Any], ...]] = {}
        for sheet_name in content_sheets:
            references = sorted(
                tools.non_empty_cell_references(sheet_name),
                key=coordinate_to_tuple,
            )
            facts[sheet_name] = tuple(
                tools.get_cell(sheet_name, reference) for reference in references
            )

        formula_items = list(tools.iter_formulas())
        formulas = {
            f"{sheet_name}!{cell}": formula
            for sheet_name, cell, formula in formula_items
        }
        defined_names = tools.defined_names()
        dependency_graph = build_dependency_graph(formula_items, defined_names)

        return WorkbookIndex(
            workbook_version=tools.workbook_version,
            manifest=deepcopy(manifest),
            content_sheets=content_sheets,
            required_ranges=required_ranges,
            facts=facts,
            formulas=formulas,
            defined_names=dict(defined_names),
            dependency_graph=dependency_graph,
            non_empty_cell_count=sum(len(sheet_facts) for sheet_facts in facts.values()),
        )


__all__ = ["CellAddress", "WorkbookIndex", "WorkbookIndexBuilder"]
