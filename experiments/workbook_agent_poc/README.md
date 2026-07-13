# Workbook Agent PoC — EXPERIMENTAL WORKTREE VALIDATION

> **In the `Modelextratcion_test` linked worktree only, this PoC is intentionally
> wired to `POST /api/v1/models/upload` as a synchronous experimental validation
> endpoint. It bypasses the retained production upload implementation and does
> not write production database records or vectors.**

## Purpose

Validate the core principle of the proposed architecture, end to end and locally:

> The LLM explores an uploaded Excel model **only through controlled local tools**,
> proposes structured candidates with source-cell evidence, and a **deterministic
> rule-based validator verifies every claim against the workbook**. The LLM cannot
> invent values, cannot coerce a missing formula cache to 0, and cannot submit a
> fact without a resolvable source reference.

## Files

| File | Role |
|------|------|
| `workbook_tools.py` | 5 read-only tools + full per-cell evidence envelope. Loads the workbook twice (values + formulas), exactly like the production `ExcelParser`. Never coerces `None` → `0`. |
| `validator.py` | Deterministic validator. Re-reads the workbook and checks each candidate; trusts the workbook, not the model. |
| `agent_loop.py` | Backend-owned function-calling loop. `MockModel`-agnostic; ships an `AzureDriver` using the Azure OpenAI v1 `OpenAI` + Responses API function-calling pattern. |
| `run_poc.py` | Entry point. Runs the loop over `Financial_Model_Data.xlsx`, validates candidates, and asserts 10 invariants. |

## Run

```bash
# Local, deterministic, no network, no cost (default):
.venv_mac/bin/python3 experiments/workbook_agent_poc/run_poc.py

# Real Azure OpenAI round-trip (network + token cost; uses .env creds):
.venv_mac/bin/python3 experiments/workbook_agent_poc/run_poc.py --live
```

## FastAPI Upload Validation

Rebuild and start the API from the `Modelextratcion_test` linked worktree, then
open `http://localhost:8000/docs` and use `POST /api/v1/models/upload`.

- Upload `.xlsx` workbooks only. Legacy `.xls` is explicitly rejected with HTTP 415.
- The request waits synchronously for Azure Responses API exploration and deterministic validation.
- The response includes extraction, coverage, validation summary/results, warnings, errors,
  every trace event, trace truncation metadata, and token/deployment metadata.
- The current Next.js upload UI is not compatible with this raw experimental response.

## Status

- **Mock loop + validation: PASSING** (10/10 invariants) — proves orchestration and, crucially,
  that the validator **rejects** fabricated values, bad refs, and missing sources.
- **`--live` Azure round-trip: VERIFIED** against deployment `gpt-5.2`. The real model drove
  `list_sheets → inspect_sheet → read_range → submit_extraction_result` and submitted **63
  assumption candidates**; the deterministic validator confirmed **63/63** against the workbook.
  Observed limitations (both by design of the control, not bugs):
  - The model inspected only 1 of 11 sheets — coverage is **backend-tracked**, so the partial
    coverage is visible in the log rather than trusted from the model.
  - The terminal tool needs a **constrained JSON schema** (now applied); an unconstrained
    `result` object produced 0 candidates on the first attempt.
