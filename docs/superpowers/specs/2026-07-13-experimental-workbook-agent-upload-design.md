# Experimental Workbook-Agent Upload Validation Design

Date: 2026-07-13  
Status: Approved for implementation  
Scope: `Modelextratcion_test` linked worktree only

## Objective

Replace the runtime behavior of `POST /api/v1/models/upload` in this worktree with a synchronous, experimental workbook-agent validation endpoint. The endpoint lets a tester upload arbitrary benchmark `.xlsx` workbooks from FastAPI Swagger UI and inspect the complete extraction, coverage, deterministic validation, and tool-call trace in one response.

This is an experiment, not a production migration. The existing production upload implementation remains in the source tree as an unregistered legacy function so the change is easy to reverse.

## Explicit Non-Goals

The experimental endpoint will not:

- create `Investment`, `FinancialModel`, or `ModelAssumption` rows;
- write audit-log rows;
- run vectorization;
- call the legacy `ExcelParser`, `AssumptionMapper`, or health report;
- infer workbook meaning from fixed sheet names;
- preserve compatibility with the current Next.js upload result contract;
- provide an asynchronous job API or persistence for experiment results.

The primary client for this validation phase is FastAPI Swagger UI at `/docs`.

## Endpoint Contract

### Route

`POST /api/v1/models/upload`

The OpenAPI summary and description must explicitly label it as an **experimental workbook-agent validation endpoint** and state that it is synchronous, Azure-backed, and intended for benchmark testing.

### Request

The request remains `multipart/form-data` with one required `file` field.

- `.xlsx` is supported and prioritized.
- `.xls` returns HTTP `415 Unsupported Media Type` with a structured explanation that the workbook-agent toolchain relies on `openpyxl` and does not reliably read legacy binary Excel files.
- Any other extension returns HTTP `415`.
- An empty upload returns HTTP `400`.
- A file named `.xlsx` that cannot be opened as an OOXML workbook returns HTTP `422 Unprocessable Entity`.

The uploaded file is written to a request-scoped temporary location for workbook analysis and removed after the response is assembled. It is not recorded in the production upload volume or database.

### Successful Response

The endpoint returns HTTP `200` with the raw validation envelope:

```json
{
  "endpoint_mode": "experimental_workbook_agent_validation",
  "filename": "benchmark.xlsx",
  "runtime_seconds": 72.4,
  "driver_meta": {
    "api": "responses",
    "deployment": "gpt-5.4-mini",
    "prompt_tokens": 12345,
    "completion_tokens": 2345
  },
  "submitted": true,
  "stop_reason": "submitted",
  "coverage": {},
  "final_extraction": {},
  "validation_summary": {
    "candidate_count": 63,
    "validated": 55,
    "validated_null": 2,
    "reclassified": 3,
    "review_required": 2,
    "rejected": 1
  },
  "validation_results": [],
  "warnings": [],
  "errors": [],
  "trace": [],
  "trace_truncated": false
}
```

`validation_results` contains every deterministic candidate validation result. `validation_summary` is derived only from those results and is not model-authored.

`warnings` and `errors` are arrays of structured objects with `code` and `message`, plus optional `context`. A run that reaches a hard cap or ends without a valid submission still returns HTTP `200` so benchmark evidence remains inspectable; it sets `submitted=false`, records an `AGENT_INCOMPLETE` error, and returns the available coverage and trace.

`trace` contains every tool-call event produced by the backend-owned loop. Tool result bodies remain bounded previews to prevent unbounded responses. Each event records whether its preview was truncated, and the response-level `trace_truncated` is true if any event was shortened. The number of trace events is not silently reduced.

## Fatal Error Responses

Fatal errors use FastAPI HTTP errors with structured `detail` objects:

- `400 EMPTY_FILE`: no bytes were uploaded.
- `415 UNSUPPORTED_WORKBOOK_FORMAT`: `.xls` or another unsupported extension.
- `422 INVALID_XLSX`: corrupt, encrypted, or otherwise unreadable OOXML workbook.
- `503 AZURE_CONFIGURATION_ERROR`: required Azure endpoint/API key configuration is missing.
- `502 AZURE_RESPONSES_ERROR`: Azure Responses API fails before a benchmark result can be assembled.
- `500 WORKBOOK_VALIDATION_ERROR`: unexpected local tool or deterministic validation failure.

