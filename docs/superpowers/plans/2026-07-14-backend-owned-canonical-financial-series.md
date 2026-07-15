# Backend-Owned Canonical Financial Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make workbook-derived canonical financial series the sole consumer-facing source of truth while retaining legacy raw buckets for compatibility.

**Architecture:** `FinancialSeriesMaterializer` accepts new descriptors and normalized legacy full-series objects, reads both cached and formula workbook views through the existing `WorkbookToolset`, and returns canonical series plus structured results and summary telemetry. `validate_extraction()` integrates the outcome and the API adapter writes canonical series back to `final_extraction.financial_series` without changing the agent loop or submission gate.

**Tech Stack:** Python 3.12, openpyxl 3.1.2, pytest, existing workbook-agent PoC.

## Global Constraints

- Work only in `.claude/worktrees/Modelextratcion_test`.
- Do not make live Azure calls.
- Do not commit or push.
- Do not modify coverage, chunking, continuation tokens, workbook-version binding, submission gating, endpoints, persistence, or frontend code.
- Do not add one model call per series or model-visible workbook reads.
- Preserve raw `financial_series_candidates`, `scenario_structures`, and `sensitivity_structures`.

---

### Task 1: Descriptor Contract

**Files:**
- Modify: `experiments/workbook_agent_poc/extraction_contract.py`
- Test: `experiments/workbook_agent_poc/tests/test_financial_series_contract.py`

**Interfaces:**
- Produces: `SUBMIT_RESULT_SCHEMA.properties.financial_series.items` requiring descriptor ranges rather than arrays.

- [ ] Replace the contract assertions with RED assertions that `period_range` and `value_range` are required and that `period_axis`, `value_axis`, `calculation_type`, and `formula_pattern` are not model-authored descriptor fields.
- [ ] Run `pytest experiments/workbook_agent_poc/tests/test_financial_series_contract.py -q` and confirm it fails against the array-based schema.
- [ ] Replace `_FINANCIAL_SERIES` with a descriptor schema containing required semantic fields and optional scenario/entity/currency/label reference fields.
- [ ] Update `SYSTEM_PROMPT` to forbid submitted `periods[]`, `values[]`, formula counts, and point source cells while requiring aligned qualified ranges.
- [ ] Re-run the contract test and confirm it passes.

### Task 2: Deterministic Materializer Core

**Files:**
- Modify: `experiments/workbook_agent_poc/time_series.py`
- Test: `experiments/workbook_agent_poc/tests/test_financial_series.py`

**Interfaces:**
- Produces: `FinancialSeriesMaterializer(tools).materialize(descriptor) -> dict`.
- Produces: structured failed canonical objects with `error_code` and `rejection_reason`.

- [ ] Add RED tests for descriptor-only horizontal and vertical materialization, qualified quoted sheets, explicit `sheet_name`, one-dimensional/alignment errors, and representative-cell-only detection.
- [ ] Run the focused tests and confirm they fail because the current validator requires arrays.
- [ ] Implement range parsing into an immutable range spec with qualified sheet, normalized A1 range, orientation, coordinates, and length.
- [ ] Build period points from workbook cell facts with index, raw label, display label, normalized fields, and qualified source cell.
- [ ] Build value points from workbook cell facts with cached value, formula, availability/freshness, number format, data type, and qualified source cell.
- [ ] Return `materialized`/`materialized_with_warning` and `validated`/`validated_with_warning` statuses for usable series; return `failed`/`rejected` with stable codes for invalid geometry.
- [ ] Re-run the focused tests and confirm descriptor materialization is green.

### Task 3: Period and Formula Telemetry

**Files:**
- Modify: `experiments/workbook_agent_poc/time_series.py`
- Test: `experiments/workbook_agent_poc/tests/test_financial_series.py`

**Interfaces:**
- Produces: `normalize_period(raw_value, display_label) -> dict[str, Any]`.
- Produces: backend-derived `calculation_type` and `formula_pattern`.

- [ ] Add RED tests for `2025`, `FY25`, `2026E`, `Q1 2027`, Excel dates, formula-only, hardcoded-only, mixed/blank, and all-zero rows.
- [ ] Confirm failures show missing point normalization and canonical telemetry.
- [ ] Implement conservative regex/date normalization that preserves original labels and returns null for uncertain fields.
- [ ] Derive formula/static/blank counts from formula and cached workbook facts; make zeros static, not blank.
- [ ] Normalize copied formulas with `openpyxl.formula.translate.Translator`; return null when translation is unsafe.
- [ ] Re-run focused tests and confirm all telemetry cases pass.

