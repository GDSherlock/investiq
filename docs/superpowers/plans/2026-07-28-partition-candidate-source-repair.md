# Partition Candidate Source Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject source-less nested partition candidates at the Azure driver boundary, request exactly one targeted correction, and allow the small GPT-5.4 mini workbook upload to reach deterministic reconciliation without weakening provenance.

**Architecture:** Add a pure nested-result validator beside the partition tool contract, then inject it only into `AzurePartitionDriver.extract()`. The existing two-attempt structured-output loop will use the validator's static repair instruction for one same-response-chain correction; a second invalid result remains an atomic typed failure.

**Tech Stack:** Python 3.12, OpenAI Responses SDK, `httpx.MockTransport`, pytest, FastAPI, Docker Compose, PostgreSQL.

## Global Constraints

- Preserve the existing public upload response, database schema, persistence lifecycle, calculation engine, frontend, partition planner, coverage tracker, reconciler, and rollback switch.
- Do not infer, backfill, or synthesize a missing workbook source reference.
- Allow at most one structured correction response for a malformed partition result.
- Do not change `PartitionLimits`, `max_calls_per_operation`, transport retry counts, token budgets, byte budgets, partition limits, or deadlines.
- Do not add `jsonschema` or another runtime dependency.
- Do not log raw cells, formulas, labels, model-authored candidate content, API keys, endpoints, or request payloads.
- Do not automatically retry a whole failed workbook upload.
- Keep the local ignored `.env` on `gpt-5.4-mini`; do not commit or modify it during implementation.
- Preserve unrelated dirty and untracked files, especially `apps/ui`, `docker-compose.yml`, `tests/test_monte_carlo_contracts.py`, `.playwright-mcp/`, and unrelated reports.

---

### Task 1: Deterministic Nested Partition Result Validator

**Files:**
- Modify: `experiments/workbook_agent_poc/partition_contract.py:5-10,30-60,162-171`
- Create: `experiments/workbook_agent_poc/tests/test_partition_contract.py`

**Interfaces:**
- Produces: immutable `PartitionResultIssue(code: str, repair_instruction: str)`.
- Produces: `validate_partition_tool_arguments(arguments: dict[str, Any]) -> PartitionResultIssue | None`.
- Consumes: the parsed outer `submit_partition_result` arguments, including its nested `result`.
- Does not validate workbook existence or source geometry; `PartitionReconciler` remains authoritative for those checks.

- [ ] **Step 1: Write the failing contract tests**

Create `experiments/workbook_agent_poc/tests/test_partition_contract.py`:

