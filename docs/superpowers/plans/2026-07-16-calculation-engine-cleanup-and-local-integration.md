# Calculation Engine Cleanup and Local Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this plan inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the internal maintainability of the accepted Phase 1 and Phase 2 calculation engine without changing any public contract, persisted meaning, calculation result, or runtime behavior, then verify and merge it into local `main` without pushing.

**Architecture:** Preserve the Phase 1 preparation/compilation path and the Phase 2 calculation-run path as separate responsibilities. Limit production edits to shared constants, shared timestamp plumbing, exact internal types, private naming, and an equivalent queue implementation; document future Excel/project-finance coverage separately from runtime code.

**Tech Stack:** Python 3.12, dataclasses, openpyxl, SQLAlchemy 2, Alembic, pytest, Git linked worktrees.

## Global Constraints

- Work only in `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.claude/worktrees/calculation-rule-extraction-design` on `design/calculation-rule-extraction` until the local merge step.
- Use `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3` for Python verification.
- Do not change formula semantics, IR/registry/version values, deterministic UUID/hash inputs, override normalization, typed values, blank/error handling, `COUNTIF`, lazy `IF`, graph ordering, dirty propagation, reuse, idempotency, transaction behavior, or failure sanitization.
- Do not modify, rename, squash, or remove Alembic migrations or change any table, column, constraint, status, or database meaning.
- Preserve the Model Extraction persistence/reload/upload contracts and the accepted Phase 1 default behavior.
- Do not implement the deferred function pack, named/table execution, dynamic arrays, iterative calculation, APIs, upload orchestration, frontend work, Scenario, Sensitivity, or Monte Carlo.
- Do not stage or commit user-owned files from the original `main` worktree, and do not push.

---

### Task 1: Centralize Phase 2 Version Identifiers

**Classification:** duplication removal

**Why:** `phase2_types.py` repeats the same registered version strings in dataclass defaults and validation, while `phase2_registry.py` separately declares the registry/semantics strings. One internal source reduces drift without changing emitted values.

**Files:**
- Modify: `apps/api/app/calculation_rules/phase2_types.py`
- Modify: `apps/api/app/calculation_rules/phase2_registry.py`
- Verify: `tests/test_calculation_engine_v2_compiler.py`

**Protected contracts:** Every existing version string remains byte-for-byte identical; `calc-ir-v1` stays the shared compiler/evaluator default; `phase2_registry.PHASE2_FUNCTION_REGISTRY_VERSION` remains importable.

- [ ] Define named Phase 2 constants in `phase2_types.py` for inventory, IR, compiler, engine, function registry, semantics, and grouping profiles.
- [ ] Use the constants in `Phase2CalculationConfiguration` defaults and its registered-version validation.
- [ ] Import and reuse registry/semantics constants in `phase2_registry.py` without changing registry entries.
- [ ] Run the v2 compiler suite and the Phase 1 compiler/evaluator suites.

### Task 2: Remove Duplicate UTC Timestamp Implementations

**Classification:** duplication removal and module-boundary cleanup

**Why:** Phase 1 models, Phase 2 models, and both repositories contain four equivalent timezone-aware `datetime.now(timezone.utc)` helpers. The SQLAlchemy model helper is already the persistence-layer source.

**Files:**
- Modify: `apps/api/app/calculation_rules/phase2_models.py`
- Modify: `apps/api/app/calculation_rules/repository.py`
- Modify: `apps/api/app/calculation_rules/phase2_repository.py`
- Verify: `tests/test_calculation_rule_persistence_schema.py`
- Verify: `tests/test_calculation_engine_v2_persistence_schema.py`
- Verify: `tests/test_calculation_engine_v2_service.py`

**Protected contracts:** Timestamps remain timezone-aware UTC; model defaults, retry timestamps, completion timestamps, rollback behavior, and persisted columns remain unchanged.

- [ ] Reuse `apps.api.app.calculation_rules.models.utcnow` in the Phase 2 model module while retaining the existing `phase2_models.utcnow` name as an alias.
- [ ] Replace the two repository-private duplicate helpers with the shared model helper.
- [ ] Remove only imports made unreachable by this consolidation.
- [ ] Run Phase 1 and Phase 2 persistence/service suites.

### Task 3: Tighten Internal Types and Private Naming

**Classification:** type-safety improvement and naming/readability

**Why:** Registry injection is currently typed as `Mapping[str, Any]`, a persisted-value lookup returns `Any`, and `_override_value` does not state that it normalizes and validates typed override values.

