# Phase 1 Calculation Rule Extraction Acceptance Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this verification plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce complete, reproducible Phase 1 acceptance evidence against an existing materialized model and its immutable persisted workbook.

**Architecture:** Run the public `CalculationRuleExtractionService.extract_and_execute` contract directly against the active database, then independently inspect persisted relational rows and workbook XML/openpyxl content. Use repository tests for isolated failure and PostgreSQL behavior, and write a durable acceptance report without changing production code.

**Tech Stack:** Python 3.12, SQLAlchemy, Alembic, openpyxl, pytest, SQLite/PostgreSQL, InvestIQ canonical persistence services.

## Global Constraints

- Work only in branch `design/calculation-rule-extraction` and its existing linked worktree.
- Do not merge, push, commit, invoke the upload endpoint, connect Phase 1 to upload, redesign architecture, expand the whitelist, or modify Phase 2.
- Do not modify production code unless a reproducible test exposes a real implementation defect; if that happens, stop and use systematic debugging plus RED-GREEN TDD.
- Do not rerun LLM Model Extraction unless the selected persisted model is invalid or missing.
- Do not use `extraction_snapshot_json`, API `final_extraction`, or LLM traces as Phase 1 input or evidence.
- Use only `ModelExtractionReadService`, `DatabaseWorkbookStorage`, canonical relational tables, and workbook bytes selected by `workbook_version_id`.
- Leave unrelated untracked files untouched and redact database passwords from all output.
- Do not intentionally corrupt the active acceptance database; destructive failure cases run only in isolated test databases/transactions.

## File Structure

- Create: `/tmp/investiq_phase1_acceptance.py` — ephemeral evidence collector that calls the public service, independently inspects workbook formula inventory, reloads persisted rows, and emits JSON.
- Create: `/tmp/investiq_phase1_acceptance.json` — machine-readable evidence from the active acceptance database.
- Create: `docs/reports/2026-07-16-phase-1-calculation-rule-acceptance.md` — concise durable acceptance report and final decision.
- Do not modify: `apps/api/app/**`, `apps/api/alembic/**`, `tests/**`, or Phase 2 code unless a defect is first reproduced by a failing test.

---

### Task 1: Environment and Upstream Model Gate

**Files:**
- Read: `.env`, `apps/api/app/database.py`, `apps/api/alembic.ini`, `apps/api/alembic/versions/20260715_0003_calculation_rule_extraction.py`
- Read: `apps/api/app/model_extraction_models.py`

**Interfaces:**
- Consumes: repository/worktree metadata and active SQLAlchemy configuration.
- Produces: redacted environment evidence plus the newest `materialized` model with a valid workbook.

- [ ] **Step 1: Capture repository and worktree provenance**

Run: `git rev-parse --show-toplevel && git branch --show-current && git rev-parse HEAD && git status --short --branch`

Expected: the requested linked worktree, branch `design/calculation-rule-extraction`, and no unrelated mutations.

- [ ] **Step 2: Capture database and migration state without exposing credentials**

Use SQLAlchemy URL parsing to render `driver://user:***@host:port/database`, then run Alembic `current` and `heads` with the active URL.

Expected: active database dialect identified and Alembic current/head `20260715_0003`.

- [ ] **Step 3: Select the newest suitable upstream model**

Query `ModelVersion` joined to `WorkbookVersion` for `status == "materialized"`, newest first. Confirm workbook bytes via `ModelExtractionReadService(session, DatabaseWorkbookStorage(session)).load_workbook_version(workbook_id)` and report IDs, filename, SHA-256, parameter/series/value counts.

Expected: one real materialized model whose persisted workbook bytes pass size and digest verification.

### Task 2: Active-Database Phase 1 Execution and Inventory Evidence

**Files:**
- Create: `/tmp/investiq_phase1_acceptance.py`
- Create: `/tmp/investiq_phase1_acceptance.json`
- Read: `apps/api/app/calculation_rules/service.py`
- Read: `apps/api/app/calculation_rules/models.py`

