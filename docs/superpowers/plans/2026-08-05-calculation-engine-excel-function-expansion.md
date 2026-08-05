# Calculation Engine Excel Function Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic Excel-compatible `MOD`, `OR`, `YEAR`, `MATCH`, `XNPV`, and `XIRR` support so the supplied project-finance workbook can calculate without changing extraction behavior.

**Architecture:** Extend the existing closed Phase 2 function registry and `SafeCalculationEvaluator`; the generic parser, compiler, IR, graph, extraction, persistence schema, API, and UI remain unchanged. Introduce `calc-engine-v4` and `calc-functions-v4`, preserve historical v3 artifacts, and prove each function through a separate RED-to-GREEN cycle before running the exact workbook read-only.

**Tech Stack:** Python 3.12, openpyxl 3.1.2 date/workbook primitives, existing typed calculation IR and evaluator, pytest.

## Global Constraints

- Production changes are limited to `apps/api/app/calculation_rules/phase2_types.py`, `apps/api/app/calculation_rules/phase2_registry.py`, and `apps/api/app/calculation_rules/evaluator.py`.
- Keep `PHASE2_IR_VERSION = "calc-ir-v2"`, `PHASE2_COMPILER_VERSION = "formula-compiler-v3"`, and `PHASE2_SEMANTICS_PROFILE = "excel-compatible-kpi-v1"` unchanged.
- Set `PHASE2_ENGINE_VERSION = "calc-engine-v4"` and `PHASE2_FUNCTION_REGISTRY_VERSION = "calc-functions-v4"`.
- Do not modify workbook-agent, partitioning, extraction, validation, canonical materialization, semantic bindings, database migrations, API contracts, or frontend code.
- Do not read cached workbook results during evaluation and do not coerce unavailable, unsupported, blocked, blank, or errors to zero.
- Preserve persisted v3 graph/run readability; do not rewrite existing artifacts or re-extract the workbook.
- Use `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3` for every pytest command.
- Apply strict TDD for every function: observe the focused test fail for the missing behavior before changing production code.

---

## File Structure

- Modify `apps/api/app/calculation_rules/phase2_types.py`: current engine and registry capability identifiers only.
- Modify `apps/api/app/calculation_rules/phase2_registry.py`: six additive `FunctionDefinition` entries and their exact arities.
- Modify `apps/api/app/calculation_rules/evaluator.py`: dispatch branches plus private, pure comparison/date/financial helpers.
- Create `tests/test_calculation_engine_v4_excel_functions.py`: isolated workbook compiler/evaluator harness, six function conformance suites, and opt-in exact-workbook acceptance.
- Modify `tests/test_calculation_engine_v2_compiler.py`: current Phase 2 registry membership and v4 envelope expectations.
- Modify `tests/test_calculation_engine_v2_service.py`: current graph registry-version expectation.
- Modify `tests/test_calculation_integration_service.py`: current readiness/graph version expectations while keeping the explicit legacy-v3 reload fixture unchanged.
- Keep `tests/test_calculation_engine_v3_kpi_functions.py` unchanged as regression evidence for the existing function pack.

---

### Task 1: Establish the v4 Contract and Add `MOD`

**Files:**
- Create: `tests/test_calculation_engine_v4_excel_functions.py`
- Modify: `tests/test_calculation_engine_v2_compiler.py:108-151`
- Modify: `tests/test_calculation_engine_v2_service.py:80-100`
- Modify: `tests/test_calculation_integration_service.py:260-275,375-390`
- Modify: `apps/api/app/calculation_rules/phase2_types.py:16-22`
- Modify: `apps/api/app/calculation_rules/phase2_registry.py:45-57`
- Modify: `apps/api/app/calculation_rules/evaluator.py:511-531`

**Interfaces:**
- Consumes: `FormulaCompiler`, `WorkbookFormulaInventory`, `CalculationGraphBuilder`, `SafeCalculationEvaluator`, and `PHASE2_FUNCTION_REGISTRY`.
- Produces: v4 configuration identifiers, registry entry `MOD(2, 2)`, and evaluator result `ScalarValue` with Excel sign/error semantics.

- [ ] **Step 1: Create the reusable v4 test harness and failing `MOD` tests**

Create `tests/test_calculation_engine_v4_excel_functions.py` with the following imports and helper:

```python
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
```

- [ ] **Step 2: Run the `MOD` tests and verify RED**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v4_excel_functions.py -k mod
```

Expected: both tests fail because `MOD` is classified as `unsupported_function:MOD`; no production exception is accepted as the RED signal.

- [ ] **Step 3: Version the current contract and register `MOD`**

In `phase2_types.py`, change only:

```python
PHASE2_ENGINE_VERSION = "calc-engine-v4"
PHASE2_FUNCTION_REGISTRY_VERSION = "calc-functions-v4"
```

In `phase2_registry.py`, add:

```python
"MOD": _phase2_definition("MOD", 2, 2),
```

Update current-contract assertions in the three existing test files from
`calc-engine-v3`/`calc-functions-v3` to v4. In
`test_fresh_session_reloads_legacy_v2_run_versions_without_rerun`, keep the
explicit persisted `calc-engine-v3` and `calc-functions-v3` expectations.
Update `test_phase2_registry_is_closed_versioned_and_additive` so its exact
registry set includes `MOD`.

- [ ] **Step 4: Implement the minimal `MOD` evaluator branch**

Immediately after `first_number` is obtained in `_function`, add:

```python
if name == "MOD":
    divisor_value = self._evaluate_node(arguments[1], context, trace)
    divisor = _coerce_numeric(divisor_value)
    if isinstance(divisor, ScalarValue):
        return divisor
    if divisor == 0:
        return ScalarValue.error("#DIV/0!")
    try:
        result = first_number - divisor * math.floor(first_number / divisor)
    except (ArithmeticError, OverflowError, ValueError):
        return ScalarValue.error("#NUM!")
    return _finite_number(result)
