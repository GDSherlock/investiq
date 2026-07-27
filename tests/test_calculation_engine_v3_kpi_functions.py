from __future__ import annotations

from collections import Counter
from io import BytesIO
from pathlib import Path
import uuid

from openpyxl import Workbook
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
):
    workbook = Workbook()
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
            SafeCalculationEvaluator(
                function_registry=PHASE2_FUNCTION_REGISTRY,
            )
            .execute(
                graph,
                catalog,
                (compilation,),
                configuration,
            )
            .values()
        )
    )
    return compilation, execution


def _compile_and_evaluate_workbook(relative_path: str):
    workbook_path = Path(__file__).parents[1] / relative_path
    configuration = Phase2CalculationConfiguration()
    catalog = WorkbookFormulaInventory(configuration).scan(
        workbook_path.read_bytes(),
        str(uuid.uuid4()),
    )
    compilations = tuple(
        FormulaCompiler(
            configuration,
            function_registry=PHASE2_FUNCTION_REGISTRY,
        ).compile(formula, catalog)
        for formula in catalog.formulas
    )
    graph = CalculationGraphBuilder(configuration).build(catalog, compilations)
    executions = SafeCalculationEvaluator(
        function_registry=PHASE2_FUNCTION_REGISTRY,
    ).execute(
        graph,
        catalog,
        compilations,
        configuration,
    )
    return catalog, compilations, executions


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=IFERROR(7,1/0)", ScalarValue.number(7)),
        ("=IFERROR(1/0,9)", ScalarValue.number(9)),
        ("=IFERROR(#N/A,11)", ScalarValue.number(11)),
    ],
)
def test_iferror_evaluates_only_the_selected_branch(
    formula: str,
    expected: ScalarValue,
) -> None:
    _compilation, execution = _compile_and_evaluate(formula)

    assert execution is not None
    assert execution.status == "executed"
    assert execution.value == expected


def test_and_flattens_logical_ranges_and_propagates_typed_errors() -> None:
    _compilation, truthy = _compile_and_evaluate(
        "=AND(TRUE,Inputs!A1:A3)",
        {"A1": True, "A2": "ignored", "A3": None},
    )
    _compilation, falsey = _compile_and_evaluate("=AND(TRUE,FALSE)")
    _compilation, errored = _compile_and_evaluate("=AND(TRUE,#N/A)")
    _compilation, no_logicals = _compile_and_evaluate(
        "=AND(Inputs!A1:A2)",
        {"A1": "ignored", "A2": None},
    )

    assert truthy is not None and truthy.value == ScalarValue.boolean(True)
    assert falsey is not None and falsey.value == ScalarValue.boolean(False)
    assert errored is not None and errored.value == ScalarValue.error("#N/A")
    assert no_logicals is not None
    assert no_logicals.value == ScalarValue.error("#VALUE!")


def test_minifs_supports_comparison_pairs_and_excel_shape_rules() -> None:
    values = {
        "A1": 0,
        "A2": 1.3,
        "A3": 1.2,
        "A4": 1.4,
        "B1": "x",
        "B2": "x",
        "B3": "y",
        "B4": "x",
        "C1": 0,
        "C2": 1,
        "C3": 1,
        "C4": 0,
    }
    _compilation, matched = _compile_and_evaluate(
        '=MINIFS(Inputs!A1:A4,Inputs!B1:B4,"x",Inputs!C1:C4,">0")',
        values,
    )
    _compilation, no_match = _compile_and_evaluate(
        '=MINIFS(Inputs!A1:A4,Inputs!A1:A4,">5")',
        values,
    )
    _compilation, mismatched = _compile_and_evaluate(
        '=MINIFS(Inputs!A1:A4,Inputs!B1:B3,"x")',
        values,
    )
    _compilation, wildcard = _compile_and_evaluate(
        '=MINIFS(Inputs!A1:A4,Inputs!B1:B4,"x*")',
        values,
    )

    assert matched is not None and matched.value == ScalarValue.number(1.3)
    assert no_match is not None and no_match.value == ScalarValue.number(0)
    assert mismatched is not None
    assert mismatched.value == ScalarValue.error("#VALUE!")
    assert wildcard is not None
    assert wildcard.value == ScalarValue.error("#VALUE!")


