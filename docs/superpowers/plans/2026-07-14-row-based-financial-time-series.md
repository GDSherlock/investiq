# Row-Based Financial Time-Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace representative-cell canonical financial-series extraction with complete aligned period/value axes while preserving the current full-context flow and legacy buckets.

**Architecture:** Extend the submit contract with a canonical `financial_series` bucket and validate it through a dedicated range-aware validator. Keep legacy candidates untouched, deduplicate exact canonical source ranges deterministically, and expose an additive time-series summary through the existing API adapter.

**Tech Stack:** Python 3.12, OpenPyXL 3.1.2, pytest, existing workbook-agent PoC and FastAPI adapter.

## Global Constraints

- Do not change coverage, chunking, continuation tokens, submission gating, workbook-version binding, persistence, endpoints, frontend code, or unrelated routing.
- Do not make live Azure calls.
- Do not commit or push.
- Preserve `financial_series_candidates`; add `financial_series` additively.

---

### Task 1: Canonical series contract

**Files:**
- Modify: `experiments/workbook_agent_poc/extraction_contract.py`
- Test: `experiments/workbook_agent_poc/tests/test_financial_series_contract.py`

**Interfaces:**
- Produces: `SUBMIT_RESULT_SCHEMA.properties.financial_series` and explicit complete-series prompt rules.

- [x] Write schema/prompt assertions that fail because the canonical bucket and complete-axis instruction do not exist.
- [x] Run the focused contract test and confirm the expected RED failure.
- [x] Add schemas for axes, range references, formula pattern metadata, and canonical series.
- [x] Add explicit prompt rules for complete contiguous axes, null preservation, formula/semantic independence, and scenario/sensitivity separation.
- [x] Run the focused test and confirm GREEN.

### Task 2: Deterministic series validator

**Files:**
- Create: `experiments/workbook_agent_poc/time_series.py`
- Modify: `experiments/workbook_agent_poc/validator.py`
- Test: `experiments/workbook_agent_poc/tests/test_financial_series.py`

**Interfaces:**
- Produces: `validate_financial_series(tools, series) -> dict`, `validate_financial_series_collection(tools, series) -> list[dict]`.
- Consumes: `WorkbookToolset.get_cell`, OpenPyXL range utilities, and canonical schema fields.

- [x] Write failing tests for aligned horizontal ranges, fully formula rows, mixed rows with nulls, one-point misuse, misalignment, wrong values, duplicate ranges, vertical axes, and invalid two-dimensional ranges.
- [x] Run the focused tests and confirm failures are due to missing series validation.
- [x] Implement range parsing, positional workbook comparison, formula/cache telemetry, calculation type, relative-formula consistency, and deterministic duplicate flags.
- [x] Integrate canonical validation results into `validate_extraction` without changing legacy candidate validation.
- [x] Run the focused tests and confirm GREEN.

### Task 3: API summary and deterministic workbook regression

**Files:**
- Modify: `apps/api/app/workbook_validation.py`
- Modify: `tests/test_workbook_validation.py`

**Interfaces:**
- Produces: response field `time_series_summary` with submitted, validated, reclassified, rejected, representative-only, mismatch, and duplicate counts.

- [x] Extend the deterministic Financial Model driver to submit evidenced complete series from `Financial_Model_Data.xlsx` and add failing response assertions.
- [x] Run the focused adapter regression and confirm RED.
- [x] Add additive summary construction and response wiring.
- [x] Run the adapter regression and confirm coverage remains complete, `coverage_rejections=0`, `submit_attempts=1`, and canonical series validate.

### Task 4: Regression verification and reporting

**Files:**
- Modify: `experiments/workbook_agent_poc/README.md`

**Interfaces:**
- Documents: compatibility choice, canonical schema, deterministic validation, and local/mock versus live acceptance distinction.

- [x] Document the additive bucket and limitations of OpenPyXL display/cached-value freshness.
- [x] Run focused financial-series, validator, contract, agent-loop, coverage, and observation-chunking tests.
- [x] Run the relevant full PoC/API suite.
- [x] Run `git diff --check`, inspect `git status`, and record runtime/token/logical-call before/after evidence without a live Azure request.
