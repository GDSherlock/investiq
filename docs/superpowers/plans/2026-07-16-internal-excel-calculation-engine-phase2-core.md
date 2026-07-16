# Internal Excel Calculation Engine Phase 2 Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an additive, independently accepted Phase 2 core that reads preserved Phase 1 artifacts, emits `calc-ir-v2`, executes the repository workbook's `COUNTIF`, persists immutable graph/group/run artifacts, and proves deterministic incremental recalculation with typed overrides.

**Architecture:** Keep every Phase 1 identifier, table meaning, status, and public default unchanged. Add Phase 2 configuration, registry, graph, grouping, persistence, and orchestration modules; the only Phase 1 edits are backward-compatible dependency-injection seams in the compiler/evaluator. Policy-gated capabilities remain disabled: no third-party oracle, volatile functions, iterative execution, dynamic references, external workbook retrieval, or production trace retention expansion.

**Tech Stack:** Python 3.12, dataclasses, openpyxl, SQLAlchemy 2, Alembic, SQLite/PostgreSQL-compatible DDL, pytest.

## Global Constraints

- Work only in `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.claude/worktrees/calculation-rule-extraction-design` on `design/calculation-rule-extraction`.
- Use `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3` for every Python verification command.
- Preserve `calc-ir-v1`, `formula-inventory-v1`, all Phase 1 UUIDv5 inputs, the six Phase 1 table meanings, and all Phase 1 status values.
- Emit `calc-ir-v2`, `formula-compiler-v2`, `calc-engine-v2`, `calc-functions-v2`, and `excel-compatible-v2` only from Phase 2 entry points.
- Add tables and fields; do not repurpose a Phase 1 column or introduce a legacy snapshot fallback.
- Keep iteration disabled, volatile/dynamic/external functions unsupported, and third-party oracles absent.
- Accept typed value overrides only; reject formula text as an override.
- A blocked or cyclic component must not contaminate an independent supported component.
- Do not create a Git commit unless the user explicitly requests one.

## File Responsibility Map

- `apps/api/app/calculation_rules/phase2_types.py`: version constants, configuration, override/run/result contracts, and deterministic Phase 2 identities.
- `apps/api/app/calculation_rules/phase2_registry.py`: immutable `calc-functions-v2` metadata and the first progressive function increment (`COUNT`, `COUNTA`, `COUNTIF`).
- `apps/api/app/calculation_rules/compiler.py`: optional registry injection and strict v2 envelope emission/validation while retaining v1 defaults.
- `apps/api/app/calculation_rules/evaluator.py`: optional registry/input/prior-value injection while retaining v1 defaults.
- `apps/api/app/calculation_rules/phase2_graph.py`: immutable graph version, all-SCC classification, topological layers, dirty propagation, and reuse planning.
- `apps/api/app/calculation_rules/phase2_grouping.py`: deterministic model-scoped grouping of contiguous copied formulas with cell evidence retained.
- `apps/api/app/calculation_rules/phase2_models.py`: eight additive target-state SQLAlchemy tables.
- `apps/api/app/calculation_rules/phase2_repository.py`: idempotent graph/group/run persistence and reload.
- `apps/api/app/calculation_rules/phase2_service.py`: `compile_workbook` and `calculate_model` orchestration over canonical reads.
- `apps/api/alembic/versions/20260716_0004_internal_calculation_engine.py`: forward/backward SQLite/PostgreSQL-compatible Phase 2 schema migration.
- `apps/api/alembic/env.py`, `apps/api/app/main.py`: register Phase 2 metadata at migration and startup boundaries.
- `tests/test_calculation_engine_v2_compiler.py`: v1 compatibility, v2 envelope, registry, criteria, and evaluator conformance.
- `tests/test_calculation_engine_v2_graph.py`: graph identity, SCCs, layers, dirty propagation, and deterministic reuse.
- `tests/test_calculation_engine_v2_grouping.py`: grouping fingerprint, continuity, formula breaks, and retry stability.
- `tests/test_calculation_engine_v2_persistence_schema.py`: exact eight-table schema, constraints, migration, idempotency, and restart reload.
- `tests/test_calculation_engine_v2_service.py`: compile/calculate contracts, cell/canonical overrides, maximum-valid output, incremental reuse, and idempotency.
- `docs/reports/2026-07-16-phase-2-calculation-engine-acceptance.md`: final commands, counts, real-workbook evidence, limitations, and decision.