```

- [ ] **Step 5: Run contract and `MOD` tests GREEN**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v4_excel_functions.py tests/test_calculation_engine_v2_compiler.py tests/test_calculation_engine_v2_service.py tests/test_calculation_integration_service.py
```

Expected: all selected tests pass; the legacy reload test still proves v3 records retain their stored versions.

- [ ] **Step 6: Commit the v4 contract and `MOD`**

```bash
git add apps/api/app/calculation_rules/phase2_types.py apps/api/app/calculation_rules/phase2_registry.py apps/api/app/calculation_rules/evaluator.py tests/test_calculation_engine_v4_excel_functions.py tests/test_calculation_engine_v2_compiler.py tests/test_calculation_engine_v2_service.py tests/test_calculation_integration_service.py
git commit -m "feat(calculation): add Excel MOD support"
```

---

### Task 2: Add `OR` Without Changing `AND`

**Files:**
- Modify: `tests/test_calculation_engine_v4_excel_functions.py`
- Modify: `tests/test_calculation_engine_v2_compiler.py:125-151`
- Modify: `apps/api/app/calculation_rules/phase2_registry.py:48-60`
- Modify: `apps/api/app/calculation_rules/evaluator.py:344-372`

**Interfaces:**
- Consumes: `_truthy(ScalarValue | _RangeValue) -> bool | ScalarValue` and the current `AND` range rules.
- Produces: registry entry `OR(1, 255)` and Boolean/error results without modifying `AND` outputs.

- [ ] **Step 1: Add failing range, scalar, and error tests**

Append:

```python
def test_or_flattens_ranges_and_preserves_scalar_coercion_rules() -> None:
    _compilation, truthy = _compile_and_evaluate(
        "=OR(FALSE,Inputs!A1:A3)",
        {"A1": 0, "A2": "ignored", "A3": 2},
    )
    _compilation, falsey = _compile_and_evaluate("=OR(FALSE,0)")
    _compilation, scalar_text = _compile_and_evaluate('=OR(FALSE,"text")')
    _compilation, empty_range = _compile_and_evaluate(
        "=OR(Inputs!A1:A2)",
        {"A1": "ignored", "A2": None},
    )
    _compilation, errored = _compile_and_evaluate("=OR(TRUE,#N/A)")

    assert truthy is not None and truthy.value == ScalarValue.boolean(True)
    assert falsey is not None and falsey.value == ScalarValue.boolean(False)
    assert scalar_text is not None and scalar_text.value == ScalarValue.error("#VALUE!")
    assert empty_range is not None and empty_range.value == ScalarValue.error("#VALUE!")
    assert errored is not None and errored.value == ScalarValue.error("#N/A")
```

- [ ] **Step 2: Run the `OR` test and verify RED**

Run the v4 test file with `-k 'or_'`. Expected: unsupported `OR` compilation.

- [ ] **Step 3: Register and evaluate `OR`**

Add `"OR": _phase2_definition("OR", 1, 255)` to the registry and include it
in the exact registry-set assertion. Replace the `if name == "AND"` branch with:

```python
if name in {"AND", "OR"}:
    result = name == "AND"
    found_logical = False
    for argument in arguments:
        value = self._evaluate_node(argument, context, trace)
        values = value.values if isinstance(value, _RangeValue) else (value,)
        for item in values:
            if item.kind == "error":
                return item
            if item.kind in {"text", "blank"}:
                if isinstance(value, _RangeValue):
                    continue
                return ScalarValue.error("#VALUE!")
            truth = _truthy(item)
            if isinstance(truth, ScalarValue):
                return truth
            found_logical = True
            result = result and truth if name == "AND" else result or truth
    if not found_logical:
        return ScalarValue.error("#VALUE!")
    return ScalarValue.boolean(result)
```

