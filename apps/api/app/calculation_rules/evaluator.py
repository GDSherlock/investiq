"""Safe evaluation of validated `calc-ir-v1` nodes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
from typing import Any, Mapping, Sequence

from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
from openpyxl.utils.datetime import (
    CALENDAR_MAC_1904,
    CALENDAR_WINDOWS_1900,
    to_excel,
)

from .compiler import CalculationExpressionValidator
from .function_registry import FUNCTION_REGISTRY
from .graph import CalculationGraphPlan
from .types import (
    CalculationRuleExtractionConfiguration,
    FormulaCompilation,
    WorkbookCatalog,
    WorkbookCellFact,
    WorkbookCellRef,
    WorkbookFormulaCell,
)


_ERROR_CODES = {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A"}


@dataclass(frozen=True)
class ScalarValue:
    kind: str
    value: Any = None
    error_code: str | None = None
    iso_evidence: str | None = None

    @classmethod
    def number(cls, value: int | float) -> "ScalarValue":
        number = float(value)
        if not math.isfinite(number):
            return cls.error("#NUM!")
        return cls("number", number)

    @classmethod
    def boolean(cls, value: bool) -> "ScalarValue":
        return cls("boolean", bool(value))

    @classmethod
    def text(cls, value: str) -> "ScalarValue":
        return cls("text", str(value))

    @classmethod
    def blank(cls) -> "ScalarValue":
        return cls("blank")

    @classmethod
    def date_serial(cls, value: float, iso_evidence: str | None = None) -> "ScalarValue":
        if not math.isfinite(value):
            return cls.error("#NUM!")
        return cls("date_serial", float(value), iso_evidence=iso_evidence)

    @classmethod
    def error(cls, code: str) -> "ScalarValue":
        if code not in _ERROR_CODES:
            raise ValueError(f"Unknown Excel error code: {code}")
        return cls("error", error_code=code)

    @property
    def number_value(self) -> float:
        if self.kind not in {"number", "date_serial"}:
            raise TypeError("Scalar value is not numeric")
        return float(self.value)

    def to_json(self) -> dict[str, Any]:
        if self.kind == "error":
            return {"value_type": "error", "error_code": self.error_code}
        if self.kind in {"number", "date_serial"}:
            payload: dict[str, Any] = {
                "value_type": self.kind,
                "value": format(float(self.value), ".17g"),
            }
            if self.iso_evidence is not None:
                payload["iso_evidence"] = self.iso_evidence
            return payload
        return {"value_type": self.kind, "value": self.value}

    @classmethod
    def from_json(cls, payload: dict[str, Any] | None) -> "ScalarValue | None":
        if payload is None:
            return None
        kind = payload.get("value_type")
        if kind == "error":
            return cls.error(payload["error_code"])
        if kind == "number":
            return cls.number(float(payload["value"]))
        if kind == "date_serial":
            return cls.date_serial(
                float(payload["value"]),
                payload.get("iso_evidence"),
            )
        if kind == "boolean":
            return cls.boolean(bool(payload["value"]))
        if kind == "text":
            return cls.text(str(payload["value"]))
        if kind == "blank":
            return cls.blank()
        raise ValueError(f"Unknown persisted scalar value type: {kind}")


@dataclass(frozen=True)
class FormulaExecution:
    status: str
    value: ScalarValue | None
    error_code: str | None
    direct_input_trace: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...] = ()


@dataclass
class CalculationExecutionContext:
    catalog: WorkbookCatalog
    formula_cell: WorkbookFormulaCell
    compilation: FormulaCompilation
    calculated_values: Mapping[WorkbookCellRef, ScalarValue]
    configuration: CalculationRuleExtractionConfiguration


@dataclass(frozen=True)
class _RangeValue:
    values: tuple[ScalarValue, ...]


class SafeCalculationEvaluator:
    def __init__(self):
        self._validator = CalculationExpressionValidator()

    def evaluate(
        self,
        expression: dict[str, Any],
        context: CalculationExecutionContext,
    ) -> FormulaExecution:
        self._validator.validate(
            expression,
            context.formula_cell,
            context.compilation.references,
            context.configuration,
        )
        trace: list[dict[str, Any]] = []
        value = self._evaluate_node(expression["root"], context, trace)
        if isinstance(value, _RangeValue):
            value = ScalarValue.error("#VALUE!")
        status = "execution_error" if value.kind == "error" else "executed"
        return FormulaExecution(
            status=status,
            value=value,
            error_code=value.error_code if value.kind == "error" else None,
            direct_input_trace=tuple(trace),
        )

    def execute(
        self,
        plan: CalculationGraphPlan,
        catalog: WorkbookCatalog,
        compilations: Sequence[FormulaCompilation],
        configuration: CalculationRuleExtractionConfiguration | None = None,
    ) -> dict[WorkbookCellRef, FormulaExecution]:
        configuration = configuration or CalculationRuleExtractionConfiguration()
        formula_by_ref = catalog.formula_by_ref()
        compilation_by_formula_id = {
            compilation.formula_cell_id: compilation for compilation in compilations
        }
        results: dict[WorkbookCellRef, FormulaExecution] = {}
        calculated: dict[WorkbookCellRef, ScalarValue] = {}
        for reference, status in plan.status_by_cell.items():
            if status == "ready":
                continue
            results[reference] = FormulaExecution(
                status=status,
                value=None,
                error_code=None,
                direct_input_trace=(),
                warnings=(status,),
            )
        for reference in plan.evaluation_order:
            formula_cell = formula_by_ref[reference]
            compilation = compilation_by_formula_id[formula_cell.id]
            if compilation.ir_json is None:
                raise ValueError("Executable graph references a formula without validated IR")
            context = CalculationExecutionContext(
                catalog=catalog,
                formula_cell=formula_cell,
                compilation=compilation,
                calculated_values=calculated,
                configuration=configuration,
            )
            execution = self.evaluate(compilation.ir_json, context)
            results[reference] = execution
            if execution.value is not None:
                calculated[reference] = execution.value
        return results

    def _evaluate_node(
        self,
        node: dict[str, Any],
        context: CalculationExecutionContext,
        trace: list[dict[str, Any]],
    ) -> ScalarValue | _RangeValue:
        node_type = node["node_type"]
        if node_type == "literal":
            literal_type = node["literal_type"]
            if literal_type == "number":
                return ScalarValue.number(float(node["value"]))
            if literal_type == "boolean":
                return ScalarValue.boolean(node["value"])
            if literal_type == "text":
                return ScalarValue.text(node["value"])
            return ScalarValue.blank()
        if node_type == "error_value":
            return ScalarValue.error(node["error_code"])
        if node_type == "cell_reference":
            return self._cell_value(node["cell"], context, trace)
        if node_type == "range_reference":
            return self._range_value(node, context, trace)
        if node_type == "unary_operation":
            operand = self._evaluate_node(node["operand"], context, trace)
            number = _coerce_numeric(operand)
            if isinstance(number, ScalarValue):
                return number
            if node["operator"] == "negative":
                number = -number
            elif node["operator"] == "percent":
                number /= 100.0
            return _finite_number(number)
        if node_type == "binary_operation":
            left_value = self._evaluate_node(node["left"], context, trace)
            left = _coerce_numeric(left_value)
            if isinstance(left, ScalarValue):
                return left
            right_value = self._evaluate_node(node["right"], context, trace)
            right = _coerce_numeric(right_value)
            if isinstance(right, ScalarValue):
                return right
            operator = node["operator"]
            try:
                if operator == "add":
                    result = left + right
                elif operator == "subtract":
                    result = left - right
                elif operator == "multiply":
                    result = left * right
                elif operator == "divide":
                    if right == 0:
                        return ScalarValue.error("#DIV/0!")
                    result = left / right
                else:
                    result = left**right
            except (ArithmeticError, OverflowError, ValueError):
                return ScalarValue.error("#NUM!")
            if isinstance(result, complex):
                return ScalarValue.error("#NUM!")
            return _finite_number(result)
        if node_type == "comparison":
            left = self._evaluate_node(node["left"], context, trace)
            if isinstance(left, _RangeValue):
                return ScalarValue.error("#VALUE!")
            if left.kind == "error":
                return left
            right = self._evaluate_node(node["right"], context, trace)
            if isinstance(right, _RangeValue):
                return ScalarValue.error("#VALUE!")
            if right.kind == "error":
                return right
            return _compare(left, right, node["operator"])
        if node_type == "function_call":
            return self._function(node, context, trace)
        raise ValueError(f"Unknown calculation node type: {node_type}")

    def _function(
        self,
        node: dict[str, Any],
        context: CalculationExecutionContext,
        trace: list[dict[str, Any]],
    ) -> ScalarValue:
        name = node["function_name"]
        arguments = node["arguments"]
        definition = FUNCTION_REGISTRY.get(name)
        if definition is None:
            raise ValueError(f"Unregistered calculation function: {name}")
        if definition.lazy:
            if name != "IF":
                raise ValueError(f"Unsupported lazy calculation function: {name}")
            condition = self._evaluate_node(arguments[0], context, trace)
            truth = _truthy(condition)
            if isinstance(truth, ScalarValue):
                return truth
            selected = arguments[1] if truth else arguments[2] if len(arguments) == 3 else None
            if selected is None:
                return ScalarValue.boolean(False)
            value = self._evaluate_node(selected, context, trace)
            return value if isinstance(value, ScalarValue) else ScalarValue.error("#VALUE!")

        if name in {"SUM", "AVERAGE", "MIN", "MAX"}:
            numeric_values: list[float] = []
            for argument in arguments:
                value = self._evaluate_node(argument, context, trace)
                if isinstance(value, _RangeValue):
                    for item in value.values:
                        if item.kind == "error":
                            return item
                        if item.kind in {"number", "date_serial"}:
                            numeric_values.append(item.number_value)
                    continue
                number = _coerce_numeric(value)
                if isinstance(number, ScalarValue):
                    return number
                numeric_values.append(number)
            if name == "SUM":
                return _safe_fsum(numeric_values)
            if name == "AVERAGE":
                if not numeric_values:
                    return ScalarValue.error("#DIV/0!")
                total = _safe_fsum(numeric_values)
                if total.kind == "error":
                    return total
                return _finite_number(total.number_value / len(numeric_values))
            if not numeric_values:
                return ScalarValue.number(0)
            return _finite_number(
                min(numeric_values) if name == "MIN" else max(numeric_values)
            )

        first = self._evaluate_node(arguments[0], context, trace)
        first_number = _coerce_numeric(first)
        if isinstance(first_number, ScalarValue):
            return first_number
        if name == "ABS":
            return _finite_number(abs(first_number))
        if name == "ROUND":
            second = self._evaluate_node(arguments[1], context, trace)
            digits = _coerce_numeric(second)
            if isinstance(digits, ScalarValue):
                return digits
            try:
                quantum = Decimal(1).scaleb(-int(digits))
                rounded = Decimal(str(first_number)).quantize(
                    quantum,
                    rounding=ROUND_HALF_UP,
                )
            except (InvalidOperation, OverflowError, ValueError):
                return ScalarValue.error("#NUM!")
            return _finite_number(float(rounded))
        raise ValueError(f"Unregistered calculation function: {name}")

    def _cell_value(
        self,
        cell: dict[str, Any],
        context: CalculationExecutionContext,
        trace: list[dict[str, Any]],
    ) -> ScalarValue:
        reference = WorkbookCellRef(
            cell["workbook_version_id"],
            cell["sheet_name"],
            cell["sheet_position"],
            cell["cell_address"],
        )
        if reference in context.calculated_values:
            value = context.calculated_values[reference]
        else:
            fact = context.catalog.cell(reference)
            if fact.formula_kind is not None:
                value = ScalarValue.error("#REF!")
            else:
                value = _scalar_from_fact(fact, context.catalog.workbook_date_system)
        if len(trace) < context.configuration.max_trace_inputs:
            trace.append(
                {
                    "sheet_name": reference.sheet_name,
                    "sheet_position": reference.sheet_position,
                    "cell_address": reference.cell_address,
                    "value": value.to_json(),
                }
            )
        return value

    def _range_value(
        self,
        node: dict[str, Any],
        context: CalculationExecutionContext,
        trace: list[dict[str, Any]],
    ) -> _RangeValue:
        start = node["start_cell"]
        end = node["end_cell"]
        start_row, start_column = coordinate_to_tuple(start["cell_address"])
        end_row, end_column = coordinate_to_tuple(end["cell_address"])
        values: list[ScalarValue] = []
        for row in range(start_row, end_row + 1):
            for column in range(start_column, end_column + 1):
                cell = dict(start)
                cell["cell_address"] = f"{get_column_letter(column)}{row}"
                values.append(self._cell_value(cell, context, trace))
        return _RangeValue(tuple(values))


def _scalar_from_fact(fact: WorkbookCellFact, date_system: str) -> ScalarValue:
    return scalar_from_python(fact.value, fact.value_type, date_system)


def scalar_from_python(
    value: Any,
    value_type: str,
    date_system: str,
) -> ScalarValue:
    """Convert trusted workbook/cache data into the typed execution profile."""
    if value_type == "blank":
        return ScalarValue.blank()
    if value_type == "boolean":
        return ScalarValue.boolean(bool(value))
    if value_type == "number":
        return ScalarValue.number(value)
    if value_type == "text":
        return ScalarValue.text(str(value))
    if value_type == "error":
        code = str(value)
        return ScalarValue.error(code) if code in _ERROR_CODES else ScalarValue.error("#VALUE!")
    if value_type == "date" and isinstance(value, (date, datetime)):
        epoch = CALENDAR_MAC_1904 if date_system == "1904" else CALENDAR_WINDOWS_1900
        return ScalarValue.date_serial(
            float(to_excel(value, epoch)),
            value.isoformat(),
        )
    return ScalarValue.error("#VALUE!")


def _coerce_numeric(value: ScalarValue | _RangeValue) -> float | ScalarValue:
    if isinstance(value, _RangeValue):
        return ScalarValue.error("#VALUE!")
    if value.kind == "error":
        return value
    if value.kind in {"number", "date_serial"}:
        return value.number_value
    if value.kind == "blank":
        return 0.0
    if value.kind == "boolean":
        return 1.0 if value.value else 0.0
    return ScalarValue.error("#VALUE!")


def _finite_number(value: float) -> ScalarValue:
    return ScalarValue.number(value) if math.isfinite(value) else ScalarValue.error("#NUM!")


def _safe_fsum(values: Sequence[float]) -> ScalarValue:
    try:
        return _finite_number(math.fsum(values))
    except (ArithmeticError, OverflowError, ValueError):
        return ScalarValue.error("#NUM!")


def _truthy(value: ScalarValue | _RangeValue) -> bool | ScalarValue:
    if isinstance(value, _RangeValue):
        return ScalarValue.error("#VALUE!")
    if value.kind == "error":
        return value
    if value.kind == "blank":
        return False
    if value.kind == "boolean":
        return bool(value.value)
    if value.kind in {"number", "date_serial"}:
        return value.number_value != 0
    return ScalarValue.error("#VALUE!")


def _compare(left: ScalarValue, right: ScalarValue, operator: str) -> ScalarValue:
    comparable = True
    if left.kind == "blank" and right.kind in {"blank", "number", "date_serial"}:
        left_value: Any = 0.0
        right_value = 0.0 if right.kind == "blank" else right.number_value
    elif right.kind == "blank" and left.kind in {"number", "date_serial"}:
        left_value = left.number_value
        right_value = 0.0
    elif left.kind in {"number", "date_serial"} and right.kind in {"number", "date_serial"}:
        left_value = left.number_value
        right_value = right.number_value
    elif left.kind == right.kind == "text":
        left_value = str(left.value).casefold()
        right_value = str(right.value).casefold()
    elif left.kind == right.kind == "boolean":
        left_value = bool(left.value)
        right_value = bool(right.value)
    elif left.kind == right.kind == "blank":
        left_value = right_value = 0.0
    else:
        comparable = False
        left_value = right_value = None

    if not comparable:
        if operator == "equal":
            return ScalarValue.boolean(False)
        if operator == "not_equal":
            return ScalarValue.boolean(True)
        return ScalarValue.error("#VALUE!")
    operations = {
        "equal": left_value == right_value,
        "not_equal": left_value != right_value,
        "less": left_value < right_value,
        "less_equal": left_value <= right_value,
        "greater": left_value > right_value,
        "greater_equal": left_value >= right_value,
    }
    return ScalarValue.boolean(operations[operator])