---

### Task 1: Versioned IR and Progressive Function Registry

**Files:**
- Create: `apps/api/app/calculation_rules/phase2_types.py`
- Create: `apps/api/app/calculation_rules/phase2_registry.py`
- Modify: `apps/api/app/calculation_rules/compiler.py`
- Modify: `apps/api/app/calculation_rules/evaluator.py`
- Test: `tests/test_calculation_engine_v2_compiler.py`

**Interfaces:**
- Consumes: `WorkbookFormulaInventory`, `FormulaCompiler`, `CalculationExpressionValidator`, `SafeCalculationEvaluator`, `FormulaCompilation`, and Phase 1 function definitions.
- Produces: `Phase2CalculationConfiguration`, `PHASE2_FUNCTION_REGISTRY`, v2-compatible compiler/validator seams, and an evaluator capable of `COUNT`, `COUNTA`, and `COUNTIF` without changing Phase 1 defaults.

- [x] **Step 1: Write failing compatibility and v2 compiler tests**

```python
def test_v2_compiler_emits_additive_envelope_and_v1_remains_byte_stable():
    v1 = compile_formula("=SUM(Inputs!A1:A2)")
    v2 = compile_formula("=COUNTIF(Inputs!A1:A2,\">0\")", phase2=True)
    assert set(v1.ir_json) == {
        "expression_id", "formula_cell_id", "ir_version", "compiler_version",
        "semantics_profile", "formula_sha256", "normalized_signature", "root",
    }
    assert v2.ir_json["ir_version"] == "calc-ir-v2"
    assert v2.ir_json["required_registry_version"] == "calc-functions-v2"
    assert v2.ir_json["capabilities"] == ["conditional-aggregation"]
    assert v2.ir_json["limits"]["node_count"] > 0

def test_v2_countif_matches_numeric_comparison_criteria():
    execution = evaluate_v2("=COUNTIF(Inputs!A1:A3,\">=2\")", [1, 2, 3])
    assert execution.value == ScalarValue.number(2)
```

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_compiler.py
```

Expected: collection or assertions fail because the Phase 2 configuration, registry, envelope fields, and evaluator semantics do not exist.

- [x] **Step 3: Add exact Phase 2 contracts and deterministic identities**

Implement these public signatures in `phase2_types.py`:

```python
@dataclass(frozen=True)
class Phase2CalculationConfiguration:
    inventory_version: str = "formula-inventory-v1"
    ir_version: str = "calc-ir-v2"
    compiler_version: str = "formula-compiler-v2"
    engine_version: str = "calc-engine-v2"
    function_registry_version: str = "calc-functions-v2"
    semantics_profile: str = "excel-compatible-v2"
    grouping_profile: str = "relative-ast-v1"
    max_formula_length: int = 8192
    max_tokens: int = 2048
    max_nodes: int = 2048
    max_depth: int = 128
    max_arguments: int = 255
    max_range_cells: int = 10000
    max_formula_count: int = 100000
    max_total_edges: int = 1000000
    max_trace_inputs: int = 256
    absolute_tolerance: float = 1e-9
    relative_tolerance: float = 1e-9

    @property
    def configuration_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

Add deterministic helpers for graph, group, and run IDs using the exact tuples from the approved target design.

- [x] **Step 4: Add the immutable v2 registry and compiler/validator injection seams**

`PHASE2_FUNCTION_REGISTRY` must copy Phase 1 definitions and add exact metadata for:

```python
{
    "COUNT": FunctionDefinition("COUNT", 0, 255, kinds, True, False, False, "count-v2", "excel-compatible-v2"),
    "COUNTA": FunctionDefinition("COUNTA", 0, 255, kinds, True, False, False, "counta-v2", "excel-compatible-v2"),
    "COUNTIF": FunctionDefinition("COUNTIF", 2, 2, kinds, True, False, False, "countif-v2", "excel-compatible-v2"),
}
```

Keep `FormulaCompiler()` and `CalculationExpressionValidator()` on the Phase 1 registry by default. Add keyword-only registry injection, and emit/accept `required_registry_version`, `capabilities`, and `limits` only when `ir_version == "calc-ir-v2"`.

- [x] **Step 5: Implement v2 evaluator semantics without changing v1 defaults**

Add keyword-only registry injection and implement criteria parsing with these behaviors:

```python
parse_countif_criterion(">=2")(ScalarValue.number(2)) is True
parse_countif_criterion("<>0")(ScalarValue.blank()) is False
parse_countif_criterion("text")(ScalarValue.text("TEXT")) is True
```

`COUNT` counts numeric/date values, `COUNTA` counts non-blank values, and `COUNTIF` requires a range plus scalar criterion. Excel errors in the criteria range propagate as typed errors; unsupported wildcard/locale behavior returns explicit `#VALUE!` rather than guessing.

- [x] **Step 6: Run v2 and Phase 1 regression tests and verify GREEN**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_compiler.py tests/test_calculation_rule_compiler.py tests/test_calculation_rule_evaluator.py
```

Expected: all selected tests pass; Phase 1 default registry/envelope assertions remain unchanged.

### Task 2: Immutable Graph Versions, SCCs, and Dirty Propagation

**Files:**
- Create: `apps/api/app/calculation_rules/phase2_graph.py`
- Test: `tests/test_calculation_engine_v2_graph.py`

**Interfaces:**
- Consumes: `CalculationGraphPlan`, `WorkbookCatalog`, `FormulaCompilation`, `WorkbookCellRef`, and Phase 2 configuration.
- Produces: `CalculationGraphVersion`, `CalculationGraphComponent`, `DirtyPropagationPlan`, `VersionedCalculationGraphBuilder.build`, and `DirtyPropagator.plan`.

- [x] **Step 1: Write failing graph-version and incremental-plan tests**

```python
def test_graph_version_classifies_every_scc_and_is_retry_stable():
    first = build_versioned_graph()
    second = build_versioned_graph()
    assert first.id == second.id
    assert first.content_fingerprint == second.content_fingerprint
    assert {item.classification for item in first.components} >= {
        "acyclic_singleton", "multi_cell_cycle", "blocked_unsupported",
    }

def test_dirty_propagation_recalculates_only_transitive_dependents():
    plan = dirty_plan(changed={cell("Inputs", "A1")}, has_prior_run=True)
    assert cell("Calc", "B1") in plan.dirty_formula_cells
    assert cell("Calc", "B2") in plan.dirty_formula_cells
    assert cell("Hidden", "C1") in plan.reusable_formula_cells
```

- [x] **Step 2: Run the graph test and verify RED**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_graph.py
```

Expected: import or assertions fail because versioned graph and dirty propagation contracts do not exist.

- [x] **Step 3: Implement immutable graph identity and all-SCC classification**

Canonicalize nodes and edges as sorted workbook-cell identity tuples, hash the compiler/IR/registry/semantics manifest plus graph payload, and create:

```python
graph_version_id = uuid.uuid5(
    uuid.UUID(workbook_version_id),
    compiler_manifest_hash,
)
```

Every formula node belongs to exactly one deterministic SCC component. Classifications are `acyclic_singleton`, `self_reference`, `multi_cell_cycle`, or `blocked_unsupported`; iteration remains disabled.

- [x] **Step 4: Implement topological layers and dirty/reuse planning**

For a cold run, mark every `ready` formula dirty. For a compatible prior run, breadth-first traverse `dependents_by_cell` from changed input cells. Return sorted dirty and reusable formula-cell tuples; cycles/blocked nodes remain status evidence and are never marked reusable values.