- [ ] **Step 4: Run `OR` plus existing `AND` tests GREEN**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v4_excel_functions.py tests/test_calculation_engine_v3_kpi_functions.py -k 'or_ or and_'
```

Expected: new `OR` tests and existing `AND` tests pass unchanged.

- [ ] **Step 5: Commit `OR`**

```bash
git add apps/api/app/calculation_rules/phase2_registry.py apps/api/app/calculation_rules/evaluator.py tests/test_calculation_engine_v2_compiler.py tests/test_calculation_engine_v4_excel_functions.py
git commit -m "feat(calculation): add Excel OR support"
```

---

### Task 3: Add Workbook-Date-System-Aware `YEAR`

**Files:**
- Modify: `tests/test_calculation_engine_v4_excel_functions.py`
- Modify: `tests/test_calculation_engine_v2_compiler.py`
- Modify: `apps/api/app/calculation_rules/phase2_registry.py`
- Modify: `apps/api/app/calculation_rules/evaluator.py:5-16,511-531,667-678`

**Interfaces:**
- Consumes: `context.catalog.workbook_date_system`, `_coerce_numeric`, and openpyxl `from_excel` with the workbook epoch.
- Produces: registry entry `YEAR(1, 1)` and `_year(serial: float, date_system: str) -> ScalarValue`.

- [ ] **Step 1: Add failing 1900/1904 and invalid-value tests**

Append:

```python
@pytest.mark.parametrize(
    ("date_system", "serial", "expected"),
    [
        ("1900", 0, 1900),
        ("1900", 60, 1900),
        ("1900", 45292, 2024),
        ("1904", 0, 1904),
        ("1904", 43830, 2024),
    ],
)
def test_year_respects_the_workbook_date_system(
    date_system: str,
    serial: int,
    expected: int,
) -> None:
    _compilation, execution = _compile_and_evaluate(
        f"=YEAR({serial})",
        date_system=date_system,
    )

    assert execution is not None
    assert execution.value == ScalarValue.number(expected)


@pytest.mark.parametrize(
    ("formula", "expected"),
    [("=YEAR(-1)", "#NUM!"), ('=YEAR("not-a-date")', "#VALUE!")],
)
def test_year_returns_typed_errors_for_invalid_values(
    formula: str,
    expected: str,
) -> None:
    _compilation, execution = _compile_and_evaluate(formula)

    assert execution is not None
    assert execution.status == "execution_error"
    assert execution.value == ScalarValue.error(expected)
```

- [ ] **Step 2: Run the `YEAR` tests and verify RED**

Run the v4 test file with `-k year`. Expected: unsupported `YEAR` compilation.

- [ ] **Step 3: Register and implement `YEAR`**

Add `"YEAR": _phase2_definition("YEAR", 1, 1)` and update the registry-set
test. Import `from_excel` beside `to_excel`. Dispatch after numeric coercion:

```python
if name == "YEAR":
    return _year(first_number, context.catalog.workbook_date_system)
```

Add the pure helper:

```python
def _year(serial: float, date_system: str) -> ScalarValue:
    if not math.isfinite(serial) or serial < 0:
        return ScalarValue.error("#NUM!")
    whole_serial = math.floor(serial)
    if date_system == "1900" and whole_serial in {0, 60}:
        return ScalarValue.number(1900)
    if date_system == "1904" and whole_serial == 0:
        return ScalarValue.number(1904)
    epoch = CALENDAR_MAC_1904 if date_system == "1904" else CALENDAR_WINDOWS_1900
    try:
        converted = from_excel(whole_serial, epoch)
        year = converted.year
    except (AttributeError, OverflowError, TypeError, ValueError):
        return ScalarValue.error("#NUM!")
    return ScalarValue.number(year)
```

- [ ] **Step 4: Run `YEAR` and scalar date regression tests GREEN**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v4_excel_functions.py tests/test_calculation_rule_evaluator.py -k 'year or date'
```

- [ ] **Step 5: Commit `YEAR`**

```bash
git add apps/api/app/calculation_rules/phase2_registry.py apps/api/app/calculation_rules/evaluator.py tests/test_calculation_engine_v2_compiler.py tests/test_calculation_engine_v4_excel_functions.py
git commit -m "feat(calculation): add Excel YEAR support"
```

---

### Task 4: Add One-Dimensional `MATCH`

**Files:**
- Modify: `tests/test_calculation_engine_v4_excel_functions.py`
- Modify: `tests/test_calculation_engine_v2_compiler.py`
- Modify: `apps/api/app/calculation_rules/phase2_registry.py`
- Modify: `apps/api/app/calculation_rules/evaluator.py:5-10,374-445,758-850`

**Interfaces:**
- Consumes: `_RangeValue`, `_coerce_numeric`, `_compare`, and range coordinate order.
- Produces: registry entry `MATCH(2, 3)`, `_match(...) -> ScalarValue`, and `_wildcard_regex(source: str) -> re.Pattern[str]`.

- [ ] **Step 1: Add failing exact, approximate, wildcard, and shape tests**

Append:

```python
@pytest.mark.parametrize(
    ("formula", "values", "expected"),
    [
        ("=MATCH(20,Inputs!A1:A3,0)", {"A1": 10, "A2": 20, "A3": 30}, 2),
        ("=MATCH(25,Inputs!A1:A3,1)", {"A1": 10, "A2": 20, "A3": 30}, 2),
        ("=MATCH(25,Inputs!A1:A3,-1)", {"A1": 30, "A2": 20, "A3": 10}, 1),
        ("=MATCH(2,Inputs!A1:C1,0)", {"A1": 1, "B1": 2, "C1": 3}, 2),
        ('=MATCH("proj*",Inputs!A1:A3,0)', {"A1": "Base", "A2": "Project", "A3": "Equity"}, 2),
        ('=MATCH("a~*",Inputs!A1:A2,0)', {"A1": "a?", "A2": "a*"}, 2),
    ],
)
def test_match_supports_excel_one_dimensional_modes(
    formula: str,
    values: dict[str, object],
    expected: int,
) -> None:
    _compilation, execution = _compile_and_evaluate(formula, values)

    assert execution is not None
    assert execution.value == ScalarValue.number(expected)


@pytest.mark.parametrize(
    ("formula", "values", "expected"),
    [
        ("=MATCH(99,Inputs!A1:A3,0)", {"A1": 1, "A2": 2, "A3": 3}, "#N/A"),
        ("=MATCH(2,Inputs!A1:B2,0)", {"A1": 1, "A2": 2, "B1": 3, "B2": 4}, "#VALUE!"),
        ("=MATCH(2,Inputs!A1:A3,2)", {"A1": 1, "A2": 2, "A3": 3}, "#VALUE!"),
    ],
)
def test_match_returns_typed_errors(
    formula: str,
    values: dict[str, object],
    expected: str,
) -> None:
    _compilation, execution = _compile_and_evaluate(formula, values)

    assert execution is not None
    assert execution.value == ScalarValue.error(expected)
```

