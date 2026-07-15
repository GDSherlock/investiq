# Simple Executable Calculation Rule Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Phase 1 deterministic Excel-subset compiler, dependency graph, safe evaluator, cached-value comparison, canonical lineage overlay, and durable six-table persistence contract.

**Architecture:** Add an isolated `apps.api.app.calculation_rules` package. Workbook-scoped inventory, references, and `calc-ir-v1` are compiled from immutable bytes; model-scoped mappings and execution results are orchestrated through the canonical-only `ModelExtractionReadService`. Formula strings are parser input and evidence only; execution accepts validated typed IR.

**Tech Stack:** Python 3.11+, openpyxl 3.1.2, SQLAlchemy 2.0, Alembic 1.13, pytest, SQLite, optional isolated PostgreSQL.

## Global Constraints

- Implement Phase 1 only; do not add grouped rules, Scenario/Sensitivity execution, frontend behavior, or a public HTTP API.
- Support only arithmetic `+ - * / ^`, unary `+ -`, postfix `%`, comparisons, literals, bounded A1 cell/range references, and `SUM`, `AVERAGE`, `MIN`, `MAX`, `ABS`, `ROUND`, `IF`.
- Never execute raw formulas through `eval`, `exec`, generated source, SQL expressions, shell commands, plugins, external links, or LLMs.
- Use workbook cell identity for execution; canonical mapping is optional lineage and never an execution gate.
- Preserve unsupported, external, special, cyclic, and failed formulas as evidence while independent supported components continue.
- Use `calc-ir-v1`, `formula-compiler-v1`, `calc-engine-v1`, `function-registry-v1`, and `excel-subset-v1` as the initial immutable version names.
- Use default limits of 8,192 formula characters, 2,048 tokens, 2,048 IR nodes, depth 128, 255 arguments, 10,000 cells per range, 100,000 formulas, and 1,000,000 expanded dependency edges.
- Use absolute/relative numeric tolerance `1e-9`; cache freshness is only `missing`, `unknown`, or `recalculation_required`.
- Persist direct traces with at most 256 inputs per formula; retain run rows with their owning model/workbook under the approved FK/cascade policy.
- Follow real RED -> GREEN -> REFACTOR. Do not write production behavior before observing its focused test fail for the intended reason.

---

### Task 1: Domain Contracts and Workbook Formula Inventory

**Files:**
- Create: `apps/api/app/calculation_rules/__init__.py`
- Create: `apps/api/app/calculation_rules/types.py`
- Create: `apps/api/app/calculation_rules/inventory.py`
- Create: `tests/test_calculation_rule_inventory.py`

**Interfaces:**
- Consumes: verified `.xlsx` bytes from `ModelExtractionReadService.load_workbook_version`.
- Produces: `CalculationRuleExtractionConfiguration`, `WorkbookCellRef`, `WorkbookCellFact`, `WorkbookFormulaCell`, `WorkbookCatalog`, and `WorkbookFormulaInventory.scan(content_bytes, workbook_version_id)`.

- [x] **Step 1: Write failing identity and inventory tests**

```python
def test_inventory_scans_visible_hidden_and_very_hidden_formula_cells():
    catalog = WorkbookFormulaInventory().scan(workbook_bytes, workbook_version_id)
    assert [(c.ref.sheet_name, c.ref.cell_address) for c in catalog.formulas] == [
        ("Visible", "B1"), ("Hidden", "B1"), ("VeryHidden", "B1")
    ]

def test_formula_cell_ids_are_retry_stable_and_anchor_free():
    assert FormulaIdFactory(workbook_version_id).formula_cell_id(ref) == expected_uuid5
```

- [x] **Step 2: Run inventory tests and verify RED**

Run: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3 -m pytest tests/test_calculation_rule_inventory.py -q`

Expected: collection fails because `apps.api.app.calculation_rules` does not exist.

- [x] **Step 3: Implement immutable domain types, deterministic UUIDv5 factories, and dual-workbook scanning**

```python
@dataclass(frozen=True)
class WorkbookCellRef:
    workbook_version_id: str
    sheet_name: str
    sheet_position: int
    cell_address: str

class WorkbookFormulaInventory:
    def scan(self, content_bytes: bytes, workbook_version_id: str) -> WorkbookCatalog:
        """Load formula and data-only copies with keep_links=False and inventory all sheets."""
