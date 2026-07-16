from __future__ import annotations

from io import BytesIO
import uuid

from openpyxl import Workbook

from apps.api.app.calculation_rules.compiler import FormulaCompiler
from apps.api.app.calculation_rules.inventory import WorkbookFormulaInventory
from apps.api.app.calculation_rules.phase2_registry import PHASE2_FUNCTION_REGISTRY
from apps.api.app.calculation_rules.phase2_types import Phase2CalculationConfiguration


def _grouping_fixture(*, divergent: bool = False):
    from apps.api.app.calculation_rules.phase2_grouping import BusinessRuleGrouper

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Forecast"
    for column, volume, price in (("C", 2, 10), ("D", 3, 10), ("E", 4, 10)):
        sheet[f"{column}5"] = volume
        sheet[f"{column}6"] = price
        sheet[f"{column}10"] = f"={column}5*{column}6"
    if divergent:
        sheet["E10"] = "=E5+E6"
    sheet["F10"] = 999
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()

    configuration = Phase2CalculationConfiguration()
    catalog = WorkbookFormulaInventory(configuration).scan(
        buffer.getvalue(),
        str(uuid.uuid4()),
    )
    compilations = tuple(
        FormulaCompiler(
            configuration,
            function_registry=PHASE2_FUNCTION_REGISTRY,
        ).compile(cell, catalog)
        for cell in catalog.formulas
    )
    model_version_id = str(uuid.uuid4())
    groups = BusinessRuleGrouper(configuration).group(
        model_version_id,
        catalog,
        compilations,
    )
    return model_version_id, catalog, compilations, groups


def test_grouping_combines_contiguous_period_formulas_without_losing_members() -> None:
    _model_id, _catalog, _compilations, groups = _grouping_fixture()

    assert len(groups) == 1
    group = groups[0]
    assert [member.cell_address for member in group.members] == [
        "C10",
        "D10",
        "E10",
    ]
    assert len({member.formula_cell_id for member in group.members}) == 3
    assert [member.period_offset for member in group.members] == [0, 1, 2]
    assert group.orientation == "horizontal"
    assert group.approval_status == "unreviewed"
    assert group.label == "Copied formula: Forecast!C10:E10"


def test_grouping_records_hardcode_break_and_identity_is_retry_stable() -> None:
    model_id, catalog, compilations, first_groups = _grouping_fixture()
    from apps.api.app.calculation_rules.phase2_grouping import BusinessRuleGrouper

    second_groups = BusinessRuleGrouper(
        Phase2CalculationConfiguration()
    ).group(model_id, catalog, compilations)

    assert first_groups[0].id == second_groups[0].id
    assert first_groups[0].group_fingerprint == second_groups[0].group_fingerprint
    assert first_groups[0].exceptions == (
        {
            "sheet_name": "Forecast",
            "cell_address": "F10",
            "reason": "hardcode_break",
        },
    )


def test_divergent_formula_is_not_silently_added_to_group() -> None:
    _model_id, _catalog, _compilations, groups = _grouping_fixture(divergent=True)

    assert len(groups) == 1
    assert [member.cell_address for member in groups[0].members] == ["C10", "D10"]
    assert groups[0].exceptions == (
        {
            "sheet_name": "Forecast",
            "cell_address": "E10",
            "reason": "formula_break",
        },
    )