**Interfaces:**
- Consumes: selected `model_version_id`, `workbook_version_id`, `SessionLocal`, `DatabaseWorkbookStorage`, and `ModelExtractionReadService`.
- Produces: first/second public-service DTOs, pre/post table counts, workbook formula inventory, and persisted representative rows.

- [ ] **Step 1: Record pre-run scoped counts**

Count `calculation_rule_extractions`, `workbook_formula_cells`, `executable_formula_rules`, `formula_references`, `formula_canonical_mappings`, and `formula_execution_results` with workbook/model/run scoping matching each table.

- [ ] **Step 2: Run the public Phase 1 service once**

```python
session = SessionLocal()
storage = DatabaseWorkbookStorage(session)
read_service = ModelExtractionReadService(session, storage)
result = CalculationRuleExtractionService(session, read_service).extract_and_execute(
    model_version_id=model_version_id,
    workbook_version_id=workbook_version_id,
)
```

Capture run ID, status, versions/profile, summary, and warning codes. Do not call any private method or HTTP endpoint.

- [ ] **Step 3: Independently count explicit workbook formulas**

Load workbook bytes only through `DatabaseWorkbookStorage`; inspect all visible, hidden, and very-hidden sheets. Use formula-preserving workbook/XML data for exact formulas and a separate cached-value view where available. Count formula cells without coercing missing cached values to zero.

Expected: actual explicit formula count equals `workbook_formula_cells` for the selected workbook.

- [ ] **Step 4: Reload through a new SQLAlchemy session**

Close the first session, create a new `SessionLocal`, reload the run and all six table families, and prove the records remain readable without rerunning extraction or compilation.

### Task 3: Compiler, IR, References, Graph, Execution, and Mapping Validation

**Files:**
- Read: `apps/api/app/calculation_rules/compiler.py`
- Read: `apps/api/app/calculation_rules/graph.py`
- Read: `apps/api/app/calculation_rules/evaluator.py`
- Read: `apps/api/app/calculation_rules/repository.py`
- Update: `/tmp/investiq_phase1_acceptance.json`

**Interfaces:**
- Consumes: persisted Phase 1 rows and immutable workbook bytes.
- Produces: grouped counts, invariant checks, representative formula/IR/reference/mapping/result evidence, and a complete mismatch list.

- [ ] **Step 1: Validate compilation and calc-ir-v1 invariants**

Group by `parse_status` and `support_status`; assert supported rows are parsed with valid non-null `ir_json`, unsupported rows retain exact formula/reason with null executable IR, and external references are not internalized. Select representatives for arithmetic, cross-sheet, range aggregation, comparison, IF, postfix percent, and unsupported functions when present.

- [ ] **Step 2: Validate graph/reference behavior**

Group reference counts by resolution and kind; inspect direct targets, bounded-range completeness, precedent-to-dependent direction, no internal edges for external references, unsupported dependency isolation, independent supported subgraphs, deterministic cycles, and IF static dependencies versus runtime input trace.

- [ ] **Step 3: Validate every terminal execution result**

Group by `execution_status` and `validation_status`; enumerate every comparable executed row with calculated/cached values and errors, list every mismatch individually, preserve cache freshness, and verify one terminal result per formula cell.

- [ ] **Step 4: Validate canonical mappings without treating incomplete coverage as failure**

Group mappings by role/status/entity kind. Locate examples of parameter output, series-value output, mapped input, and an unmapped helper cell; prove an unmapped helper executes when workbook dependencies are available. Record any unavailable example as an evidence limitation rather than fabricate it.

### Task 4: Idempotency, Same-Workbook Model Isolation, and Restart

**Files:**
- Update: `/tmp/investiq_phase1_acceptance.json`

**Interfaces:**
- Consumes: selected IDs and first-run evidence.
- Produces: deterministic second-run evidence and optional alternate-model evidence.

- [ ] **Step 1: Run the identical request a second time**