def test_minifs_rejects_an_unpaired_criteria_argument_at_compile_time() -> None:
    compilation, execution = _compile_and_evaluate(
        '=MINIFS(Inputs!A1:A2,Inputs!A1:A2,">0",Inputs!A1:A2)',
        {"A1": 1, "A2": 2},
    )

    assert execution is None
    assert compilation.support_status == "unsupported"
    assert compilation.unsupported_constructs == ("invalid_arity:MINIFS",)


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        (
            "=SUM(Inputs!A1:A2+Inputs!B1:B2)",
            ScalarValue.number(10),
        ),
        (
            "=SUM(Inputs!A1:A2-Inputs!B1:B2)",
            ScalarValue.number(-4),
        ),
    ],
)
def test_equal_one_dimensional_ranges_support_pairwise_addition_and_subtraction(
    formula: str,
    expected: ScalarValue,
) -> None:
    _compilation, execution = _compile_and_evaluate(
        formula,
        {"A1": 1, "A2": 2, "B1": 3, "B2": 4},
    )

    assert execution is not None
    assert execution.value == expected


@pytest.mark.parametrize(
    "formula",
    [
        "=SUM(Inputs!A1:A2+Inputs!B1:B3)",
        "=SUM(Inputs!A1:B2+Inputs!C1:D2)",
        "=SUM(Inputs!A1:A2*Inputs!B1:B2)",
        "=Inputs!A1:A2+Inputs!B1:B2",
    ],
)
def test_range_arithmetic_rejects_unapproved_shapes_and_operators(
    formula: str,
) -> None:
    _compilation, execution = _compile_and_evaluate(
        formula,
        {
            "A1": 1,
            "A2": 2,
            "B1": 3,
            "B2": 4,
            "B3": 5,
            "C1": 6,
            "C2": 7,
            "D1": 8,
            "D2": 9,
        },
    )

    assert execution is not None
    assert execution.status == "execution_error"
    assert execution.value == ScalarValue.error("#VALUE!")


@pytest.mark.parametrize(
    ("formula", "values", "expected"),
    [
        (
            "=IRR(Inputs!A1:A2)",
            {"A1": -100, "A2": 110},
            0.1,
        ),
        (
            "=IRR(Inputs!A1:A3,25%)",
            {"A1": -100, "A2": 230, "A3": -132},
            0.2,
        ),
        (
            "=IRR(Inputs!A1:A5)",
            {"A1": -100, "A2": "ignored", "A3": True, "A4": None, "A5": 110},
            0.1,
        ),
    ],
)
def test_irr_uses_deterministic_excel_periodic_cash_flow_semantics(
    formula: str,
    values: dict[str, object],
    expected: float,
) -> None:
    _compilation, execution = _compile_and_evaluate(formula, values)

    assert execution is not None
    assert execution.status == "executed"
    assert execution.value is not None
    assert execution.value.number_value == pytest.approx(expected, abs=1e-7)


@pytest.mark.parametrize(
    ("formula", "values"),
    [
        ("=IRR(Inputs!A1:A2)", {"A1": 100, "A2": 110}),
        ("=IRR(Inputs!A1:A2)", {"A1": -100, "A2": -10}),
        ("=IRR(Inputs!A1:A2)", {"A1": -100, "A2": "ignored"}),
    ],
)
def test_irr_returns_num_for_no_root_or_insufficient_numeric_values(
    formula: str,
    values: dict[str, object],
) -> None:
    _compilation, execution = _compile_and_evaluate(formula, values)

    assert execution is not None
    assert execution.status == "execution_error"
    assert execution.error_code == "#NUM!"
    assert execution.value == ScalarValue.error("#NUM!")