- [x] **Step 5: Run graph and Phase 1 graph regression tests and verify GREEN**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_graph.py tests/test_calculation_rule_graph.py
```

Expected: all selected tests pass and Phase 1 graph ordering remains unchanged.

### Task 3: Model-Scoped Business-Rule Grouping

**Files:**
- Create: `apps/api/app/calculation_rules/phase2_grouping.py`
- Test: `tests/test_calculation_engine_v2_grouping.py`

**Interfaces:**
- Consumes: formula-cell records, `normalized_signature`, resolved references, model version, and grouping profile.
- Produces: immutable `GroupedCalculationRule`, ordered `CalculationRuleMember`, explicit formula-break evidence, and deterministic group IDs.

- [x] **Step 1: Write failing grouping tests**

```python
def test_grouping_combines_contiguous_period_formulas_without_losing_members():
    groups = group_formulas("=C5*C6", "=D5*D6", "=E5*E6")
    assert len(groups) == 1
    assert [member.cell_address for member in groups[0].members] == ["C10", "D10", "E10"]
    assert all(member.formula_cell_id for member in groups[0].members)

def test_grouping_records_hardcode_break_and_identity_is_retry_stable():
    first = group_with_hardcode_break()
    second = group_with_hardcode_break()
    assert first.id == second.id
    assert first.exceptions == ({"cell_address": "F10", "reason": "hardcode_break"},)
```

- [x] **Step 2: Run the grouping test and verify RED**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_grouping.py
```

Expected: import or assertions fail because no Phase 2 grouping module exists.

- [x] **Step 3: Implement deterministic grouping and evidence retention**

Group only supported formulas with identical normalized signatures on the same sheet and a contiguous row or column axis. Require at least two members. The group fingerprint includes model version, grouping profile, normalized signature, orientation, and exact ordered member evidence; the member's absolute period coordinate is excluded from the normalized expression but retained on every member row.

- [x] **Step 4: Keep semantic labels policy-neutral**

Set generated labels to stable technical labels such as `Copied formula: <sheet>!<first>:<last>`, confidence from deterministic evidence only, and approval status `unreviewed`. Do not infer business prose or approve a group automatically.

- [x] **Step 5: Run grouping tests and verify GREEN**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_grouping.py
```

Expected: all grouping tests pass with stable identities and complete member evidence.

### Task 4: Additive Phase 2 Persistence and Migration

**Files:**
- Create: `apps/api/app/calculation_rules/phase2_models.py`
- Create: `apps/api/app/calculation_rules/phase2_repository.py`
- Create: `apps/api/alembic/versions/20260716_0004_internal_calculation_engine.py`
- Modify: `apps/api/alembic/env.py`
- Modify: `apps/api/app/main.py`
- Test: `tests/test_calculation_engine_v2_persistence_schema.py`

**Interfaces:**
- Consumes: Phase 1 workbook/model/formula tables and Phase 2 graph/group/run dataclasses.
- Produces: exact additive tables `workbook_named_expressions`, `calculation_graph_versions`, `calculation_graph_components`, `grouped_calculation_rules`, `calculation_rule_members`, `calculation_rule_dependencies`, `calculation_runs`, and `calculation_run_values`; `Phase2CalculationRepository` save/load methods.

- [x] **Step 1: Write failing exact-schema and restart tests**

```python
def test_metadata_contains_exact_eight_phase2_tables():
    expected = {
        "workbook_named_expressions", "calculation_graph_versions",
        "calculation_graph_components", "grouped_calculation_rules",
        "calculation_rule_members", "calculation_rule_dependencies",
        "calculation_runs", "calculation_run_values",
    }
    assert expected <= set(Base.metadata.tables)

def test_phase2_artifacts_are_idempotent_and_reload_after_restart(context):
    first = context.persist_fixture()
    second = context.persist_fixture()
    assert first.graph_version_id == second.graph_version_id
    assert context.restart().load_run(first.calculation_run_id) == first