Call the same public service with the same default configuration. Compare DTOs, run IDs, and before/after scoped counts.

Expected: same deterministic run ID; no duplicate inventory, compilation, references, mappings, or execution results; equivalent DTO.

- [ ] **Step 2: Test a second real materialized model for the same workbook if available**

If present, run Phase 1 for that model and prove workbook-scoped inventory/compiler/reference reuse with separate run/mapping/result rows. If absent, report `not available`.

- [ ] **Step 3: Verify restart/reload boundaries**

Reload the completed run from a fresh session and scan downstream Phase 1 readers for prohibited snapshot/API/LLM trace access.

### Task 5: Failure Isolation, PostgreSQL, Migration, and Regression Suites

**Files:**
- Read: `tests/test_calculation_rule_service.py`
- Read: `tests/test_calculation_rule_persistence_schema.py`
- Read: `tests/test_model_extraction_*.py`

**Interfaces:**
- Consumes: existing isolated pytest fixtures and `TEST_POSTGRES_URL` if configured.
- Produces: exact command outputs and pass/fail/skip counts.

- [ ] **Step 1: Run focused Phase 1 and failure-isolation tests**

Run: `python -m pytest -q tests/test_calculation_rule_inventory.py tests/test_calculation_rule_compiler.py tests/test_calculation_rule_graph.py tests/test_calculation_rule_evaluator.py tests/test_calculation_rule_persistence_schema.py tests/test_calculation_rule_service.py`

Expected: missing IDs, mismatch, non-materialized model, corrupt/unavailable bytes, parser/system exception, persistence exception, retry, rollback/session reuse, and canonical-table isolation are covered and passing; record exact gaps if any named case is not covered.

- [ ] **Step 2: Run Model Extraction regression tests**

Run: `python -m pytest -q tests/test_workbook_storage.py tests/test_model_extraction_persistence.py tests/test_model_extraction_reload.py tests/test_model_extraction_persistence_schema.py tests/test_model_extraction_lifecycle.py tests/test_experimental_workbook_upload.py`

- [ ] **Step 3: Run isolated PostgreSQL acceptance when configured**

Require a `TEST_POSTGRES_URL` that is distinct from the active acceptance database. Run the Phase 1 PostgreSQL-marked tests, Alembic upgrade to `20260715_0003`, service/persistence/reload/idempotency/failure isolation tests, and report exact results. If no isolated URL is available, report this as an acceptance gap and do not substitute SQLite evidence.

- [ ] **Step 4: Run the full repository suite fresh**

Run: `python -m pytest -q`

Expected: report exact pass/fail/skip totals and explain each Phase 1-relevant skip. Openpyxl deprecation warnings are recorded separately.

### Task 6: Report and Decision

**Files:**
- Create: `docs/reports/2026-07-16-phase-1-calculation-rule-acceptance.md`
- Read: `/tmp/investiq_phase1_acceptance.json`

**Interfaces:**
- Consumes: all fresh evidence from Tasks 1-5.
- Produces: the required acceptance report and exactly one decision from PASS, CONDITIONAL PASS, or FAIL.

- [ ] **Step 1: Write the required evidence sections**

Include Environment, Selected upstream model, Run result, Six-table evidence with representative rows, Idempotency, Failure isolation, PostgreSQL, Remaining limitations, and exact test commands/results.

- [ ] **Step 2: Audit the report against all 18 acceptance sections**

Explicitly list the availability of a second financial workbook/model, unsupported formulas, cache comparability, mismatches, mapping ambiguity, and skipped conditions. Confirm secrets are redacted and prohibited data paths were not used.

- [ ] **Step 3: Apply the final decision rule**

Use `PASS` only if all blocking correctness, persistence, isolation, and required PostgreSQL evidence passes. Use `CONDITIONAL PASS` for correct core execution with explicitly incomplete non-correctness evidence. Use `FAIL` for any reproducible correctness, persistence, or isolation defect.