**Files:**
- Modify: `apps/api/app/calculation_rules/compiler.py`
- Modify: `apps/api/app/calculation_rules/evaluator.py`
- Modify: `apps/api/app/calculation_rules/phase2_repository.py`
- Modify: `apps/api/app/calculation_rules/phase2_service.py`
- Modify: `apps/api/app/calculation_rules/phase2_types.py`
- Verify: `tests/test_calculation_rule_compiler.py`
- Verify: `tests/test_calculation_rule_evaluator.py`
- Verify: `tests/test_calculation_engine_v2_compiler.py`
- Verify: `tests/test_calculation_engine_v2_service.py`

**Protected contracts:** No public signature, accepted exception, normalized payload, scalar conversion, or persisted DTO field changes.

- [ ] Type registry injection as `Mapping[str, FunctionDefinition]` in compiler, parser, validator, and evaluator internals.
- [ ] Type repository cell serialization as `WorkbookCellRef` and prior-run lookup values as `PersistedCalculationRunValue`.
- [ ] Rename `_override_value` to `_normalize_override_value` and update only its private callers.
- [ ] Run compiler, evaluator, and Phase 2 service suites.

### Task 4: Simplify Dirty-Propagation Queue Mechanics

**Classification:** module-boundary cleanup

**Why:** `DirtyPropagator.plan()` implements FIFO traversal with `list.pop(0)`. `collections.deque.popleft()` expresses the queue contract directly and avoids repeated list shifts while preserving traversal and sorted output.

**Files:**
- Modify: `apps/api/app/calculation_rules/phase2_graph.py`
- Verify: `tests/test_calculation_engine_v2_graph.py`
- Verify: `tests/test_calculation_rule_graph.py`

**Protected contracts:** Changed/dirty/reusable membership, dependency direction, BFS semantics, SCC classification, topological layers, and deterministic output order remain identical.

- [ ] Replace the local list queue with `deque` and `popleft()`.
- [ ] Run Phase 1 and Phase 2 graph tests.

### Task 5: Document Deferred Calculation Coverage

**Classification:** documentation cleanup

**Why:** The target design contains a broad capability roadmap, but integration needs one concise source distinguishing implemented scope from explicitly deferred Excel/project-finance work and future IRR/XIRR conformance gates.

**Files:**
- Create: `docs/calculation-engine-backlog.md`

**Protected contracts:** Documentation only; no runtime registry or feature flag changes.

- [ ] Record current Phase 1/Phase 2 scope and the exact deferred project-finance/date/supporting-function priorities.
- [ ] Record deferred general Excel compatibility: complete named-range execution, structured references, dynamic arrays, broader functions, and iterative circular calculation.
- [ ] Record deterministic convergence, error, date-basis, tolerance, and Excel-compatibility test requirements for future `IRR` and `XIRR`.
- [ ] Confirm every deferred function remains absent from the calculation function registry.

### Task 6: Verify, Commit, and Merge Locally

**Classification:** documentation cleanup and verification

**Affected tests:** No test file is intentionally changed. Existing Phase 1, Phase 2, Model Extraction, PostgreSQL, real-workbook, and override tests prove equivalence.

- [ ] Run `python -m compileall apps tests` and `git diff --check`.
- [ ] Run focused Phase 1 and focused Phase 2 suites.
- [ ] Run Model Extraction persistence, reload, lifecycle, storage, and upload regressions.
- [ ] Run the full repository suite.
- [ ] Run `pytest -q -m postgres` with an isolated `TEST_POSTGRES_URL`; verify Alembic head `20260716_0004`, rollback, reload, typed-value round trips, and idempotency; delete only that isolated database.
- [ ] Re-run the persisted real-workbook and override regression without upload or Azure calls.
- [ ] Review `git status`, `git diff --stat`, `git diff`, and `git diff --check`; confirm no migration, generated artifact, secret, or unrelated change.
- [ ] Stage intentional cleanup/plan/backlog files only and commit `refactor(calculation): clean calculation engine implementation`.
- [ ] Fetch refs and review any `main` movement.
- [ ] Preserve the original untracked report and verified Excel lock file outside `main` only while needed; do not stage them.
- [ ] Merge with `--no-ff` unless repository policy requires otherwise, rerun focused Phase 1/Phase 2 tests plus compile/diff checks on merged `main`, restore user files exactly, and do not push or delete the source branch.

## Plan Self-Review

- Scope coverage: every selected production edit maps to a named cleanup category and an existing focused regression suite.
- Protected contracts: formulas, versions, statuses, IDs, database schema, migrations, public interfaces, persistence, and Model Extraction behavior are explicitly frozen.
- Placeholder scan: no implementation placeholder, deferred runtime work, or unnamed verification step remains.
- Merge safety: Phase 2 baseline and cleanup remain separate commits; user-owned files are preserved outside the calculation commit; no push or branch deletion is allowed.