```

Classify scalar formulas, array/data-table/special formulas, exact caches, workbook epoch, calculation flags, hidden-state metadata, and static/blank cell values. Reject formula-count and workbook-bound violations without traversing links.

- [x] **Step 4: Run inventory tests and verify GREEN**

Run: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3 -m pytest tests/test_calculation_rule_inventory.py -q`

Expected: all inventory tests pass.

---

### Task 2: Dedicated Formula Compiler and Validated `calc-ir-v1`

**Files:**
- Create: `apps/api/app/calculation_rules/compiler.py`
- Create: `tests/test_calculation_rule_compiler.py`

**Interfaces:**
- Consumes: `WorkbookFormulaCell`, `WorkbookCatalog`, and configuration limits.
- Produces: `FormulaCompiler.compile(formula_cell, workbook_catalog, profile) -> FormulaCompilation`, validated IR dictionaries, reference rows, normalized signatures, warnings, and unsupported-construct evidence.

- [x] **Step 1: Write table-driven RED tests for the complete whitelist**

```python
@pytest.mark.parametrize("formula,node_type", [
    ("=1+2*3", "binary_operation"),
    ("=-2^2%", "binary_operation"),
    ("=A1>=Inputs!$B$2", "comparison"),
    ('=IF(A1>0,SUM(B1:B3),"none")', "function_call"),
])
def test_compiler_emits_valid_calc_ir_v1(formula, node_type, catalog):
    compiled = compile_at(formula, catalog)
    assert compiled.support_status == "supported"
    assert compiled.ir_json["ir_version"] == "calc-ir-v1"
    assert compiled.ir_json["root"]["node_type"] == node_type
```

Add focused tests for literals, errors, quoted/Unicode sheet names, mixed anchors, finite ranges, precedence, source spans, lazy-IF syntax, normalized signatures, deterministic reference IDs, and schema revalidation.

- [x] **Step 2: Run compiler whitelist tests and verify RED**

Run: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3 -m pytest tests/test_calculation_rule_compiler.py -q`

Expected: import/attribute failures for the absent compiler.

- [x] **Step 3: Implement lexer, Pratt/precedence parser, reference resolver, and closed IR validator**

Implemented interfaces: `FormulaCompiler(configuration).compile(formula_cell, workbook_catalog) -> FormulaCompilation` and `CalculationExpressionValidator.validate(expression, formula_cell, references, configuration) -> None`.

The lexer records zero-based half-open spans into the exact leading-`=` formula. The parser has no evaluation behavior and emits only registered nodes/operators/functions.

- [x] **Step 4: Write RED tests for every exclusion and maximum-valid evidence**

Cover unknown/conditional/lookup/financial/date/dynamic functions, names, structured/whole row/whole column/3-D/external references, arrays, unions/intersections, `&`, malformed formulas, and each resource limit. Assert external formulas are `external_reference`, other unsupported constructs are `unsupported`, syntax errors are distinct, `ir_json` is null, and recognized references remain.

- [x] **Step 5: Implement support classification and verify GREEN**

Run: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3 -m pytest tests/test_calculation_rule_compiler.py -q`

Expected: all compiler tests pass; only pre-existing dependency deprecation warnings are permitted.

---

### Task 3: Dependency Graph, Safe Evaluator, and Cache Comparator

**Files:**
- Create: `apps/api/app/calculation_rules/graph.py`
- Create: `apps/api/app/calculation_rules/evaluator.py`
- Create: `apps/api/app/calculation_rules/comparison.py`
- Create: `tests/test_calculation_rule_graph.py`
- Create: `tests/test_calculation_rule_evaluator.py`

**Interfaces:**
- Consumes: validated compilations and catalog static values only.
- Produces: deterministic graph order/SCCs/block reasons, `ScalarValue`, per-cell `FormulaExecution`, and `CachedValueComparison`.

- [x] **Step 1: Write graph RED tests**

```python
def test_graph_detects_cycles_and_executes_an_independent_component():
    plan = CalculationGraphBuilder(configuration).build(catalog, compilations)
    assert plan.cycles == ((a_ref, b_ref),)
    assert plan.status_by_cell[dependent_ref] == "blocked_by_dependency"
    assert independent_ref in plan.evaluation_order
```

Cover range expansion, static/helper nodes, self/multi-cell cycles, deterministic tie-breaking, unresolved/external zero edges, edge budgets, blocked transitive dependents, and no cache fallback.

- [x] **Step 2: Run graph tests and verify RED, then implement Tarjan plus Kahn ordering**