No exception message may expose API keys or other secret values.

## Architecture

### API Router

`apps/api/app/routers/models.py` keeps the route path but delegates experimental behavior to a new adapter. The current production body is retained without its route decorator and renamed clearly as legacy/rollback-only code.

The experimental route must not declare database or authentication dependencies because the validation run has no persistence or user-owned records.

### Workbook-Agent Adapter

A focused API-side adapter owns:

- temporary-file lifecycle;
- `WorkbookToolset` construction;
- `AzureDriver` construction;
- `run_loop()` execution with existing `HardCaps`;
- `validate_extraction()` execution;
- deterministic summary, warnings, errors, driver metadata, and trace-truncation assembly;
- translation of known failures into API-safe error categories.

The agent loop, coverage gate, toolset, extraction contract, role classifier, dependency analysis, and validator remain sourced from `experiments/workbook_agent_poc`. They are not copied into production modules.

### Container Packaging

The API Docker image currently copies only `libs/` and `apps/api/`. Its Dockerfile must additionally copy `experiments/workbook_agent_poc/` so the container executes the same experimental source present in the worktree.

No source-code bind mount is introduced. Testing a change therefore requires rebuilding the API image.

## Data Flow

1. FastAPI validates the filename and reads the upload bytes.
2. The adapter writes the bytes to a temporary `.xlsx` path.
3. `WorkbookToolset` opens formula and cached-value workbook views.
4. `AzureDriver` uses the Azure OpenAI Responses API and the existing controlled tool schemas.
5. `run_loop()` enforces tool allowlisting, hard caps, backend-owned coverage, and submission gating.
6. `validate_extraction()` re-reads workbook evidence and validates source values and structural roles.
7. The adapter derives `validation_summary`, warnings/errors, token usage, and trace-truncation metadata.
8. FastAPI returns the full result envelope and deletes the temporary workbook.

## Compatibility and Rollback

The Next.js frontend currently expects `model_id`, `investment_id`, and `health_report`; it is intentionally out of scope and may fail against this experimental response.

Rollback is limited to restoring the route decorator to the retained legacy handler and removing the experimental route registration. Existing production parser, persistence, vectorization, and response schema code are not deleted.

## Testing Strategy

Implementation follows RED-GREEN TDD.

Automated tests must prove:

1. OpenAPI identifies the route as experimental.
2. `.xls` and unrelated extensions return `415` without invoking the agent.
3. empty `.xlsx` returns `400`.
4. malformed `.xlsx` returns `422`.
5. a deterministic fake driver can exercise the real tool loop and validator through the upload endpoint without Azure network access.
6. a successful response contains extraction, coverage, validation results, summary, warnings, errors, trace, `trace_truncated`, and `driver_meta.api`.
7. an incomplete run returns inspectable evidence and a structured `AGENT_INCOMPLETE` error.
8. the endpoint does not call the legacy parser, persistence, vectorization, or health-check path.
9. temporary files are removed after success and failure.
10. the Docker image contains the workbook-agent PoC source and the live container serves the experimental OpenAPI contract after rebuild.

The final manual validation uploads at least one provided benchmark `.xlsx` through `/docs`; real Azure execution is only performed when credentials are available and incurs model usage.

## Acceptance Criteria

- Swagger presents `POST /api/v1/models/upload` as experimental workbook-agent validation.
- Uploading a valid `.xlsx` runs the new controlled workbook-agent and deterministic validator synchronously.
- The response exposes complete extraction, coverage, validation results, all trace events, truncation metadata, driver metadata, warnings, and errors.
- `.xls` is explicitly rejected rather than passed to an unreliable reader.
- No production database, vector, legacy health, fixed-sheet parser, or production upload records are touched.
- Existing production upload code remains available for rollback.
- Unit/API tests and a rebuilt Docker API verify the implemented contract.