```python
"""Nested contract checks for partition function-call arguments."""

import os
import sys

import pytest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from partition_contract import validate_partition_tool_arguments


SOURCE_BOUND_BUCKETS = (
    "metadata",
    "all_assumption_candidates",
    "parameter_candidates",
    "derived_value_candidates",
    "output_candidates",
    "financial_series_candidates",
    "unclassified_inputs",
    "review_candidates",
    "scenario_structures",
    "sensitivity_structures",
)


def _valid_candidate():
    return {
        "candidate_id": "candidate-1",
        "original_label": "Tax rate",
        "submitted_role": "hardcoded_input",
        "raw_value": 0.25,
        "source_references": [{"sheet_name": "Inputs", "cell": "B2"}],
    }


def _arguments():
    return {
        "workbook_version": "a" * 64,
        "partition_id": "partition-1",
        "sheet_name": "Inputs",
        "primary_range": "A1:B2",
        "result": {
            "all_assumption_candidates": [],
            "output_candidates": [],
        },
    }


@pytest.mark.parametrize("bucket", SOURCE_BOUND_BUCKETS)
def test_every_source_bound_bucket_rejects_missing_source_references(bucket):
    arguments = _arguments()
    arguments["result"][bucket] = [{
        key: value
        for key, value in _valid_candidate().items()
        if key != "source_references"
    }]

    issue = validate_partition_tool_arguments(arguments)

    assert issue is not None
    assert issue.code == "candidate_source_missing"
    assert "source_references" in issue.repair_instruction
    assert "Tax rate" not in issue.repair_instruction


@pytest.mark.parametrize(
    "source_references",
    [
        [],
        ["Inputs!B2"],
        [{}],
        [{"sheet_name": "", "cell": "B2"}],
        [{"sheet_name": "Inputs", "cell": ""}],
        [{"sheet_name": 12, "cell": "B2"}],
        [{"sheet_name": "Inputs", "cell": None}],
    ],
)
def test_invalid_source_reference_shape_is_rejected(source_references):
    arguments = _arguments()
    candidate = _valid_candidate()
    candidate["source_references"] = source_references
    arguments["result"]["all_assumption_candidates"] = [candidate]

    issue = validate_partition_tool_arguments(arguments)

    assert issue is not None
    assert issue.code in {"candidate_source_missing", "candidate_source_invalid"}


@pytest.mark.parametrize(
    "field,value,expected_code",
    [
        ("result", None, "partition_result_missing"),
        ("all_assumption_candidates", None, "partition_bucket_invalid"),
        ("output_candidates", {}, "partition_bucket_invalid"),
    ],
)
def test_required_result_shape_is_rejected(field, value, expected_code):
    arguments = _arguments()
    if field == "result":
        arguments[field] = value
    else:
        arguments["result"][field] = value

    issue = validate_partition_tool_arguments(arguments)

    assert issue is not None
    assert issue.code == expected_code


def test_required_candidate_buckets_must_exist():
    arguments = _arguments()
    arguments["result"].pop("output_candidates")

    issue = validate_partition_tool_arguments(arguments)

    assert issue is not None
    assert issue.code == "partition_bucket_missing"


def test_canonical_financial_series_does_not_require_source_references():
    arguments = _arguments()
    arguments["result"]["financial_series"] = [{
        "series_id": "revenue",
        "label": "Revenue",
        "semantic_role": "financial_series",
        "business_role": "revenue",
        "category": "revenue",
        "unit": "USD",
        "frequency": "annual",
        "period_range": "Forecast!C3:J3",
        "value_range": "Forecast!C8:J8",
    }]

    assert validate_partition_tool_arguments(arguments) is None


def test_valid_source_bound_candidates_return_no_issue():
    arguments = _arguments()
    arguments["result"]["all_assumption_candidates"] = [_valid_candidate()]

    assert validate_partition_tool_arguments(arguments) is None
```

- [ ] **Step 2: Run the new tests to verify RED**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_contract.py -q
```

Expected: collection fails because
`validate_partition_tool_arguments` does not exist.

- [ ] **Step 3: Implement the pure validator**

In `partition_contract.py`, add `dataclass` and define:

```python
from dataclasses import dataclass


SOURCE_BOUND_PARTIAL_BUCKETS = (
    "metadata",
    "all_assumption_candidates",
    "parameter_candidates",
    "derived_value_candidates",
    "output_candidates",
    "financial_series_candidates",
    "unclassified_inputs",
    "review_candidates",
    "scenario_structures",
    "sensitivity_structures",
)
REQUIRED_PARTIAL_BUCKETS = (
    "all_assumption_candidates",
    "output_candidates",
)


@dataclass(frozen=True)
class PartitionResultIssue:
    code: str
    repair_instruction: str


def _issue(code: str, instruction: str) -> PartitionResultIssue:
    return PartitionResultIssue(
        code=code,
        repair_instruction=(
            "The previous submit_partition_result was rejected with "
            f"{code}. {instruction} Return one complete replacement "
            "submit_partition_result function call."
        ),
    )


def validate_partition_tool_arguments(
    arguments: dict[str, Any],
) -> PartitionResultIssue | None:
    result = arguments.get("result")
    if not isinstance(result, dict):
        return _issue(
            "partition_result_missing",
            "The result field must be an object.",
        )

    for bucket in REQUIRED_PARTIAL_BUCKETS:
        if bucket not in result:
            return _issue(
                "partition_bucket_missing",
                f"The result must include the {bucket} list.",
            )

    for bucket in SOURCE_BOUND_PARTIAL_BUCKETS:
        if bucket not in result:
            continue
        items = result[bucket]
        if not isinstance(items, list):
            return _issue(
                "partition_bucket_invalid",
                f"The {bucket} field must be a list.",
            )
        for item in items:
            if not isinstance(item, dict):
                return _issue(
                    "partition_candidate_invalid",
                    f"Every item in {bucket} must be an object.",
                )
            sources = item.get("source_references")
            if not isinstance(sources, list) or not sources:
                return _issue(
                    "candidate_source_missing",
                    "Every candidate and structure must include a non-empty "
                    "source_references list citing exact supplied evidence.",
                )
            for source in sources:
                if (
                    not isinstance(source, dict)
                    or not isinstance(source.get("sheet_name"), str)
                    or not source["sheet_name"].strip()
                    or not isinstance(source.get("cell"), str)
                    or not source["cell"].strip()
                ):
                    return _issue(
                        "candidate_source_invalid",
                        "Every source reference must contain non-empty string "
                        "sheet_name and cell fields from supplied evidence.",
                    )
    return None