- [ ] **Step 2: Run the `MATCH` tests and verify RED**

Run the v4 test file with `-k match`. Expected: unsupported `MATCH` compilation.

- [ ] **Step 3: Register `MATCH` and add dispatch validation**

Register `"MATCH": _phase2_definition("MATCH", 2, 3)` and update the exact
registry set. In `_function`, evaluate the lookup value and lookup array,
validate a one-dimensional `_RangeValue`, coerce/default `match_type`, and call:

```python
if name == "MATCH":
    lookup = self._evaluate_node(arguments[0], context, trace)
    lookup_array = self._evaluate_node(arguments[1], context, trace)
    if isinstance(lookup, _RangeValue) or not isinstance(lookup_array, _RangeValue):
        return ScalarValue.error("#VALUE!")
    if lookup_array.rows > 1 and lookup_array.columns > 1:
        return ScalarValue.error("#VALUE!")
    match_type = 1.0
    if len(arguments) == 3:
        raw_match_type = self._evaluate_node(arguments[2], context, trace)
        match_type = _coerce_numeric(raw_match_type)
        if isinstance(match_type, ScalarValue):
            return match_type
    if match_type not in {-1.0, 0.0, 1.0}:
        return ScalarValue.error("#VALUE!")
    return _match(lookup, lookup_array.values, int(match_type))
```

- [ ] **Step 4: Implement exact/approximate matching and wildcard escaping**

Import `re` and add:

```python
def _wildcard_regex(source: str) -> re.Pattern[str]:
    pieces = ["^"]
    escaped = False
    for character in source:
        if escaped:
            pieces.append(re.escape(character))
            escaped = False
        elif character == "~":
            escaped = True
        elif character == "*":
            pieces.append(".*")
        elif character == "?":
            pieces.append(".")
        else:
            pieces.append(re.escape(character))
    if escaped:
        pieces.append(re.escape("~"))
    pieces.append("$")
    return re.compile("".join(pieces), re.IGNORECASE)


def _match(
    lookup: ScalarValue,
    candidates: Sequence[ScalarValue],
    match_type: int,
) -> ScalarValue:
    if lookup.kind == "error":
        return lookup
    if match_type == 0:
        pattern = (
            _wildcard_regex(str(lookup.value))
            if lookup.kind == "text"
            and any(character in str(lookup.value) for character in ("*", "?", "~"))
            else None
        )
        for index, candidate in enumerate(candidates, start=1):
            if candidate.kind == "error":
                return candidate
            if pattern is not None:
                matched = candidate.kind == "text" and pattern.fullmatch(str(candidate.value))
            else:
                compared = _compare(candidate, lookup, "equal")
                matched = compared.kind != "error" and bool(compared.value)
            if matched:
                return ScalarValue.number(index)
        return ScalarValue.error("#N/A")

    operator = "less_equal" if match_type == 1 else "greater_equal"
    best: int | None = None
    for index, candidate in enumerate(candidates, start=1):
        if candidate.kind == "error":
            return candidate
        compared = _compare(candidate, lookup, operator)
        if compared.kind == "error":
            continue
        if bool(compared.value):
            best = index
        elif best is not None:
            break
    return ScalarValue.number(best) if best is not None else ScalarValue.error("#N/A")
```

