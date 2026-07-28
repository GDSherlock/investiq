# Large Workbook Partitioned Extraction Acceptance

Local validation date: 2026-07-28 (Asia/Singapore).

## Git and Docker Provenance

- Branch: `feature/backend-scale-up`
- Validated commit: `bc978967f5bd06abb3daf09c6437ececee468ffa`
- Compose project/service: `new-infra-proj` / `api`
- Compose working directory:
  `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj`
- Container: `new-infra-proj-api-1`, running and healthy
- Image:
  `sha256:b38a4301c9f66a95eb32a7ce7c6d1a35d55e8edd45957e3b14b489c711e85966`
- `git diff --check c6c1a0e..HEAD` passed.
- The implementation range changes only the partition modules and tests,
  `workbook_validation.py`, its two integration tests, and the implementation
  plan. It has no Alembic, frontend, calculation-engine, router, or public
  schema change.
- Existing unrelated working-tree changes under `apps/ui`, `docker-compose.yml`,
  and `tests/test_monte_carlo_contracts.py` were not staged or modified by this
  work.

Docker commands:

```text
docker compose build api
docker compose up -d api
docker inspect new-infra-proj-api-1 --format <selected provenance fields>
docker image inspect new-infra-proj-api:latest --format <image id and creation>
```

## Non-Secret Azure Configuration

The effective container configuration was inspected by printing only selected
non-secret values and booleans:

```text
deployment: gpt-5.4
endpoint_configured: true
api_key_configured: true
max_output_tokens environment value: not set
reasoning_effort environment value: not set
partitioned environment value: default true
```

The driver therefore uses its code defaults of `16384` maximum output tokens
and `medium` reasoning effort. No key, endpoint value, connection string, or
workbook payload is recorded in this report.

## Deterministic Test Results

Focused workbook-agent, upload, lifecycle, persistence, reload, orchestration,
and calculation regression:

```text
315 passed, 1 skipped, 1274 warnings in 12.69s
```

Command:

```text
.venv_mac/bin/python3 -m pytest experiments/workbook_agent_poc/tests \
  tests/test_workbook_validation.py \
  tests/test_experimental_workbook_upload.py \
  tests/test_model_extraction_lifecycle.py \
  tests/test_model_extraction_persistence.py \
  tests/test_model_extraction_reload.py \
  tests/test_model_upload_orchestration_service.py \
  tests/test_calculation_integration_service.py \
  tests/test_calculation_api.py -q
```

Complete Python suite:

```text
1 failed, 634 passed, 5 skipped, 2498 warnings in 23.19s
```

The sole failure is
`tests/test_frontend_extraction_loading_contracts.py::test_package_keeps_dependencies_and_lint_contract_unchanged`.
It observes the existing, unrelated working-tree edit that prepends
`npm run check:number-format` to `apps/ui/package.json`. The partitioned
extraction commits do not change that file.

## Workbook Inventory and Partition Budgets

Input:

```text
path: /Users/kingjason/Downloads/PF Full Model END (1).xlsx
size_bytes: 650676
sha256: e552f8e86c92c3bab2a123840675b3b625ec63285e3e8e7f1ee0baf8583ce450
```

The first preflight exposed that repeated empty observation metadata caused
`38,200,609` accumulated bytes and would deterministically breach the 24 MiB
run cap. Commit `bc97896` removes only redundant unavailable/false metadata
from partition envelopes. It retains every non-empty cell, source reference,
raw value, formula, formula/cache status, data type, number format, and
non-redundant warning.

Rebuilt-image preflight after that fix:

```text
content_sheets: 14
non_empty_cells: 44541
partitions: 163
max_estimated_total_tokens: 130331       (limit 200000)
max_estimated_raw_tokens: 119159         (limit 120000)
max_request_bytes: 260662                (limit 524288)
raw_evidence_bytes_total: 22689503        (limit 25165824)
```

The preflight used `WorkbookToolset`, `WorkbookIndexBuilder`, and
`PartitionPlanner` inside the rebuilt API container. It did not instantiate an
Azure client.

## Live Upload Result

Not run. The user explicitly paused real Azure calls before the public upload
step.

- HTTP upload request: not sent
- Azure Responses requests: zero
- Azure request IDs: none
- Workbook/model version IDs: none created by this local validation

Consequently, Azure model semantics, live response latency, and live
materialization are not claimed as accepted.

## Coverage and Provenance

A local `local-no-azure` driver returned schema-valid empty partial results for
the real workbook's planned partitions. The production
`run_partitioned_extraction` orchestration, coverage tracker, 24 MiB circuit
breaker, and reconciler were exercised with the real planned envelopes:

```text
submitted: true
stop_reason: submitted
planned_partition_count: 163
completed_partition_count: 163
missing_partition_ids: []
missing_primary_ranges: {}
submission_allowed: true
raw_evidence_bytes: 22689503
local driver operations: 163
external Azure calls: zero
```

The coverage payload names its driver-operation counter `azure_call_count`; in
this test its value was `163`, but every operation was handled by the in-process
`local-no-azure` driver and generated no network request.

## Persistence and Calculation Preparation

The local no-Azure validation invoked the request-scoped partition pipeline
directly and intentionally did not call the public upload endpoint. It created
no workbook version, model version, extraction snapshot, or calculation-rule
record.

Existing persistence and calculation preparation behavior is covered by the
focused deterministic suite above, including failed-attempt lifecycle behavior:
a failed model version remains failed, and a later upload starts with a distinct
model version ID.

## Remaining Warnings

- Live Azure upload, semantic extraction quality, durable materialization, and
  calculation preparation for this supplied workbook remain pending by user
  instruction.
- The container receives the `gpt-5.4` deployment and defaults partitioned mode
  to true, but does not receive explicit maximum-output-token or
  reasoning-effort environment values.
- The complete Python suite has one unrelated failure caused by existing
  uncommitted frontend changes described above.
- Compose reports that its top-level `version` attribute is obsolete; it was not
  changed because Compose is outside this task's approved diff.