```

Add these names to `__all__`:

```python
"PartitionResultIssue",
"SOURCE_BOUND_PARTIAL_BUCKETS",
"validate_partition_tool_arguments",
```

Do not add strict mode or `additionalProperties=False`; that is outside the
approved approach.

- [ ] **Step 4: Run contract and existing reconciliation tests**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_contract.py \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py -q
```

Expected: all selected tests pass, proving validation aligns with the existing
reconciler without changing its behavior.

- [ ] **Step 5: Commit the contract validator**

Run:

```bash
git add \
  experiments/workbook_agent_poc/partition_contract.py \
  experiments/workbook_agent_poc/tests/test_partition_contract.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat(agent): validate partition candidate sources"
```

Expected staged scope: exactly the contract module and its new test.

---

### Task 2: One Targeted Same-Partition Correction

**Files:**
- Modify: `experiments/workbook_agent_poc/partition_driver.py:13-19,121-222`
- Modify: `experiments/workbook_agent_poc/tests/test_partition_driver.py:15-20,64-74,173-207,311-328`

**Interfaces:**
- Consumes: `validate_partition_tool_arguments()` and
  `PartitionResultIssue`.
- Extends:

```python
AzurePartitionDriver._structured_operation(
    ...,
    payload_validator: (
        Callable[[dict[str, Any]], PartitionResultIssue | None] | None
    ) = None,
) -> dict[str, Any]
```

- Preserves: two structured attempts, independent partition sessions,
  transport retry behavior, and `max_calls_per_operation`.

- [ ] **Step 1: Add a failing repair-success driver test**

In `test_partition_driver.py`, import:

```python
from partition_driver import (
    AzurePartitionDriver,
    PartitionAuthenticationError,
    PartitionContextLimitError,
    PartitionStructuredOutputError,
)
```

Add:

```python
def _candidate_without_source():
    return {
        "candidate_id": "candidate-secret-id",
        "original_label": "secret-model-label",
        "submitted_role": "hardcoded_input",
        "raw_value": 0.25,
    }


def _candidate_with_source():
    return {
        **_candidate_without_source(),
        "source_references": [{"sheet_name": "Model", "cell": "A1"}],
    }


def test_missing_candidate_source_gets_one_targeted_correction(monkeypatch):
    partition = _partition("partition-source-repair", "A1:B2")
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        arguments = _partition_args(partition)
        arguments["result"]["all_assumption_candidates"] = [
            _candidate_without_source()
            if len(bodies) == 1
            else _candidate_with_source()
        ]
        return _response(
            request,
            response_id=f"resp-source-{len(bodies)}",
            tool_name="submit_partition_result",
            arguments=arguments,
        )

    result = _driver(monkeypatch, handler).extract(
        partition,
        _envelope(partition),
    )

    assert len(bodies) == 2
    assert bodies[1]["previous_response_id"] == "resp-source-1"
    correction = bodies[1]["input"][0]["content"]
    assert "candidate_source_missing" in correction
    assert "source_references" in correction
    assert "secret-model-label" not in correction
    assert result["result"]["all_assumption_candidates"][0][
        "source_references"
    ] == [{"sheet_name": "Model", "cell": "A1"}]
```

- [ ] **Step 2: Add failing exhaustion and log-safety tests**

Add:

```python
def test_two_source_less_results_raise_without_third_call(monkeypatch):
    partition = _partition("partition-source-exhausted", "A1:B2")
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        arguments = _partition_args(partition)
        arguments["result"]["all_assumption_candidates"] = [
            _candidate_without_source()
        ]
        return _response(
            request,
            response_id=f"resp-exhausted-{len(bodies)}",
            tool_name="submit_partition_result",
            arguments=arguments,
        )

    driver = _driver(monkeypatch, handler)

    with pytest.raises(PartitionStructuredOutputError):
        driver.extract(partition, _envelope(partition))

    assert len(bodies) == 2
    assert driver.call_count == 2


def test_source_repair_logs_only_static_issue_code(monkeypatch, caplog):
    partition = _partition("partition-source-log", "A1:B2")
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        arguments = _partition_args(partition)
        arguments["result"]["all_assumption_candidates"] = [
            _candidate_without_source()
            if calls == 1
            else _candidate_with_source()
        ]
        return _response(
            request,
            response_id=f"resp-log-{calls}",
            tool_name="submit_partition_result",
            arguments=arguments,
        )

    caplog.set_level(logging.WARNING)
    _driver(monkeypatch, handler).extract(partition, _envelope(partition))

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "candidate_source_missing" in rendered
    assert "secret-model-label" not in rendered
    assert "secret-cell-sentinel" not in rendered
    assert "secret-api-key-sentinel" not in rendered
```

- [ ] **Step 3: Run the new driver tests to verify RED**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_driver.py::test_missing_candidate_source_gets_one_targeted_correction \
  experiments/workbook_agent_poc/tests/test_partition_driver.py::test_two_source_less_results_raise_without_third_call \
  experiments/workbook_agent_poc/tests/test_partition_driver.py::test_source_repair_logs_only_static_issue_code -q
```

Expected:

- the repair-success test incorrectly returns the first malformed result;
- the exhaustion test does not raise;
- the safe validation-code log is absent.

- [ ] **Step 4: Wire the validator into extraction only**

In `partition_driver.py`, import:

```python
from partition_contract import (
    PARTITION_SYSTEM_PROMPT,
    RECONCILIATION_SYSTEM_PROMPT,
    SUBMIT_PARTITION_TOOL,
    SUBMIT_RECONCILIATION_TOOL,
    PartitionResultIssue,
    serialize_partition_envelope,
    validate_partition_tool_arguments,
)
```

Pass the validator from `extract()`:

```python
result = self._structured_operation(
    initial_input=[{"role": "user", "content": payload}],
    instructions=PARTITION_SYSTEM_PROMPT,
    tool=SUBMIT_PARTITION_TOOL,
    expected_tool_name="submit_partition_result",
    required_fields={
        "workbook_version",
        "partition_id",
        "sheet_name",
        "primary_range",
        "result",
    },
    operation_id=partition.partition_id,
    payload_validator=validate_partition_tool_arguments,
)
```

Do not pass it from `resolve_conflict()`.

Extend `_structured_operation`:

```python
def _structured_operation(
    self,
    *,
    initial_input: list[dict[str, Any]],
    instructions: str,
    tool: dict[str, Any],
    expected_tool_name: str,
    required_fields: set[str],
    operation_id: str,
    payload_validator: (
        Callable[[dict[str, Any]], PartitionResultIssue | None] | None
    ) = None,
) -> dict[str, Any]:
```

Replace the current `parsed` acceptance block with:

```python
parsed = self._parse_tool_result(
    response,
    expected_tool_name=expected_tool_name,
    required_fields=required_fields,
)
issue = (
    payload_validator(parsed)
    if parsed is not None and payload_validator is not None
    else None
)
if parsed is not None and issue is None:
    return parsed

validation_code = (
    issue.code if issue is not None else "partition_tool_call_invalid"
)
logger.warning(
    "partition_structured_output_rejected operation_id=%s "
    "validation_code=%s structured_attempt=%s",
    operation_id,
    validation_code,
    structured_attempt,
)
if structured_attempt == 0:
    previous_response_id = response.id
    repair_instruction = (
        issue.repair_instruction
        if issue is not None
        else (
            f"Return exactly one {expected_tool_name} function call "
            "with every required field."
        )
    )
    next_input = [{
        "role": "user",
        "content": repair_instruction,
    }]
```

Keep the current terminal `PartitionStructuredOutputError` unchanged.

- [ ] **Step 5: Run all driver tests**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest experiments/workbook_agent_poc/tests/test_partition_driver.py -q
```

Expected: all driver tests pass. Existing no-function-call correction,
authentication, context, transient retry, independent conflict resolution,
usage, and logging tests must remain green.

