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
| `workbook_tools.py` | Read-only tools + full per-cell evidence envelope. Loads the workbook twice (values + formulas), exactly like the production `ExcelParser`, and caches observed facts for validation reuse. Never coerces `None` → `0`. |
| `validator.py` | Deterministic validator for legacy point candidates plus backend-materialized financial series; trusts workbook evidence, not the model. |
| `time_series.py` | `FinancialSeriesMaterializer`: descriptor/range validation, canonical period/value points, formula/static/blank telemetry, period normalization, representative-cell rejection, deduplication, and consumer point conversion. |
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
  a dedicated `time_series_summary`, every trace event, trace truncation metadata, and
  token/deployment metadata.
- The current Next.js upload UI is not compatible with this raw experimental response.

## Canonical financial-series compatibility

The LLM identifies semantics plus complete workbook ranges. It does not repeat period arrays,
value arrays, formula counts, or per-point source cells:

```json
{
  "series_id": "revenue_total",
  "label": "TOTAL REVENUE",
  "semantic_role": "financial_series",
  "category": "revenue",
  "unit": "USD M",
  "frequency": "annual",
  "period_range": "Revenue!C3:V3",
  "value_range": "Revenue!C14:V14",
  "label_reference": "Revenue!B14"
}
```

The backend materializer reads the already-loaded cached-value and formula workbook views, verifies
one-dimensional aligned ranges, and writes consumer-ready objects to
`final_extraction.financial_series`. Each canonical period/value point contains its index and source
cell; calculation type and formula telemetry are derived from workbook cells. Future database, API,
chart, cash-flow, scenario, and monitoring consumers should use only this canonical bucket.

The raw `financial_series_candidates` bucket remains unchanged for debugging and old single-cell
consumers. Legacy complete objects with `period_axis.source_range` and `value_axis.source_range` are
temporarily accepted, but their LLM-authored arrays and formula metadata are only disagreement
telemetry and never override workbook-derived canonical data. New submitted descriptors are retained
under `financial_series_descriptors` before canonical write-back.

Formula presence is independent of `semantic_role=financial_series`. OpenPyXL exposes cached formula
values but cannot prove freshness or reliably render every Excel display string, so formula cache
freshness is reported as `unknown` and workbook recalculation flags become warnings. Scenario tables
remain in `scenario_structures`; one-way and two-way matrices remain in
`sensitivity_structures` and are never materialized as ordinary chronological series.

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
