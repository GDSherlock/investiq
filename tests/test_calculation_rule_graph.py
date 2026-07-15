from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
import pytest

from apps.api.app.calculation_rules.compiler import FormulaCompiler
from apps.api.app.calculation_rules.graph import (
    CalculationGraphBuilder,
    _tarjan_cycles,
)
from apps.api.app.calculation_rules.inventory import WorkbookFormulaInventory
from apps.api.app.calculation_rules.types import (
    CalculationRuleExtractionConfiguration,
    WorkbookCellRef,
)


WORKBOOK_VERSION_ID = "32345678-1234-5678-9234-567812345678"


def _graph_case(*, configuration=None):
    configuration = configuration or CalculationRuleExtractionConfiguration()
    workbook = Workbook()
    inputs = workbook.active
    inputs.title = "Inputs"
    inputs["A1"] = 2
    inputs["A2"] = 3
    calc = workbook.create_sheet("Calc")
    calc["B1"] = "=SUM(Inputs!A1:A2)"
    calc["B2"] = "=B1*2"
    calc["B3"] = "=B4+1"
    calc["B4"] = "=B3+1"
    calc["B5"] = '=COUNTIF(Inputs!A1:A2,">0")'
    calc["B6"] = "=B5+1"
    calc["B7"] = "=Inputs!A1+1"
    calc["B8"] = "=B8+1"
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    catalog = WorkbookFormulaInventory(configuration).scan(
        buffer.getvalue(), WORKBOOK_VERSION_ID
    )
    compiler = FormulaCompiler(configuration)
    compilations = tuple(compiler.compile(cell, catalog) for cell in catalog.formulas)
    return catalog, compilations, CalculationGraphBuilder(configuration).build(
        catalog, compilations
    )


def _by_address(catalog):
    return {formula.ref.cell_address: formula.ref for formula in catalog.formulas}


def test_graph_expands_ranges_and_orders_precedents_before_dependents() -> None:
    catalog, _compilations, plan = _graph_case()
    refs = _by_address(catalog)

    b1_precedents = plan.precedents_by_formula[refs["B1"]]
    assert [reference.display for reference in b1_precedents] == [
        "Inputs!A1",
        "Inputs!A2",
    ]
    # Unsupported B5 retains its reference evidence but contributes no trusted
    # executable graph edges. B6 still has an edge to the unsupported B5 cell.
    assert plan.edge_count == 8
    assert plan.evaluation_order.index(refs["B1"]) < plan.evaluation_order.index(
        refs["B2"]
    )
    assert plan.status_by_cell[refs["B1"]] == "ready"
    assert plan.status_by_cell[refs["B2"]] == "ready"
    assert plan.status_by_cell[refs["B7"]] == "ready"


def test_graph_detects_self_and_multi_cell_cycles_deterministically() -> None:
    catalog, _compilations, plan = _graph_case()
    refs = _by_address(catalog)

    assert plan.cycles == (
        (refs["B3"], refs["B4"]),
        (refs["B8"],),
    )
    assert plan.status_by_cell[refs["B3"]] == "cycle"
    assert plan.status_by_cell[refs["B4"]] == "cycle"
    assert plan.status_by_cell[refs["B8"]] == "cycle"
    assert refs["B3"] not in plan.evaluation_order


def test_unsupported_precedent_blocks_dependents_but_not_independent_subgraphs() -> None:
    catalog, _compilations, plan = _graph_case()
    refs = _by_address(catalog)

    assert plan.status_by_cell[refs["B5"]] == "not_executable"
    assert plan.status_by_cell[refs["B6"]] == "blocked_by_dependency"
    assert refs["B7"] in plan.evaluation_order
    assert refs["B1"] in plan.evaluation_order
    assert refs["B2"] in plan.evaluation_order


def test_graph_order_is_retry_stable() -> None:
    first_catalog, _first_compilations, first = _graph_case()
    second_catalog, _second_compilations, second = _graph_case()

    assert [ref.display for ref in first.evaluation_order] == [
        ref.display for ref in second.evaluation_order
    ]
    assert [ref.display for ref in first_catalog.formula_by_ref()] == [
        ref.display for ref in second_catalog.formula_by_ref()
    ]


def test_total_edge_budget_is_enforced_without_truncation() -> None:
    configuration = CalculationRuleExtractionConfiguration(max_total_edges=7)

    with pytest.raises(ValueError, match="dependency edge limit"):
        _graph_case(configuration=configuration)


def test_scc_detection_handles_long_valid_graphs_without_python_recursion() -> None:
    references = tuple(
        WorkbookCellRef(WORKBOOK_VERSION_ID, "Calc", 0, f"A{row}")
        for row in range(1, 1_501)
    )
    dependencies = {
        reference: (
            () if index == len(references) - 1 else (references[index + 1],)
        )
        for index, reference in enumerate(references)
    }

    assert _tarjan_cycles(dependencies) == ()