- [ ] **Step 6: Run partition pipeline and API regressions**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_contract.py \
  experiments/workbook_agent_poc/tests/test_partition_driver.py \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py \
  tests/test_workbook_validation.py \
  tests/test_experimental_workbook_upload.py -q
```

Expected: zero failures. This proves the repair remains request-scoped and the
public upload/error contract is unchanged.

- [ ] **Step 7: Run the complete deterministic acceptance suite**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest \
  experiments/workbook_agent_poc/tests \
  tests/test_workbook_validation.py \
  tests/test_experimental_workbook_upload.py \
  tests/test_model_extraction_lifecycle.py \
  tests/test_model_extraction_persistence.py \
  tests/test_model_extraction_reload.py \
  tests/test_model_upload_orchestration_service.py \
  tests/test_calculation_integration_service.py \
  tests/test_calculation_api.py -q
```

Expected: zero scoped failures.

Then run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest -q
```

Expected baseline note: the current dirty frontend worktree may still cause
`tests/test_frontend_extraction_loading_contracts.py::test_package_keeps_dependencies_and_lint_contract_unchanged`
to fail. Do not edit the frontend or weaken that test; record its exact result
separately from this scoped fix.

- [ ] **Step 8: Verify scope and commit the driver repair**

Run:

```bash
git diff --name-only HEAD | sort
git diff --check
```

Expected task paths only:

```text
experiments/workbook_agent_poc/partition_driver.py
experiments/workbook_agent_poc/tests/test_partition_driver.py
```

The Task 1 contract files are already committed and must not reappear as
unstaged changes.

Commit:

```bash
git add \
  experiments/workbook_agent_poc/partition_driver.py \
  experiments/workbook_agent_poc/tests/test_partition_driver.py
git diff --cached --check
git diff --cached --stat
git commit -m "fix(agent): repair source-less partition candidates"
```

---

### Task 3: Gated GPT-5.4 Mini Full-Flow Acceptance

**Files:**
- Create after explicit live-call approval:
  `docs/reports/small-workbook-gpt54-mini-source-repair-acceptance.md`
- Do not modify production code in this task.

**Interfaces:**
- Consumes: rebuilt API image containing Tasks 1-2.
- Consumes:
  `/Users/kingjason/Downloads/fixed_solar_project_finance_model_financial_functions.xlsx`.
- Produces: one bounded public upload result, database/calculation evidence, and
  a sanitized report.

- [ ] **Step 1: Stop for explicit live-call authorization**

Before any Azure call, present:

```text
Deterministic repair tests are green. May I run one billable GPT-5.4 mini
upload of fixed_solar_project_finance_model_financial_functions.xlsx?
```

Do not continue until the user explicitly approves. Approval of this plan alone
does not authorize the billable acceptance request.

- [ ] **Step 2: Rebuild and verify API provenance**

Run:

```bash
docker compose build api
docker compose up -d --force-recreate --no-deps api
docker compose ps api
```

Wait for health, then print only non-secret selected configuration:

```bash
docker compose exec -T api python -c '
import os
print({
    "deployment": os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT"),
    "endpoint_configured": bool(os.getenv("AZURE_OPENAI_ENDPOINT")),
    "api_key_configured": bool(os.getenv("AZURE_OPENAI_API_KEY")),
    "partitioned": os.getenv(
        "WORKBOOK_AGENT_PARTITIONED_EXTRACTION_ENABLED",
        "<default:true>",
    ),
})
'
```

Expected: deployment `gpt-5.4-mini`, both booleans true, partitioned mode true
or default true. Never run `docker compose config` because it can display
secrets from `.env`.

- [ ] **Step 3: Repeat the no-Azure workbook preflight**

Run:

```bash
PYTHONPATH=experiments/workbook_agent_poc \
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -c '
from workbook_tools import WorkbookToolset
from workbook_index import WorkbookIndexBuilder
from partition_planner import PartitionPlanner
p = "/Users/kingjason/Downloads/fixed_solar_project_finance_model_financial_functions.xlsx"
tools = WorkbookToolset(file_path=p)
index = WorkbookIndexBuilder().build(tools)
parts = PartitionPlanner().plan(index)
print({
    "content_sheets": len(index.content_sheets),
    "non_empty_cells": index.non_empty_cell_count,
    "partitions": len(parts),
    "max_estimated_total_tokens": max(
        x.estimated_total_tokens for x in parts
    ),
    "max_estimated_raw_tokens": max(
        x.estimated_raw_tokens for x in parts
    ),
    "max_request_bytes": max(x.request_bytes for x in parts),
    "raw_evidence_bytes_total": sum(
        x.raw_evidence_bytes for x in parts
    ),
})
'
```

Expected deterministic inventory:

```text
content_sheets: 8
non_empty_cells: 1534
partitions: 8
max_estimated_total_tokens: 77374
max_estimated_raw_tokens: 65732
max_request_bytes: 154747
raw_evidence_bytes_total: 508362
```

- [ ] **Step 4: Upload the workbook exactly once**

Run:

```bash
curl --fail-with-body --silent --show-error --max-time 1800 \
  -X POST \
  -F 'file=@/Users/kingjason/Downloads/fixed_solar_project_finance_model_financial_functions.xlsx' \
  http://127.0.0.1:8000/api/v1/models/upload \
  -o /tmp/solar-mini-source-repair-result.json \
  -w 'http_code=%{http_code} total_seconds=%{time_total}\n'
