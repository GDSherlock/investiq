from __future__ import annotations

import uuid

from apps.api.app.calculation_rules.compiler import FormulaCompiler
from apps.api.app.calculation_rules.graph import CalculationGraphBuilder
from apps.api.app.calculation_rules.inventory import WorkbookFormulaInventory
from apps.api.app.calculation_rules.phase2_registry import PHASE2_FUNCTION_REGISTRY
from apps.api.app.calculation_rules.phase2_types import Phase2CalculationConfiguration
from apps.api.app.calculation_rules.types import WorkbookCellRef
from tests.calculation_rule_test_support import calculation_workbook_bytes


def _versioned_graph():
    from apps.api.app.calculation_rules.phase2_graph import (
        VersionedCalculationGraphBuilder,
    )

    configuration = Phase2CalculationConfiguration()
    catalog = WorkbookFormulaInventory(configuration).scan(
        calculation_workbook_bytes(),
        str(uuid.uuid4()),
    )
    compiler = FormulaCompiler(
        configuration,
        function_registry=PHASE2_FUNCTION_REGISTRY,
    )
    compilations = tuple(compiler.compile(cell, catalog) for cell in catalog.formulas)
    base_plan = CalculationGraphBuilder(configuration).build(catalog, compilations)
    version = VersionedCalculationGraphBuilder(configuration).build(
        catalog,
        compilations,
        base_plan,
    )
    return catalog, compilations, base_plan, version


def _cell(catalog, sheet_name: str, address: str) -> WorkbookCellRef:
    position = catalog.sheet_position(sheet_name)
    assert position is not None
    return WorkbookCellRef(
        catalog.workbook_version_id,
        sheet_name,
        position,
        address,
    )


def test_graph_version_classifies_every_scc_and_is_retry_stable() -> None:
    catalog, compilations, base_plan, first = _versioned_graph()
    from apps.api.app.calculation_rules.phase2_graph import (
        VersionedCalculationGraphBuilder,
    )

    second = VersionedCalculationGraphBuilder(
        Phase2CalculationConfiguration()
    ).build(catalog, compilations, base_plan)

    assert first.id == second.id
    assert first.content_fingerprint == second.content_fingerprint
    assert first.compiler_manifest_hash == second.compiler_manifest_hash
    assert first.node_count == len(catalog.formulas) == 10
    assert sum(len(item.members) for item in first.components) == 10
    assert {item.classification for item in first.components} >= {
        "acyclic_singleton",
        "multi_cell_cycle",
        "blocked_unsupported",
    }
    cycle = next(
        item for item in first.components if item.classification == "multi_cell_cycle"
    )
    assert [member.display for member in cycle.members] == ["Calc!B5", "Calc!B6"]


def test_graph_layers_are_precedent_first_and_deterministic() -> None:
    catalog, _compilations, _base_plan, graph = _versioned_graph()
    layer_by_cell = {
        member.display: layer
        for layer, members in enumerate(graph.topological_layers)
        for member in members
    }

    assert layer_by_cell["Calc!B1"] < layer_by_cell["Calc!B2"]
    assert layer_by_cell["Calc!B2"] < layer_by_cell["Calc!B8"]
    assert layer_by_cell["Hidden!C1"] < layer_by_cell["Very Hidden!D1"]
    assert _cell(catalog, "Calc", "B5") not in {
        member for layer in graph.topological_layers for member in layer
    }


def test_dirty_propagation_recalculates_only_transitive_dependents() -> None:
    from apps.api.app.calculation_rules.phase2_graph import DirtyPropagator

    catalog, _compilations, _base_plan, graph = _versioned_graph()
    plan = DirtyPropagator().plan(
        graph,
        changed_cells={_cell(catalog, "Inputs", "A1")},
        has_compatible_prior_run=True,
    )

    assert {item.display for item in plan.dirty_formula_cells} == {
        "Calc!B1",
        "Calc!B2",
        "Calc!B3",
        "Calc!B4",
        "Calc!B8",
    }
    assert {item.display for item in plan.reusable_formula_cells} == {
        "Hidden!C1",
        "Very Hidden!D1",
    }


def test_cold_run_marks_every_ready_formula_dirty() -> None:
    from apps.api.app.calculation_rules.phase2_graph import DirtyPropagator

    _catalog, _compilations, _base_plan, graph = _versioned_graph()
    plan = DirtyPropagator().plan(
        graph,
        changed_cells=set(),
        has_compatible_prior_run=False,
    )

    assert len(plan.dirty_formula_cells) == 7
    assert plan.reusable_formula_cells == ()


def test_compatible_no_change_run_reuses_every_ready_formula() -> None:
    from apps.api.app.calculation_rules.phase2_graph import DirtyPropagator

    _catalog, _compilations, _base_plan, graph = _versioned_graph()
    plan = DirtyPropagator().plan(
        graph,
        changed_cells=set(),
        has_compatible_prior_run=True,
    )

    assert plan.dirty_formula_cells == ()
    assert len(plan.reusable_formula_cells) == 7