Run: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3 -m pytest tests/test_calculation_rule_graph.py -q`

Expected RED: graph module absent. Implement SCC detection and deterministic topological sorting; rerun until GREEN.

- [x] **Step 3: Write evaluator/comparator RED tests**

```python
@pytest.mark.parametrize("formula,expected", [
    ("=SUM(A1:A3)", ScalarValue.number(6)),
    ("=ROUND(-2.5,0)", ScalarValue.number(-3)),
    ("=IF(TRUE,1,1/0)", ScalarValue.number(1)),
])
def test_evaluator_conforms_to_excel_subset(formula, expected, executable_case):
    assert executable_case(formula).value == expected
```

Cover all operators/functions, direct-versus-range coercion, blanks, booleans, text, dates, errors, division/overflow, percent, comparisons, lazy IF, trace bounding, cache statuses, tolerance, and type-exact comparisons.

- [x] **Step 4: Implement typed-value evaluation and comparison without formula strings**

Implemented interfaces: `SafeCalculationEvaluator.evaluate(expression, context) -> FormulaExecution` and `CachedValueComparator.compare(calculated, cached, freshness) -> CachedValueComparison`.

Validate IR before dispatch. The registry contains only the seven approved functions and marks `IF` lazy. No function receives raw formula text.

- [x] **Step 5: Run graph/evaluator tests and verify GREEN**

Run: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3 -m pytest tests/test_calculation_rule_graph.py tests/test_calculation_rule_evaluator.py -q`

Expected: all tests pass.

---

### Task 4: Additive Six-Table Persistence and Repository

**Files:**
- Create: `apps/api/app/calculation_rules/models.py`
- Create: `apps/api/app/calculation_rules/repository.py`
- Create: `apps/api/alembic/versions/20260715_0003_calculation_rule_extraction.py`
- Create: `tests/test_calculation_rule_persistence_schema.py`
- Modify: `tests/model_extraction_test_support.py`

**Interfaces:**
- Consumes: deterministic inventory, compilations, mappings, executions, and summary DTOs.
- Produces: idempotent workbook compilation reuse and model-scoped extraction/result reload.

- [x] **Step 1: Write schema/repository RED tests**

Assert all six tables, named FKs/checks/uniques/indexes, SQLite migration from empty DB, optional PostgreSQL migration/JSON/UUID behavior, inventory reuse, immutable compiler versions, deterministic retry IDs, model-scoped mappings/results, cascades, rollback, and cross-session DTO reload.

- [x] **Step 2: Run persistence tests and verify RED**

Run: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3 -m pytest tests/test_calculation_rule_persistence_schema.py -q`

Expected: model/table imports fail.

- [x] **Step 3: Implement SQLAlchemy models, Alembic migration, and repository**

Implemented repository operations: `start_run`, `load_completed_result`, `save_compilation`, `replace_outputs`, `complete_run`, `mark_failed`, and `load_result`.

Use generic JSON and portable `Uuid(as_uuid=False)`. Existing Model Extraction tables and APIs remain unchanged.

- [x] **Step 4: Run persistence tests and verify GREEN**

Run: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3 -m pytest tests/test_calculation_rule_persistence_schema.py -q`

Expected: SQLite passes; PostgreSQL tests skip unless `TEST_POSTGRES_URL` is explicitly configured.

---

### Task 5: Canonical-Only Orchestration and End-to-End Phase 1 Acceptance

**Files:**
- Create: `apps/api/app/calculation_rules/service.py`
- Create: `tests/calculation_rule_test_support.py`
- Create: `tests/test_calculation_rule_service.py`

**Interfaces:**
- Consumes: `ModelExtractionReadService`, repository, inventory, compiler, graph, evaluator, comparator.
- Produces: `CalculationRuleExtractionService.extract_and_execute(model_version_id, workbook_version_id, configuration) -> CalculationRuleExtractionResult`.

- [x] **Step 1: Write service RED tests**

```python
def test_service_returns_maximum_valid_persisted_output_after_restart(context):
    result = service.extract_and_execute(model_id, workbook_id, configuration)
    restarted = restarted_repository.load_result(result.calculation_rule_extraction_id)
    assert restarted == result
    assert result.status == "completed_with_warning"
    assert result.cells_by_address["Calc!B2"].execution_status == "executed"
    assert result.cells_by_address["Calc!B3"].support_status == "unsupported"
```