```

Do not retry automatically for any status.

- [ ] **Step 5: Inspect a bounded response**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -c '
import json
from pathlib import Path
r = json.loads(
    Path("/tmp/solar-mini-source-repair-result.json").read_text()
)
print({
    "submitted": r.get("submitted"),
    "stop_reason": r.get("stop_reason"),
    "workbook_version_id": r.get("workbook_version_id"),
    "model_version_id": r.get("model_version_id"),
    "driver_meta": r.get("driver_meta"),
    "coverage": {
        key: r.get("coverage", {}).get(key)
        for key in (
            "planned_partition_count",
            "completed_partition_count",
            "missing_partition_ids",
            "missing_primary_ranges",
            "submission_allowed",
            "azure_call_count",
        )
    },
    "validation_summary": r.get("validation_summary"),
    "time_series_summary": r.get("time_series_summary"),
    "errors": r.get("errors"),
})
'
```

Acceptance requires:

- HTTP 200;
- `submitted=true`;
- `stop_reason=submitted`;
- planned/completed partition counts both 8;
- empty missing IDs/ranges;
- `submission_allowed=true`;
- non-null workbook/model version IDs;
- no public errors.

The Azure call count may be greater than 8 only when one or more partitions
used the single approved structured correction. It must remain within the
existing global call budget.

- [ ] **Step 6: Inspect safe logs and database state**

Run:

```bash
docker compose logs --since 30m --no-color api | \
  rg 'partition_structured_output_rejected|partition_failed|candidate_source_missing|POST /api/v1/models/upload'
```

Then:

```bash
docker compose exec -T postgres psql \
  -U investiq -d investiq -v ON_ERROR_STOP=1 \
  -c "
SELECT id, status, validation_status, submitted, stop_reason,
       workbook_version_id
FROM model_versions
ORDER BY created_at DESC
LIMIT 1;
" \
  -c "
SELECT status, COUNT(*)
FROM calculation_rule_extractions
WHERE model_version_id = (
    SELECT id FROM model_versions ORDER BY created_at DESC LIMIT 1
)
GROUP BY status
ORDER BY status;
"
```

Expected: latest model version is `materialized`; calculation preparation has
one existing terminal success/warning status. If the upload fails, record the
safe terminal code/request ID and stop without retry.

- [ ] **Step 7: Create and commit the acceptance report**

Create
`docs/reports/small-workbook-gpt54-mini-source-repair-acceptance.md` with:

```markdown
# Small Workbook GPT-5.4 Mini Source Repair Acceptance

## Git and Docker Provenance
## Non-Secret Azure Configuration
## Deterministic Test Results
## Workbook Preflight
## Live Upload Result
## Structured Repair Evidence
## Persistence and Calculation Preparation
## Remaining Warnings
```

Record exact counts, runtime, request IDs, and status fields. Do not include
keys, endpoints, connection strings, raw cells, candidate payloads, or full
responses.

Commit:

```bash
git add docs/reports/small-workbook-gpt54-mini-source-repair-acceptance.md
git diff --cached --check
git diff --cached --stat
git commit -m "docs: record source repair acceptance"
```

If the live upload fails, use the same report headings, record the failure
without claiming acceptance, and use commit message:

```bash
git commit -m "docs: record source repair validation failure"
```