```

- [x] **Step 2: Run the persistence test and verify RED**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_persistence_schema.py
```

Expected: the eight tables and repository do not exist.

- [x] **Step 3: Add SQLAlchemy models and constraints**

Use UUID string primary keys, named foreign keys, deterministic uniqueness constraints, relational query keys, bounded JSON payloads, and status checks. `calculation_runs.status` accepts `pending`, `running`, `completed`, `completed_with_warning`, `failed`, and `cancelled`; `calculation_run_values.execution_status` preserves Phase 1 values and additively accepts `reused`, `cached_comparison_only`, `iteration_converged`, `iteration_not_converged`, and `unavailable`.

- [x] **Step 4: Add the `20260716_0004` migration and metadata imports**

Set `down_revision = "20260715_0003"`. Upgrade creates parent tables before children and indexes deterministic lookup paths. Downgrade drops children before parents. Import `phase2_models` from Alembic env and API startup so `Base.metadata` is complete without feature-first imports.

- [x] **Step 5: Implement idempotent repository writes and restart reads**

Graph/group writes compare immutable identity payloads and reject mismatches. A run is keyed by model, graph, registry, normalized override hash, and policy hash. Terminal result rows are inserted atomically with the terminal run state; a failed write rolls back without exposing partial success.

- [x] **Step 6: Run SQLite migration, persistence, and Phase 1 schema tests and verify GREEN**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_persistence_schema.py tests/test_calculation_rule_persistence_schema.py tests/test_model_extraction_persistence_schema.py
```

Expected: all selected tests pass and Alembic head is `20260716_0004`.

### Task 5: Compile and Calculate Service Contracts

**Files:**
- Create: `apps/api/app/calculation_rules/phase2_service.py`
- Modify: `apps/api/app/calculation_rules/__init__.py`
- Test: `tests/test_calculation_engine_v2_service.py`

**Interfaces:**
- Consumes: canonical `ModelExtractionReadService`, Phase 1 inventory/persistence, v2 compiler/evaluator/graph/group/repository, typed overrides, and run policy.
- Produces: `InternalCalculationEngineService.compile_workbook(...) -> CompilationResult` and `calculate_model(...) -> CalculationRunResult`.

- [x] **Step 1: Write failing cold-run, override, reuse, idempotency, and failure tests**

```python
def test_phase2_cold_run_executes_countif_and_preserves_maximum_valid_output(context):
    result = context.service.calculate_model(context.model.id)
    assert result.ir_version == "calc-ir-v2"
    assert result.cells_by_address["Calc!B3"].value == ScalarValue.number(2)
    assert result.cells_by_address["Calc!B4"].value == ScalarValue.number(3)
    assert result.cells_by_address["Calc!B5"].status == "cycle"
    assert result.cells_by_address["Calc!B7"].status == "not_executable"

def test_parameter_override_dirties_dependents_and_reuses_independent_cells(context):
    baseline = context.service.calculate_model(context.model.id)
    changed = context.service.calculate_model(
        context.model.id,
        overrides=[CalculationOverride.parameter(context.parameter.id, 10)],
    )
    assert changed.cells_by_address["Calc!B2"].value == ScalarValue.number(26)
    assert changed.cells_by_address["Hidden!C1"].status == "reused"
    assert changed.reused_formula_cells > 0
    assert changed.calculation_run_id != baseline.calculation_run_id
```

- [x] **Step 2: Run the service test and verify RED**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_service.py
```

Expected: service, override, and result contracts do not exist.

- [x] **Step 3: Implement deterministic workbook compilation**

`compile_workbook` loads SHA-verified bytes, inventories with the preserved Phase 1 inventory version, compiles with the v2 registry, persists v2 rules alongside v1 rules, builds/persists the graph, and returns support counts. Equivalent requests reload the same graph identity.

- [x] **Step 4: Implement typed override resolution and safe run orchestration**

Canonical parameter overrides must resolve to a parameter owned by the requested model and then to its exact source cell. Cell overrides must identify a cell in the selected workbook. Reject formula text, foreign model entities, ambiguous canonical cells, unknown value types, and non-finite numbers before creating a run.

