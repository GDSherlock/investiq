from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import uuid

from openpyxl import Workbook, load_workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904
import pytest

from apps.api.app.calculation_rules.compiler import FormulaCompiler
from apps.api.app.calculation_rules.evaluator import SafeCalculationEvaluator, ScalarValue
from apps.api.app.calculation_rules.graph import CalculationGraphBuilder
from apps.api.app.calculation_rules.inventory import WorkbookFormulaInventory
from apps.api.app.calculation_rules.phase2_registry import PHASE2_FUNCTION_REGISTRY
from apps.api.app.calculation_rules.phase2_types import Phase2CalculationConfiguration


def _compile_and_evaluate(
    formula: str,
    values: dict[str, object] | None = None,
    *,
    date_system: str = "1900",
):
    workbook = Workbook()
    if date_system == "1904":
        workbook.epoch = CALENDAR_MAC_1904
    inputs = workbook.active
    inputs.title = "Inputs"
    for address, value in (values or {}).items():
        inputs[address] = value
    calc = workbook.create_sheet("Calc")
    calc["A1"] = formula
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()

    configuration = Phase2CalculationConfiguration()
    catalog = WorkbookFormulaInventory(configuration).scan(
        buffer.getvalue(),
        str(uuid.uuid4()),
    )
    compilation = FormulaCompiler(
        configuration,
        function_registry=PHASE2_FUNCTION_REGISTRY,
    ).compile(catalog.formulas[0], catalog)
    if compilation.ir_json is None:
        return compilation, None
    graph = CalculationGraphBuilder(configuration).build(catalog, (compilation,))
    execution = next(
        iter(
            SafeCalculationEvaluator(function_registry=PHASE2_FUNCTION_REGISTRY)
            .execute(graph, catalog, (compilation,), configuration)
            .values()
        )
    )
    return compilation, execution


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=MOD(3,2)", 1),
        ("=MOD(-3,2)", 1),
        ("=MOD(3,-2)", -1),
        ("=MOD(-3,-2)", -1),
    ],
)
def test_mod_uses_the_divisor_sign(formula: str, expected: float) -> None:
    compilation, execution = _compile_and_evaluate(formula)

    assert compilation.support_status == "supported"
    assert execution is not None
    assert execution.value == ScalarValue.number(expected)


def test_mod_returns_division_error_for_zero_divisor() -> None:
    _compilation, execution = _compile_and_evaluate("=MOD(7,0)")

    assert execution is not None
    assert execution.value == ScalarValue.error("#DIV/0!")