Cover model/workbook mismatch, exact storage load, canonical output/input mappings and unmapped helpers, completed-run reuse, failed retry identity, external evidence, cycle/blocked cells, summary denominators, source/cache traceability, no snapshot fallback, and independent execution.

- [x] **Step 2: Run service tests and verify RED**

Run: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3 -m pytest tests/test_calculation_rule_service.py -q`

Expected: service import/behavior failures.

- [x] **Step 3: Implement staged orchestration and sanitized failure handling**

Implemented interface: `CalculationRuleExtractionService.extract_and_execute(model_version_id, workbook_version_id, configuration=None) -> CalculationRuleExtractionResult`.

Validate the model/workbook pair before run creation. Commit short persistence stages around workbook parsing/evaluation. Resolve mappings only through `ModelExtractionReadService.resolve_entity_by_source_cell`. Mark task-level failures without discarding prior failed identity.

- [x] **Step 4: Add repository corpus and security regression tests**

Use `Financial_Model_Data.xlsx` plus a structurally different repository workbook fixture. Assert all formulas are inventoried, every whitelist-only formula parses, unsupported formulas remain, internal reference rates use explicit denominators, no parser crash occurs, and no formula string reaches any execution primitive. This repository evidence is one real workbook plus one fixture; the separate two-real-workbook acceptance criterion remains open.

- [x] **Step 5: Run Phase 1 and upstream regression verification**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest \
  tests/test_calculation_rule_inventory.py \
  tests/test_calculation_rule_compiler.py \
  tests/test_calculation_rule_graph.py \
  tests/test_calculation_rule_evaluator.py \
  tests/test_calculation_rule_persistence_schema.py \
  tests/test_calculation_rule_service.py -q
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest \
  tests/test_model_extraction_persistence.py \
  tests/test_model_extraction_persistence_schema.py \
  tests/test_model_extraction_reload.py \
  tests/test_model_extraction_lifecycle.py \
  tests/test_experimental_workbook_upload.py -q
```

Expected: all configured tests pass; PostgreSQL-only tests skip when no isolated URL is supplied.

---

### Task 6: Scope, Migration, and Acceptance Audit

**Files:**
- Modify: `docs/superpowers/plans/2026-07-15-simple-executable-calculation-rule-extraction.md`

- [x] **Step 1: Run static and migration checks**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m compileall -q apps/api/app/calculation_rules
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m alembic -c apps/api/alembic.ini upgrade head
git diff --check
```

Expected: exit 0 for every command.

- [x] **Step 2: Audit the approved acceptance criteria and scope**

Re-read Section 24.2 of the approved design and map every criterion to a passing test/output. Confirm the diff contains no Phase 2 grouping, public API, frontend, Scenario/Sensitivity, LLM, snapshot, or legacy parser behavior changes.

- [x] **Step 3: Record actual verification evidence**

Check completed plan boxes only after the named RED/GREEN or final verification command was observed. Report any unavailable PostgreSQL or external-workbook evidence as an explicit gap rather than implying it passed.

## Verification Evidence (2026-07-15)

- RED was observed independently for inventory, compiler, graph/evaluator, persistence, service, function-registry metadata, sparse scanning, IR tamper checks, aggregate overflow, output-only mapping uniqueness, and recursion-safe SCC handling before the corresponding GREEN changes.
- Full repository suite: `342 passed, 4 skipped` using `.venv_mac/bin/python3`; the remaining warnings are existing Pydantic/openpyxl warnings.
- Focused final Phase 1 suite: `95 passed, 1 skipped`; the skip is the isolated PostgreSQL acceptance test because `TEST_POSTGRES_URL` is unavailable.
- Empty SQLite migration: revisions `20260715_0001 -> 20260715_0002 -> 20260715_0003`; `alembic current` reports `20260715_0003 (head)`.
- Static checks: package `compileall`, `git diff --check`, and production security/scope greps passed.
- Corpus: `Financial_Model_Data.xlsx` inventories 352 formulas, compiles 351 as supported, and retains one unsupported `COUNTIF`; the multilingual fixture inventories and supports all 3 formulas.
- Acceptance gap: the repository contains only one real financial workbook plus fixtures, so the design's two structurally different real-workbook criterion is not claimed.
- Acceptance gap: `TEST_POSTGRES_URL` was unavailable, so the isolated PostgreSQL equivalence test exists but was skipped; SQLite persistence/reload/migration evidence passed.
