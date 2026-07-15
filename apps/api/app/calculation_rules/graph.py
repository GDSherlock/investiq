"""Workbook-cell dependency graph, SCC detection, and stable execution order."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Mapping, Sequence

from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter

from .types import (
    CalculationRuleExtractionConfiguration,
    FormulaCompilation,
    FormulaReference,
    WorkbookCatalog,
    WorkbookCellRef,
)


@dataclass(frozen=True)
class CalculationGraphPlan:
    evaluation_order: tuple[WorkbookCellRef, ...]
    cycles: tuple[tuple[WorkbookCellRef, ...], ...]
    status_by_cell: Mapping[WorkbookCellRef, str]
    precedents_by_formula: Mapping[WorkbookCellRef, tuple[WorkbookCellRef, ...]]
    dependents_by_cell: Mapping[WorkbookCellRef, tuple[WorkbookCellRef, ...]]
    edge_count: int


@dataclass
class _TarjanFrame:
    node: WorkbookCellRef
    parent: WorkbookCellRef | None
    neighbors: tuple[WorkbookCellRef, ...]
    next_index: int = 0


class CalculationGraphBuilder:
    def __init__(
        self,
        configuration: CalculationRuleExtractionConfiguration | None = None,
    ):
        self._configuration = configuration or CalculationRuleExtractionConfiguration()

    def build(
        self,
        catalog: WorkbookCatalog,
        compilations: Sequence[FormulaCompilation],
    ) -> CalculationGraphPlan:
        formula_by_id = {formula.id: formula for formula in catalog.formulas}
        compilation_by_cell_id = {
            compilation.formula_cell_id: compilation for compilation in compilations
        }
        if set(compilation_by_cell_id) != set(formula_by_id):
            raise ValueError("Compilations must cover every inventoried formula cell")

        formula_refs = {
            formula.id: formula.ref for formula in catalog.formulas
        }
        formula_ref_set = set(formula_refs.values())
        status_by_cell: dict[WorkbookCellRef, str] = {}
        precedents: dict[WorkbookCellRef, tuple[WorkbookCellRef, ...]] = {}
        dependents: dict[WorkbookCellRef, set[WorkbookCellRef]] = {}
        edge_count = 0

        for formula in catalog.formulas:
            compilation = compilation_by_cell_id[formula.id]
            formula_ref = formula.ref
            if compilation.support_status != "supported":
                status_by_cell[formula_ref] = "not_executable"
                precedents[formula_ref] = ()
                continue
            expanded: list[WorkbookCellRef] = []
            for reference in compilation.references:
                if reference.resolution_status != "resolved_internal":
                    continue
                for target in expand_reference(reference, catalog):
                    expanded.append(target)
                    dependents.setdefault(target, set()).add(formula_ref)
                    edge_count += 1
                    if edge_count > self._configuration.max_total_edges:
                        raise ValueError(
                            "Dependency graph exceeds configured dependency edge limit"
                        )
            precedents[formula_ref] = tuple(
                sorted(set(expanded), key=_cell_sort_key)
            )
            status_by_cell[formula_ref] = "ready"

        supported_formula_refs = {
            reference
            for reference, status in status_by_cell.items()
            if status == "ready"
        }
        formula_dependencies = {
            reference: tuple(
                precedent
                for precedent in precedents[reference]
                if precedent in formula_ref_set
            )
            for reference in supported_formula_refs
        }
        cycle_components = _tarjan_cycles(formula_dependencies)
        cycle_members = {
            member for component in cycle_components for member in component
        }
        for member in cycle_members:
            status_by_cell[member] = "cycle"

        changed = True
        while changed:
            changed = False
            for reference in sorted(supported_formula_refs, key=_cell_sort_key):
                if status_by_cell[reference] != "ready":
                    continue
                formula_precedents = (
                    precedent
                    for precedent in precedents[reference]
                    if precedent in formula_ref_set
                )
                if any(
                    status_by_cell[precedent]
                    in {"not_executable", "cycle", "blocked_by_dependency"}
                    for precedent in formula_precedents
                ):
                    status_by_cell[reference] = "blocked_by_dependency"
                    changed = True

        ready = {
            reference
            for reference, status in status_by_cell.items()
            if status == "ready"
        }
        indegree = {
            reference: sum(
                1
                for precedent in precedents[reference]
                if precedent in ready
            )
            for reference in ready
        }
        heap: list[tuple[tuple[int, int, int], WorkbookCellRef]] = [
            (_cell_sort_key(reference), reference)
            for reference, count in indegree.items()
            if count == 0
        ]
        heapq.heapify(heap)
        evaluation_order: list[WorkbookCellRef] = []
        while heap:
            _sort_key, reference = heapq.heappop(heap)
            evaluation_order.append(reference)
            for dependent in sorted(dependents.get(reference, ()), key=_cell_sort_key):
                if dependent not in ready:
                    continue
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(heap, (_cell_sort_key(dependent), dependent))
        if len(evaluation_order) != len(ready):
            raise ValueError("Executable dependency graph contains an unclassified cycle")

        return CalculationGraphPlan(
            evaluation_order=tuple(evaluation_order),
            cycles=cycle_components,
            status_by_cell=status_by_cell,
            precedents_by_formula=precedents,
            dependents_by_cell={
                reference: tuple(sorted(items, key=_cell_sort_key))
                for reference, items in dependents.items()
            },
            edge_count=edge_count,
        )

def _cell_sort_key(reference: WorkbookCellRef) -> tuple[int, int, int]:
    row, column = coordinate_to_tuple(reference.cell_address)
    return reference.sheet_position, row, column


def expand_reference(
    reference: FormulaReference,
    catalog: WorkbookCatalog,
) -> tuple[WorkbookCellRef, ...]:
    """Expand one resolved internal scalar/range reference without truncation."""
    if reference.target_sheet_name is None or reference.target_sheet_position is None:
        return ()
    if reference.start_cell_address is None:
        return ()
    if reference.reference_kind == "cell":
        return (
            WorkbookCellRef(
                catalog.workbook_version_id,
                reference.target_sheet_name,
                reference.target_sheet_position,
                reference.start_cell_address,
            ),
        )
    if reference.end_cell_address is None:
        return ()
    start_row, start_column = coordinate_to_tuple(reference.start_cell_address)
    end_row, end_column = coordinate_to_tuple(reference.end_cell_address)
    return tuple(
        WorkbookCellRef(
            catalog.workbook_version_id,
            reference.target_sheet_name,
            reference.target_sheet_position,
            f"{get_column_letter(column)}{row}",
        )
        for row in range(start_row, end_row + 1)
        for column in range(start_column, end_column + 1)
    )


def _tarjan_cycles(
    dependencies: Mapping[WorkbookCellRef, Sequence[WorkbookCellRef]],
) -> tuple[tuple[WorkbookCellRef, ...], ...]:
    """Return deterministic SCC cycles using an explicit Tarjan DFS stack."""
    index = 0
    indices: dict[WorkbookCellRef, int] = {}
    lowlinks: dict[WorkbookCellRef, int] = {}
    stack: list[WorkbookCellRef] = []
    on_stack: set[WorkbookCellRef] = set()
    components: list[tuple[WorkbookCellRef, ...]] = []

    def push(
        node: WorkbookCellRef,
        parent: WorkbookCellRef | None,
        frames: list[_TarjanFrame],
    ) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        neighbors = tuple(
            precedent
            for precedent in sorted(dependencies.get(node, ()), key=_cell_sort_key)
            if precedent in dependencies
        )
        frames.append(_TarjanFrame(node, parent, neighbors))

    for start_node in sorted(dependencies, key=_cell_sort_key):
        if start_node in indices:
            continue
        frames: list[_TarjanFrame] = []
        push(start_node, None, frames)
        while frames:
            frame = frames[-1]
            node = frame.node
            if frame.next_index < len(frame.neighbors):
                precedent = frame.neighbors[frame.next_index]
                frame.next_index += 1
                if precedent not in indices:
                    push(precedent, node, frames)
                elif precedent in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[precedent])
                continue

            frames.pop()
            if frame.parent is not None:
                lowlinks[frame.parent] = min(
                    lowlinks[frame.parent],
                    lowlinks[node],
                )
            if lowlinks[node] != indices[node]:
                continue
            component: list[WorkbookCellRef] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            ordered = tuple(sorted(component, key=_cell_sort_key))
            if len(ordered) > 1 or node in dependencies.get(node, ()):
                components.append(ordered)
    return tuple(sorted(components, key=lambda component: _cell_sort_key(component[0])))