### Task 4: Legacy Compatibility and Deduplication

**Files:**
- Modify: `experiments/workbook_agent_poc/time_series.py`
- Test: `experiments/workbook_agent_poc/tests/test_financial_series.py`

**Interfaces:**
- Produces: `normalize_financial_series_descriptors(extraction) -> tuple[list[dict], dict]`.
- Produces: `materialize_collection(descriptors) -> {canonical_series, validation_results, telemetry}`.

- [ ] Add RED tests where legacy arrays are deliberately wrong but source ranges are correct, exact duplicate evidence appears twice, and same labels differ by scenario/unit/entity.
- [ ] Confirm current code rejects wrong legacy arrays and emits duplicate rejected results instead of one canonical object.
- [ ] Normalize legacy axis source ranges into descriptors and retain legacy arrays only for disagreement warnings.
- [ ] Deduplicate by period/value evidence plus scenario/entity/unit/currency; preserve label aliases and duplicate telemetry.
- [ ] Keep same-label/different-evidence series separate with a warning; prefer schedule evidence over dashboard evidence only for otherwise equivalent duplicates.
- [ ] Re-run focused tests and confirm canonical collection behavior passes.

### Task 5: Validation and API Write-Back

**Files:**
- Modify: `experiments/workbook_agent_poc/validator.py`
- Modify: `apps/api/app/workbook_validation.py`
- Modify: `apps/api/app/schemas.py`
- Test: `tests/test_workbook_validation.py`

**Interfaces:**
- Produces: `materialize_financial_series(tools, extraction) -> dict` used once per run.
- Produces: `final_extraction.financial_series` and additive `time_series_summary`.

- [ ] Add RED API tests using legacy complete objects only under `financial_series_candidates`; assert canonical write-back and non-zero summary.
- [ ] Add RED assertions that descriptor-only deterministic acceptance preserves `submitted=true`, `coverage_rejections=0`, `submit_attempts=1`, and `logical_model_tool_calls=25`.
- [ ] Integrate materialization before final response construction and make validator results consume the same materialization outcome.
- [ ] Compute summary fields `submitted_descriptors`, `legacy_series_detected`, `materialized_series`, `validated_series`, `validated_with_warning`, `rejected_series`, `representative_cell_only`, `period_value_mismatches`, and `duplicate_series` from actual outcomes.
- [ ] Preserve raw submitted buckets and write only backend-derived canonical objects to `final_extraction.financial_series`.
- [ ] Re-run API and agent-loop focused tests and confirm no coverage/submission regression.

### Task 6: Consumer Helper and Documentation

**Files:**
- Modify: `experiments/workbook_agent_poc/time_series.py`
- Modify: `experiments/workbook_agent_poc/README.md`
- Test: `experiments/workbook_agent_poc/tests/test_financial_series.py`

**Interfaces:**
- Produces: `canonical_series_to_points(series: dict[str, Any]) -> list[dict[str, Any]]`.

- [ ] Add a RED test for aligned chart point conversion and an error on malformed canonical axes.
- [ ] Implement deterministic point zipping with period index/label/normalized fields, value, and value source cell.
- [ ] Document descriptor ownership, canonical consumer bucket, legacy debugging bucket, scenario/sensitivity separation, and unknown cached freshness.
- [ ] Re-run focused tests and confirm the helper and docs contract are green.

### Task 7: Deterministic Acceptance and Performance Evidence

**Files:**
- Modify: `tests/test_workbook_validation.py`

**Interfaces:**
- Consumes: deterministic `FinancialModelCoverageDriver` and canonical response fields.

- [ ] Convert the deterministic current-workbook driver from full arrays to descriptors and add legacy-shape regression coverage separately.
- [ ] Measure compact descriptor JSON bytes and equivalent legacy full-array JSON bytes with the same semantic fields.
- [ ] Assert current workbook canonical coverage where valid rows exist for revenue, EBITDA, net income, unlevered free cash flow, total debt service, DSCR, and cumulative capex.
- [ ] Record descriptors detected, legacy detected, materialized, validated, rejected, representative-only, mismatch, duplicate, logical model calls, and backend range reads.
- [ ] Run every requested focused command, then the full PoC/API suite, and finally `git diff --check`.
- [ ] Inspect `git status --short`; leave all changes uncommitted and unstaged.