- [ ] **Step 5: Run `MATCH` and comparison regressions GREEN**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v4_excel_functions.py tests/test_calculation_engine_v2_compiler.py tests/test_calculation_rule_evaluator.py -k 'match or comparison'
```

- [ ] **Step 6: Commit `MATCH`**

```bash
git add apps/api/app/calculation_rules/phase2_registry.py apps/api/app/calculation_rules/evaluator.py tests/test_calculation_engine_v2_compiler.py tests/test_calculation_engine_v4_excel_functions.py
git commit -m "feat(calculation): add Excel MATCH support"
```

---

### Task 5: Add Strict Irregular-Date `XNPV`

**Files:**
- Modify: `tests/test_calculation_engine_v4_excel_functions.py`
- Modify: `tests/test_calculation_engine_v2_compiler.py`
- Modify: `apps/api/app/calculation_rules/phase2_registry.py`
- Modify: `apps/api/app/calculation_rules/evaluator.py:445-480,667-741`

**Interfaces:**
- Consumes: `_RangeValue`, `_coerce_numeric`, `_finite_number`.
- Produces: registry entry `XNPV(3, 3)`, `_strict_numeric_range_values`, `_dated_cash_flows`, `_xnpv_value`, and `_xnpv`.

- [ ] **Step 1: Add failing result and validation tests**

Append:

```python
def test_xnpv_discounts_irregular_cash_flows_from_the_first_date() -> None:
    _compilation, execution = _compile_and_evaluate(
        "=XNPV(10%,Inputs!A1:A3,Inputs!B1:B3)",
        {
            "A1": -100,
            "A2": 30,
            "A3": 90,
            "B1": 43831,
            "B2": 44013,
            "B3": 44197,
        },
    )

    expected = -100 + 30 / (1.1 ** (182 / 365)) + 90 / (1.1 ** (366 / 365))
    assert execution is not None and execution.value is not None
    assert execution.value.number_value == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize(
    ("formula", "values", "expected"),
    [
        (
            "=XNPV(10%,Inputs!A1:A2,Inputs!B1:B3)",
            {"A1": -100, "A2": 110, "B1": 43831, "B2": 44197, "B3": 44562},
            "#VALUE!",
        ),
        (
            "=XNPV(10%,Inputs!A1:A2,Inputs!B1:B2)",
            {"A1": -100, "A2": "bad", "B1": 43831, "B2": 44197},
            "#VALUE!",
        ),
        (
            "=XNPV(10%,Inputs!A1:A2,Inputs!B1:B2)",
            {"A1": -100, "A2": 110, "B1": 44197, "B2": 43831},
            "#NUM!",
        ),
        (
            "=XNPV(-100%,Inputs!A1:A2,Inputs!B1:B2)",
            {"A1": -100, "A2": 110, "B1": 43831, "B2": 44197},
            "#NUM!",
        ),
    ],
)
def test_xnpv_returns_typed_input_and_domain_errors(
    formula: str,
    values: dict[str, object],
    expected: str,
) -> None:
    _compilation, execution = _compile_and_evaluate(formula, values)

    assert execution is not None
    assert execution.value == ScalarValue.error(expected)
```

- [ ] **Step 2: Run `XNPV` tests and verify RED**

Run the v4 test file with `-k xnpv`. Expected: unsupported `XNPV` compilation.

- [ ] **Step 3: Register and dispatch `XNPV`**

Register `"XNPV": _phase2_definition("XNPV", 3, 3)` and update the exact
registry set. Add the evaluator branch:

```python
if name == "XNPV":
    rate_value = self._evaluate_node(arguments[0], context, trace)
    values = self._evaluate_node(arguments[1], context, trace)
    dates = self._evaluate_node(arguments[2], context, trace)
    rate = _coerce_numeric(rate_value)
    if isinstance(rate, ScalarValue):
        return rate
    paired = _dated_cash_flows(values, dates)
    if isinstance(paired, ScalarValue):
        return paired
    cash_flows, day_offsets = paired
    return _xnpv(rate, cash_flows, day_offsets)
```

- [ ] **Step 4: Implement strict paired-range and XNPV helpers**

Add:

```python
def _strict_numeric_range_values(value: _RangeValue) -> list[float] | ScalarValue:
    if value.rows > 1 and value.columns > 1:
        return ScalarValue.error("#VALUE!")
    numbers: list[float] = []
    for item in value.values:
        if item.kind == "error":
            return item
        if item.kind not in {"number", "date_serial"}:
            return ScalarValue.error("#VALUE!")
        numbers.append(item.number_value)
    return numbers


def _dated_cash_flows(
    values: ScalarValue | _RangeValue,
    dates: ScalarValue | _RangeValue,
) -> tuple[list[float], list[float]] | ScalarValue:
    if not isinstance(values, _RangeValue) or not isinstance(dates, _RangeValue):
        return ScalarValue.error("#VALUE!")
    cash_flows = _strict_numeric_range_values(values)
    date_serials = _strict_numeric_range_values(dates)
    if isinstance(cash_flows, ScalarValue):
        return cash_flows
    if isinstance(date_serials, ScalarValue):
        return date_serials
    if not cash_flows or len(cash_flows) != len(date_serials):
        return ScalarValue.error("#VALUE!")
    whole_dates = [math.trunc(value) for value in date_serials]
    if any(value < 0 for value in whole_dates):
        return ScalarValue.error("#VALUE!")
    first_date = whole_dates[0]
    if any(value < first_date for value in whole_dates):
        return ScalarValue.error("#NUM!")
    return cash_flows, [float(value - first_date) for value in whole_dates]


def _xnpv_value(rate: float, cash_flows: Sequence[float], day_offsets: Sequence[float]) -> float:
    if rate <= -1.0 or not math.isfinite(rate):
        raise ValueError("XNPV rate is outside the real-valued domain")
    base = 1.0 + rate
    return math.fsum(
        cash_flow / (base ** (day_offset / 365.0))
        for cash_flow, day_offset in zip(cash_flows, day_offsets)
    )


def _xnpv(rate: float, cash_flows: Sequence[float], day_offsets: Sequence[float]) -> ScalarValue:
    try:
        value = _xnpv_value(rate, cash_flows, day_offsets)
    except (ArithmeticError, OverflowError, ValueError):
        return ScalarValue.error("#NUM!")
    return _finite_number(value)
