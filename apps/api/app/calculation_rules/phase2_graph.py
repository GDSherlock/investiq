"""Immutable graph versions and incremental dirty propagation for Phase 2."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Iterable, Mapping, Sequence
import uuid

from openpyxl.utils.cell import coordinate_to_tuple

from .graph import CalculationGraphPlan
from .phase2_types import Phase2CalculationConfiguration
from .types import FormulaCompilation, WorkbookCatalog, WorkbookCellRef


@dataclass(frozen=True)
class CalculationGraphComponent:
    id: str
    ordinal: int
    classification: str
    members: tuple[WorkbookCellRef, ...]
    topological_layer: int | None
    iteration_enabled: bool = False


@dataclass(frozen=True)
class CalculationGraphVersion:
    id: str
    workbook_version_id: str
    compiler_manifest_hash: str
    content_fingerprint: str
    node_count: int
    edge_count: int
    components: tuple[CalculationGraphComponent, ...]
    topological_layers: tuple[tuple[WorkbookCellRef, ...], ...]
    base_plan: CalculationGraphPlan = field(repr=False, compare=False)


@dataclass(frozen=True)
class DirtyPropagationPlan:
    changed_cells: tuple[WorkbookCellRef, ...]
    dirty_formula_cells: tuple[WorkbookCellRef, ...]
    reusable_formula_cells: tuple[WorkbookCellRef, ...]


class VersionedCalculationGraphBuilder:
    def __init__(
        self,
        configuration: Phase2CalculationConfiguration | None = None,
    ) -> None:
        self._configuration = configuration or Phase2CalculationConfiguration()

    def build(
        self,
        catalog: WorkbookCatalog,
        compilations: Sequence[FormulaCompilation],
        base_plan: CalculationGraphPlan,
    ) -> CalculationGraphVersion:
        formula_refs = tuple(
            sorted(catalog.formula_by_ref(), key=_cell_sort_key)
        )
        if set(formula_refs) != set(base_plan.status_by_cell):
            raise ValueError("Versioned graph must cover every formula cell")
        compilation_payload = [
            {
                "formula_cell_id": item.formula_cell_id,
                "expression_id": item.expression_id,
                "ir_version": item.ir_version,
                "compiler_version": item.compiler_version,
                "semantics_profile": item.semantics_profile,
                "support_status": item.support_status,
            }
            for item in sorted(compilations, key=lambda item: item.formula_cell_id)
        ]
        manifest = {
            "workbook_version_id": catalog.workbook_version_id,
            "compiler_version": self._configuration.compiler_version,
            "ir_version": self._configuration.ir_version,
            "registry_version": self._configuration.function_registry_version,
            "semantics_profile": self._configuration.semantics_profile,
            "configuration_hash": self._configuration.configuration_hash,
            "compilations": compilation_payload,
        }
        compiler_manifest_hash = _hash_payload(manifest)
        graph_id = str(
            uuid.uuid5(
                uuid.UUID(catalog.workbook_version_id),
                compiler_manifest_hash,
            )
        )
        graph_payload = {
            "nodes": [_ref_payload(item) for item in formula_refs],
            "edges": [
                {
                    "precedent": _ref_payload(precedent),
                    "dependent": _ref_payload(dependent),
                }
                for dependent in sorted(
                    base_plan.precedents_by_formula,
                    key=_cell_sort_key,
                )
                for precedent in sorted(
                    base_plan.precedents_by_formula[dependent],
                    key=_cell_sort_key,
                )
            ],
            "statuses": [
                {
                    "cell": _ref_payload(reference),
                    "status": base_plan.status_by_cell[reference],
                }
                for reference in formula_refs
            ],
        }
        content_fingerprint = _hash_payload(graph_payload)
        layers = _topological_layers(base_plan)
        layer_by_cell = {
            member: ordinal
            for ordinal, members in enumerate(layers)
            for member in members
        }
        components = _components(
            graph_id,
            formula_refs,
            base_plan,
            layer_by_cell,
        )
        if sum(len(item.members) for item in components) != len(formula_refs):
            raise ValueError("Graph component partition is incomplete")
        return CalculationGraphVersion(
            id=graph_id,
            workbook_version_id=catalog.workbook_version_id,
            compiler_manifest_hash=compiler_manifest_hash,
            content_fingerprint=content_fingerprint,
            node_count=len(formula_refs),
            edge_count=base_plan.edge_count,
            components=components,
            topological_layers=layers,
            base_plan=base_plan,
        )


class DirtyPropagator:
    def plan(
        self,
        graph: CalculationGraphVersion,
        *,
        changed_cells: Iterable[WorkbookCellRef],
        has_compatible_prior_run: bool,
    ) -> DirtyPropagationPlan:
        changed = tuple(sorted(set(changed_cells), key=_cell_sort_key))
        ready = {
            reference
            for reference, status in graph.base_plan.status_by_cell.items()
            if status == "ready"
        }
        if not has_compatible_prior_run:
            return DirtyPropagationPlan(
                changed_cells=changed,
                dirty_formula_cells=tuple(sorted(ready, key=_cell_sort_key)),
                reusable_formula_cells=(),
            )

        dirty: set[WorkbookCellRef] = set()
        visited = set(changed)
        queue = list(changed)
        while queue:
            precedent = queue.pop(0)
            if precedent in ready:
                dirty.add(precedent)
            for dependent in graph.base_plan.dependents_by_cell.get(precedent, ()):
                if dependent in visited:
                    continue
                visited.add(dependent)
                queue.append(dependent)
                if dependent in ready:
                    dirty.add(dependent)
        reusable = ready - dirty
        return DirtyPropagationPlan(
            changed_cells=changed,
            dirty_formula_cells=tuple(sorted(dirty, key=_cell_sort_key)),
            reusable_formula_cells=tuple(sorted(reusable, key=_cell_sort_key)),
        )


def _components(
    graph_id: str,
    formula_refs: Sequence[WorkbookCellRef],
    base_plan: CalculationGraphPlan,
    layer_by_cell: Mapping[WorkbookCellRef, int],
) -> tuple[CalculationGraphComponent, ...]:
    cycle_by_member = {
        member: cycle
        for cycle in base_plan.cycles
        for member in cycle
    }
    partitions: list[tuple[str, tuple[WorkbookCellRef, ...], int | None]] = []
    emitted_cycles: set[tuple[WorkbookCellRef, ...]] = set()
    for reference in formula_refs:
        cycle = cycle_by_member.get(reference)
        if cycle is not None:
            if cycle in emitted_cycles:
                continue
            emitted_cycles.add(cycle)
            classification = "self_reference" if len(cycle) == 1 else "multi_cell_cycle"
            partitions.append((classification, cycle, None))
            continue
        status = base_plan.status_by_cell[reference]
        classification = (
            "acyclic_singleton" if status == "ready" else "blocked_unsupported"
        )
        partitions.append((classification, (reference,), layer_by_cell.get(reference)))

    partitions.sort(key=lambda item: _cell_sort_key(item[1][0]))
    components: list[CalculationGraphComponent] = []
    for ordinal, (classification, members, layer) in enumerate(partitions):
        identity = {
            "classification": classification,
            "members": [_ref_payload(item) for item in members],
        }
        component_id = str(
            uuid.uuid5(uuid.UUID(graph_id), _canonical_json(identity))
        )
        components.append(
            CalculationGraphComponent(
                id=component_id,
                ordinal=ordinal,
                classification=classification,
                members=tuple(sorted(members, key=_cell_sort_key)),
                topological_layer=layer,
            )
        )
    return tuple(components)


def _topological_layers(
    base_plan: CalculationGraphPlan,
) -> tuple[tuple[WorkbookCellRef, ...], ...]:
    ready = {
        reference
        for reference, status in base_plan.status_by_cell.items()
        if status == "ready"
    }
    layer_by_cell: dict[WorkbookCellRef, int] = {}
    for reference in base_plan.evaluation_order:
        formula_precedents = [
            precedent
            for precedent in base_plan.precedents_by_formula.get(reference, ())
            if precedent in ready
        ]
        layer_by_cell[reference] = (
            max(layer_by_cell[precedent] for precedent in formula_precedents) + 1
            if formula_precedents
            else 0
        )
    if set(layer_by_cell) != ready:
        raise ValueError("Ready graph nodes do not have a complete layer assignment")
    if not layer_by_cell:
        return ()
    return tuple(
        tuple(
            sorted(
                (
                    reference
                    for reference, assigned in layer_by_cell.items()
                    if assigned == layer
                ),
                key=_cell_sort_key,
            )
        )
        for layer in range(max(layer_by_cell.values()) + 1)
    )


def _cell_sort_key(reference: WorkbookCellRef) -> tuple[int, int, int]:
    row, column = coordinate_to_tuple(reference.cell_address)
    return reference.sheet_position, row, column


def _ref_payload(reference: WorkbookCellRef) -> list[object]:
    return [
        reference.sheet_position,
        reference.sheet_name,
        reference.cell_address,
    ]


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