def test_npv_discounts_first_function_value_at_period_one() -> None:
    _compilation, npv = _compile_and_evaluate(
        "=NPV(10%,Inputs!A1:A2)",
        {"A1": 60, "A2": 60},
    )
    _compilation, with_initial = _compile_and_evaluate(
        "=-100+NPV(10%,Inputs!A1:A2)",
        {"A1": 60, "A2": 60},
    )
    _compilation, ignored = _compile_and_evaluate(
        "=NPV(10%,Inputs!A1:A5)",
        {"A1": 60, "A2": "ignored", "A3": True, "A4": None, "A5": 60},
    )

    assert npv is not None and npv.value is not None
    assert npv.value.number_value == pytest.approx(104.13223140495867)
    assert with_initial is not None and with_initial.value is not None
    assert with_initial.value.number_value == pytest.approx(4.13223140495867)
    assert ignored is not None and ignored.value == npv.value


def test_npv_returns_division_error_for_minus_one_rate() -> None:
    _compilation, execution = _compile_and_evaluate(
        "=NPV(-100%,Inputs!A1:A2)",
        {"A1": 60, "A2": 60},
    )

    assert execution is not None
    assert execution.status == "execution_error"
    assert execution.value == ScalarValue.error("#DIV/0!")


@pytest.mark.parametrize(
    ("relative_path", "formula_count", "execution_counts"),
    [
        (
            "tests/fixtures/calculation_rules/01_solar_pv_project_finance.xlsx",
            735,
            {"executed": 733, "execution_error": 2},
        ),
        (
            "tests/fixtures/calculation_rules/06_battery_storage_revenue_stack.xlsx",
            489,
            {"executed": 479, "execution_error": 10},
        ),
    ],
)
def test_kpi_formula_pack_eliminates_workbook_unsupported_and_dependency_blocks(
    relative_path: str,
    formula_count: int,
    execution_counts: dict[str, int],
) -> None:
    _catalog, compilations, executions = _compile_and_evaluate_workbook(relative_path)

    assert len(compilations) == formula_count
    assert {item.support_status for item in compilations} == {"supported"}
    assert Counter(item.status for item in executions.values()) == execution_counts


def test_solar_minimum_dscr_executes_and_irr_failures_are_typed_math_errors() -> None:
    catalog, _compilations, executions = _compile_and_evaluate_workbook(
        "tests/fixtures/calculation_rules/01_solar_pv_project_finance.xlsx"
    )
    formula_by_ref = catalog.formula_by_ref()
    execution_by_formula = {
        formula_by_ref[reference].exact_formula: execution
        for reference, execution in executions.items()
    }

    assert execution_by_formula[
        '=MINIFS(\'Cash Flow\'!B11:AB11,\'Cash Flow\'!B11:AB11,">0")'
    ].status == "executed"
    for formula in (
        "=IRR('Cash Flow'!B6:AB6+'Cash Flow'!B8:AB8)",
        "=IRR('Cash Flow'!B10:AB10)",
    ):
        execution = execution_by_formula[formula]
        assert execution.status == "execution_error"
        assert execution.value == ScalarValue.error("#NUM!")


def test_battery_iferror_minifs_and_range_irr_reach_runtime_semantics() -> None:
    catalog, compilations, executions = _compile_and_evaluate_workbook(
        "tests/fixtures/calculation_rules/06_battery_storage_revenue_stack.xlsx"
    )
    compilation_by_id = {item.formula_cell_id: item for item in compilations}
    formula_by_ref = catalog.formula_by_ref()
    selected = {
        formula.exact_formula: (
            compilation_by_id[formula.id],
            executions[reference],
        )
        for reference, formula in formula_by_ref.items()
        if any(
            function in formula.exact_formula
            for function in ("IFERROR(", "MINIFS(", "IRR(")
        )
    }

    assert len(selected) == 25
    assert all(compilation.support_status == "supported" for compilation, _ in selected.values())
    assert selected[
        '=MINIFS(\'Funding\'!B18:W18,\'Funding\'!B18:W18,">0")'
    ][1].value.number_value == pytest.approx(1.3)
    assert selected[
        "=IRR('Funding'!B14:W14-'Funding'!B15:W15)"
    ][0].ir_json["capabilities"] == ["financial", "range-arithmetic"]