```

- [ ] **Step 5: Run `XNPV`, `NPV`, and registry tests GREEN**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v4_excel_functions.py tests/test_calculation_engine_v3_kpi_functions.py tests/test_calculation_engine_v2_compiler.py -k 'xnpv or npv or registry'
```

- [ ] **Step 6: Commit `XNPV`**

```bash
git add apps/api/app/calculation_rules/phase2_registry.py apps/api/app/calculation_rules/evaluator.py tests/test_calculation_engine_v2_compiler.py tests/test_calculation_engine_v4_excel_functions.py
git commit -m "feat(calculation): add Excel XNPV support"
```

---

### Task 6: Add Deterministic Guess-Sensitive `XIRR`

**Files:**
- Modify: `tests/test_calculation_engine_v4_excel_functions.py`
- Modify: `tests/test_calculation_engine_v2_compiler.py`
- Modify: `apps/api/app/calculation_rules/phase2_registry.py`
- Modify: `apps/api/app/calculation_rules/evaluator.py:445-480,679-733`

**Interfaces:**
- Consumes: `_dated_cash_flows`, `_xnpv_value`, `_coerce_numeric`, `_finite_number`.
- Produces: registry entry `XIRR(2, 3)`, `_xirr_derivative`, `_xirr_bracket`, and `_xirr`.

- [ ] **Step 1: Add failing convergence, guess, and error tests**

Append:

```python
def test_xirr_solves_irregular_dates_deterministically() -> None:
    values = {
        "A1": -10000,
        "A2": 2750,
        "A3": 4250,
        "A4": 3250,
        "A5": 2750,
        "B1": 39448,
        "B2": 39508,
        "B3": 39751,
        "B4": 39859,
        "B5": 39904,
    }
    first = _compile_and_evaluate("=XIRR(Inputs!A1:A5,Inputs!B1:B5)", values)[1]
    second = _compile_and_evaluate("=XIRR(Inputs!A1:A5,Inputs!B1:B5,10%)", values)[1]

    assert first is not None and first.value is not None
    assert second is not None and second.value is not None
    assert first.value.number_value == pytest.approx(0.373362535, abs=1e-7)
    assert second.value.number_value == pytest.approx(first.value.number_value, abs=1e-10)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"A1": 100, "A2": 10, "B1": 43831, "B2": 44197}, "#NUM!"),
        ({"A1": -100, "A2": -10, "B1": 43831, "B2": 44197}, "#NUM!"),
        ({"A1": -100, "A2": 110, "B1": 44197, "B2": 43831}, "#NUM!"),
    ],
)
def test_xirr_rejects_invalid_sign_and_date_inputs(
    values: dict[str, object],
    expected: str,
) -> None:
    _compilation, execution = _compile_and_evaluate(
        "=XIRR(Inputs!A1:A2,Inputs!B1:B2)",
        values,
    )

    assert execution is not None
    assert execution.value == ScalarValue.error(expected)


def test_xirr_returns_num_when_no_root_converges() -> None:
    _compilation, execution = _compile_and_evaluate(
        "=XIRR(Inputs!A1:A3,Inputs!B1:B3,-99%)",
        {"A1": -100, "A2": 1, "A3": -1, "B1": 43831, "B2": 43832, "B3": 43833},
    )

    assert execution is not None
    assert execution.value == ScalarValue.error("#NUM!")
```

- [ ] **Step 2: Run the `XIRR` tests and verify RED**

Run the v4 test file with `-k xirr`. Expected: unsupported `XIRR` compilation.

- [ ] **Step 3: Register and dispatch `XIRR`**

Register `"XIRR": _phase2_definition("XIRR", 2, 3)` and update the exact
registry set. Add:

```python
if name == "XIRR":
    values = self._evaluate_node(arguments[0], context, trace)
    dates = self._evaluate_node(arguments[1], context, trace)
    paired = _dated_cash_flows(values, dates)
    if isinstance(paired, ScalarValue):
        return paired
    cash_flows, day_offsets = paired
    guess = 0.1
    if len(arguments) == 3:
        guess_value = self._evaluate_node(arguments[2], context, trace)
        guess = _coerce_numeric(guess_value)
        if isinstance(guess, ScalarValue):
            return guess
    return _xirr(cash_flows, day_offsets, guess)
```

- [ ] **Step 4: Implement Newton plus deterministic bracket fallback**

Add these constants and helpers near `_irr`:

```python
_XIRR_MIN_RATE = -0.999999999
_XIRR_MAX_RATE = 1_000_000.0
_XIRR_MAX_ITERATIONS = 100
_XIRR_RATE_TOLERANCE = 1e-10
_XIRR_VALUE_TOLERANCE = 1e-8


def _xirr_derivative(
    rate: float,
    cash_flows: Sequence[float],
    day_offsets: Sequence[float],
) -> float:
    base = 1.0 + rate
    return math.fsum(
        -(day_offset / 365.0)
        * cash_flow
        / (base ** ((day_offset / 365.0) + 1.0))
        for cash_flow, day_offset in zip(cash_flows, day_offsets)
        if day_offset
    )


def _xirr_bracket(
    cash_flows: Sequence[float],
    day_offsets: Sequence[float],
    guess: float,
) -> tuple[float, float] | None:
    grid = sorted(
        {
            _XIRR_MIN_RATE,
            -0.99,
            -0.9,
            -0.75,
            -0.5,
            -0.25,
            0.0,
            0.1,
            0.25,
            0.5,
            1.0,
            2.0,
            5.0,
            10.0,
            100.0,
            1_000.0,
            _XIRR_MAX_RATE,
            min(max(guess, _XIRR_MIN_RATE), _XIRR_MAX_RATE),
        }
    )
    brackets: list[tuple[float, float]] = []
    previous_rate = grid[0]
    previous_value = _xnpv_value(previous_rate, cash_flows, day_offsets)
    for rate in grid[1:]:
        value = _xnpv_value(rate, cash_flows, day_offsets)
        if value == 0:
            return rate, rate
        if previous_value == 0:
            return previous_rate, previous_rate
        if math.copysign(1.0, value) != math.copysign(1.0, previous_value):
            brackets.append((previous_rate, rate))
        previous_rate, previous_value = rate, value
    if not brackets:
        return None
    return min(brackets, key=lambda pair: abs(((pair[0] + pair[1]) / 2.0) - guess))


def _xirr(
    cash_flows: Sequence[float],
    day_offsets: Sequence[float],
    guess: float,
) -> ScalarValue:
    if (
        len(cash_flows) < 2
        or not any(value > 0 for value in cash_flows)
        or not any(value < 0 for value in cash_flows)
        or not math.isfinite(guess)
        or guess <= -1.0
    ):
        return ScalarValue.error("#NUM!")
    rate = min(guess, _XIRR_MAX_RATE)
    try:
        for _iteration in range(_XIRR_MAX_ITERATIONS):
            value = _xnpv_value(rate, cash_flows, day_offsets)
            if abs(value) <= _XIRR_VALUE_TOLERANCE:
                return _finite_number(rate)
            derivative = _xirr_derivative(rate, cash_flows, day_offsets)
            if not math.isfinite(derivative) or abs(derivative) <= 1e-15:
                break
            next_rate = rate - value / derivative
            if not (_XIRR_MIN_RATE < next_rate <= _XIRR_MAX_RATE):
                break
            if (
                abs(next_rate - rate) <= _XIRR_RATE_TOLERANCE
                and abs(_xnpv_value(next_rate, cash_flows, day_offsets))
                <= _XIRR_VALUE_TOLERANCE
            ):
                return _finite_number(next_rate)
            rate = next_rate

        bracket = _xirr_bracket(cash_flows, day_offsets, guess)
        if bracket is None:
            return ScalarValue.error("#NUM!")
        low, high = bracket
        if low == high:
            return _finite_number(low)
        low_value = _xnpv_value(low, cash_flows, day_offsets)
        for _iteration in range(_XIRR_MAX_ITERATIONS):
            middle = (low + high) / 2.0
            middle_value = _xnpv_value(middle, cash_flows, day_offsets)
            if abs(middle_value) <= _XIRR_VALUE_TOLERANCE or abs(high - low) <= _XIRR_RATE_TOLERANCE:
                return _finite_number(middle)
            if math.copysign(1.0, middle_value) == math.copysign(1.0, low_value):
                low, low_value = middle, middle_value
            else:
                high = middle
    except (ArithmeticError, OverflowError, ValueError):
        return ScalarValue.error("#NUM!")
    return ScalarValue.error("#NUM!")
```

- [ ] **Step 5: Run `XIRR`, `IRR`, and full v4 tests GREEN**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v4_excel_functions.py tests/test_calculation_engine_v3_kpi_functions.py -k 'xirr or irr'
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v4_excel_functions.py
```

- [ ] **Step 6: Commit `XIRR`**

```bash
git add apps/api/app/calculation_rules/phase2_registry.py apps/api/app/calculation_rules/evaluator.py tests/test_calculation_engine_v2_compiler.py tests/test_calculation_engine_v4_excel_functions.py
git commit -m "feat(calculation): add Excel XIRR support"
```

---

### Task 7: Prove the Exact Workbook Without Re-extraction

**Files:**
- Modify: `tests/test_calculation_engine_v4_excel_functions.py`

**Interfaces:**
- Consumes: `PF_WELL_ROUNDED_WORKBOOK_PATH`, the v4 compiler/graph/evaluator, and workbook cached values for comparison only.
- Produces: opt-in read-only acceptance proving all six target functions compile and key downstream cells execute.

- [ ] **Step 1: Add a whole-workbook execution helper**

Append:

```python
def _compile_and_evaluate_path(workbook_path: Path):
    configuration = Phase2CalculationConfiguration()
    catalog = WorkbookFormulaInventory(configuration).scan(
        workbook_path.read_bytes(),
        str(uuid.uuid4()),
    )
    compiler = FormulaCompiler(configuration, function_registry=PHASE2_FUNCTION_REGISTRY)
    compilations = tuple(compiler.compile(formula, catalog) for formula in catalog.formulas)
    graph = CalculationGraphBuilder(configuration).build(catalog, compilations)
    executions = SafeCalculationEvaluator(function_registry=PHASE2_FUNCTION_REGISTRY).execute(
        graph,
        catalog,
        compilations,
        configuration,
    )
    return catalog, compilations, executions