- [x] **Step 5: Implement incremental reuse and terminal result persistence**

Select only a completed compatible prior run. Seed non-dirty ready formulas from prior run values, evaluate dirty layers with exact overrides, mark reused rows `reused`, preserve Phase 1 blocked/cycle/not-executable meanings, canonicalize persistence order by cell identity, and return dirty/reuse metrics plus bounded warnings.

- [x] **Step 6: Implement idempotent retry and sanitized failure behavior**

Equivalent normalized inputs return the same terminal run. Deterministic parse, override, cycle-policy, and calculation errors are non-retryable evidence. Unexpected failures set `CALCULATION_ENGINE_V2_FAILED` with a sanitized message and leave the SQLAlchemy session reusable.

- [x] **Step 7: Run Phase 2 service and Phase 1 service regressions and verify GREEN**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_service.py tests/test_calculation_rule_service.py
```

Expected: all selected tests pass; Phase 1 keeps `COUNTIF` unsupported while Phase 2 executes it.

### Task 6: Acceptance Audit and Durable Evidence

**Files:**
- Create: `docs/reports/2026-07-16-phase-2-calculation-engine-acceptance.md`
- Modify if required by PostgreSQL cleanup fixture: `tests/test_model_extraction_lifecycle.py`

**Interfaces:**
- Consumes: the approved Phase 2 design, this plan, complete test output, SQLite migration, optional isolated PostgreSQL verification, and the repository `Financial_Model_Data.xlsx` corpus.
- Produces: an evidence-backed PASS/FAIL report with exact commands, metrics, remaining policy gates, and file/diff scope.

- [x] **Step 1: Run the Phase 2 focused suite**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q tests/test_calculation_engine_v2_compiler.py tests/test_calculation_engine_v2_graph.py tests/test_calculation_engine_v2_grouping.py tests/test_calculation_engine_v2_persistence_schema.py tests/test_calculation_engine_v2_service.py
```

Expected: zero failures.

- [x] **Step 2: Run the complete repository regression suite**

Run:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q
```

Expected: zero failures; only environment-gated PostgreSQL skips are allowed and must be listed.

- [x] **Step 3: Run real-workbook Phase 2 corpus acceptance**

Compile and evaluate `Financial_Model_Data.xlsx` through the Phase 2 registry. Verify exact formula inventory count, `calc-ir-v2` for supported formulas, `Checks!D16` `COUNTIF` execution, no raw-string evaluation, no external fetching, and no Phase 1 row mutation.

- [x] **Step 4: Run migration and PostgreSQL verification where an isolated test database is available**

Upgrade empty SQLite to head, downgrade to `20260715_0003`, and upgrade again. If `TEST_POSTGRES_URL` identifies an isolated database, run all PostgreSQL-marked Phase 2/Model Extraction tests; otherwise record the skip without claiming PostgreSQL acceptance.

- [x] **Step 5: Audit frozen contracts and scope**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Compare Phase 1 constants, UUID inputs, six table names, status sets, and v1 envelope tests against the pre-change baseline. Confirm no main-worktree file was modified.

- [x] **Step 6: Write the acceptance report and rerun its cited commands**

The report must distinguish implemented capabilities from policy-gated/deferred target features and end with `PASS` only if every cited local command has fresh zero-failure evidence.

## Plan Self-Review

- Spec coverage: v2 IR, progressive registry, graph versions/SCCs, dirty propagation, grouping, eight additive tables, run/result contracts, compatibility, security boundaries, and acceptance evidence each map to a task.
- Placeholder scan: no implementation placeholder or unnamed error-handling step remains.
- Type consistency: the same version strings, deterministic IDs, override types, graph/group/run identities, statuses, and public service signatures are used throughout.
- Scope: this is the policy-neutral Phase 2 core increment; oracle, iterative/volatile/dynamic behavior, full function-family breadth, named/table execution, and What-If Data Tables remain explicitly outside this implementation.