```

- [ ] **Step 2: Add the opt-in exact-workbook acceptance test**

Append:

```python
def test_well_rounded_workbook_executes_the_new_function_pack() -> None:
    configured = os.environ.get("PF_WELL_ROUNDED_WORKBOOK_PATH")
    if configured is None:
        pytest.skip("PF_WELL_ROUNDED_WORKBOOK_PATH is not configured")
    workbook_path = Path(configured)
    assert workbook_path.is_file()

    catalog, compilations, executions = _compile_and_evaluate_path(workbook_path)
    formula_by_id = {formula.id: formula for formula in catalog.formulas}
    target_names = {"MOD", "OR", "YEAR", "MATCH", "XNPV", "XIRR"}
    target_compilations = [
        compilation
        for compilation in compilations
        if any(
            f"{name}(" in formula_by_id[compilation.formula_cell_id].exact_formula.upper()
            for name in target_names
        )
    ]

    assert len(target_compilations) == 140
    assert {item.support_status for item in target_compilations} == {"supported"}
    assert not [
        item
        for item in compilations
        if any(construct.startswith("unsupported_function:") for construct in item.unsupported_constructs)
    ]
    assert not [
        execution
        for execution in executions.values()
        if execution.status in {"not_executable", "blocked_by_dependency"}
    ]

    cached = load_workbook(workbook_path, data_only=True, read_only=True)
    try:
        execution_by_address = {
            (reference.sheet_name, reference.cell_address): execution
            for reference, execution in executions.items()
        }
        for sheet_name, addresses in {
            "Operations": ("B19", "P19", "B40", "P40"),
            "Financing": ("B8", "P8", "B14", "P14"),
            "Summary": ("B14", "B15", "B16", "B17", "B18", "B19", "B20"),
        }.items():
            for address in addresses:
                execution = execution_by_address[(sheet_name, address)]
                assert execution.status == "executed"
                cached_value = cached[sheet_name][address].value
                if isinstance(cached_value, (int, float)):
                    assert execution.value is not None
                    assert execution.value.number_value == pytest.approx(
                        float(cached_value),
                        rel=1e-7,
                        abs=1e-7,
                    )
    finally:
        cached.close()
```

- [ ] **Step 3: Run exact-workbook acceptance**

Run:

```bash
PF_WELL_ROUNDED_WORKBOOK_PATH="/Users/kingjason/Downloads/PF_Well_Rounded_Project_Finance_Model.xlsx" "/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v4_excel_functions.py -k well_rounded
```

Expected: the test passes with 140 target calls supported, no unsupported
function diagnostics, no dependency blocks, and cached-value agreement for
numeric key-path cells. If a key cell produces a typed runtime error, preserve
the error and correct the function semantics; do not relax the assertion or
read cached values as calculated output.

- [ ] **Step 4: Commit exact-workbook acceptance coverage**

```bash
git add tests/test_calculation_engine_v4_excel_functions.py
git commit -m "test(calculation): cover well-rounded workbook functions"
```

---

### Task 8: Regression, Extraction Guard, and Scope Audit

**Files:**
- Verify only; no production file is added in this task.

**Interfaces:**
- Consumes: all preceding function increments.
- Produces: focused, extraction, full-suite, and diff-scope evidence suitable for completion review.

- [ ] **Step 1: Run all calculation-engine focused tests**

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_calculation_rule_compiler.py tests/test_calculation_rule_evaluator.py tests/test_calculation_engine_v2_compiler.py tests/test_calculation_engine_v2_service.py tests/test_calculation_engine_v3_kpi_functions.py tests/test_calculation_engine_v4_excel_functions.py tests/test_calculation_integration_service.py
```

Expected: all selected tests pass; opt-in workbook acceptance is skipped only
when the environment variable is absent.

- [ ] **Step 2: Run extraction regressions without changing expectations**

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -q tests/test_experimental_workbook_upload.py tests/test_model_extraction_lifecycle.py tests/test_model_extraction_reload.py tests/test_workbook_validation.py experiments/workbook_agent_poc/tests
```

Expected: the suite passes with the repository's existing skips; no extraction
test expectation is edited to obtain GREEN.

- [ ] **Step 3: Run the complete non-PostgreSQL backend suite**

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -p no:cacheprovider -m "not postgres" -q
```

Expected: all non-PostgreSQL tests pass. Any failure is diagnosed before
completion; do not classify it as unrelated without separate baseline evidence.

- [ ] **Step 4: Re-run the exact workbook with the environment variable**

Use the Task 7 command and require a pass. This is read-only and must not create
a database run, upload, extraction, or container rebuild.

- [ ] **Step 5: Audit changed files and forbidden paths**

Run:

```bash
git diff --name-only 4059674..HEAD
git diff --check 4059674..HEAD
git status --short
```

Expected production paths are exactly:

```text
apps/api/app/calculation_rules/evaluator.py
apps/api/app/calculation_rules/phase2_registry.py
apps/api/app/calculation_rules/phase2_types.py
```

All other changed paths must be the approved tests or Superpowers documents.
The status output must be clean. If any extraction, compiler, graph, migration,
API, semantic-binding, or frontend production path appears, stop completion and
remove that out-of-scope change through a new focused correction commit.

- [ ] **Step 6: Review commits without squashing historical work**

```bash
git log --oneline --decorate 4059674..HEAD
```

Expected: one focused commit per function-family step plus the acceptance-test
commit. Do not merge or push as part of this plan.
