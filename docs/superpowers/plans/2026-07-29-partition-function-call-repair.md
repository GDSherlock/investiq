# Partition Function-Call Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the one allowed partition-result correction call comply with the Azure Responses function-calling protocol by acknowledging the pending call with its `call_id`.

**Architecture:** Add one private response-inspection value object inside `partition_driver.py`. When exactly one expected function call is malformed, continue the response with a static `function_call_output`; when no function call exists, retain the existing generic user correction; when pending calls are ambiguous or lack a usable `call_id`, fail locally.

**Tech Stack:** Python 3.12, OpenAI Python SDK 2.45.0, Azure Responses API, `httpx.MockTransport`, `pytest`.

## Global Constraints

- Work only on the current `feature/backend-scale-up` branch.
- Do not enable or redesign strict structured outputs.
- Do not change partition or extraction schemas.
- Do not infer, repair, or backfill source references locally.
- Do not resend or summarize workbook evidence.
- Do not change database tables, migrations, calculation services, frontend code, Docker configuration, environment files, deployment settings, retry counts, call limits, token limits, byte limits, or deadlines.
- Keep the maximum at two structured-output attempts; never add a third attempt.
- Preserve all unrelated modified and untracked files. Stage only paths named by the current task.
- Do not issue a live Azure request until Task 3 receives fresh explicit user authorization.

---

### Task 1: Make the correction request protocol-correct

**Files:**
- Modify: `experiments/workbook_agent_poc/partition_driver.py:1-350`
- Modify: `experiments/workbook_agent_poc/tests/test_partition_driver.py:1-430`

**Interfaces:**
- Consumes: `PartitionResultIssue(code: str, repair_instruction: str)` from `partition_contract.py`.
- Produces: private `_ToolCallInspection(arguments, call_id, has_function_calls)`.
- Produces: unchanged public `AzurePartitionDriver.extract()` and `resolve_conflict()` interfaces.
- Produces: a correction input of exactly one Responses API `function_call_output` when an expected pending function call can be acknowledged.

- [ ] **Step 1: Strengthen the existing source-repair test with an Azure-protocol-aware fake**

Replace `test_missing_candidate_source_gets_one_targeted_correction` so the
mock returns the same HTTP 400 Azure produces when the second request leaves a
pending function call unresolved:

```python
def test_missing_candidate_source_gets_protocol_correct_correction(monkeypatch):
    partition = _partition("partition-source-repair", "A1:B2")
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 2:
            correction_items = body["input"]
            if (
                len(correction_items) != 1
                or correction_items[0].get("type") != "function_call_output"
                or correction_items[0].get("call_id") != "call-resp-source-1"
            ):
                return httpx.Response(
                    400,
                    request=request,
                    json={
                        "error": {
                            "message": (
                                "No tool output found for function call "
                                "call-resp-source-1."
                            ),
                            "type": "invalid_request_error",
                            "param": "input",
                            "code": None,
                        }
                    },
                )
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
    correction_items = bodies[1]["input"]
    assert correction_items[0]["type"] == "function_call_output"
    assert correction_items[0]["call_id"] == "call-resp-source-1"
    rejection = json.loads(correction_items[0]["output"])
    assert rejection["accepted"] is False
    assert rejection["validation_code"] == "candidate_source_missing"
    assert "source_references" in rejection["repair_instruction"]
    rendered_correction = json.dumps(correction_items)
    assert '"role": "user"' not in rendered_correction
    assert "secret-model-label" not in rendered_correction
    assert result["result"]["all_assumption_candidates"][0][
        "source_references"
    ] == [{"sheet_name": "Model", "cell": "A1"}]
```

- [ ] **Step 2: Add local-failure tests for unusable pending calls**

Allow `_response` to accept an explicit `call_id` while preserving its current
default:

```python
def _response(
    request,
    *,
    response_id,
    tool_name,
    arguments,
    call_id=None,
):
    effective_call_id = (
        f"call-{response_id}" if call_id is None else call_id
    )
    return httpx.Response(
        200,
        request=request,
        headers={"x-request-id": f"request-{response_id}"},
        json={
            "id": response_id,
            "object": "response",
            "created_at": 0,
            "model": "custom-full-deployment",
            "usage": {
                "input_tokens": 120,
                "output_tokens": 20,
                "total_tokens": 140,
            },
            "output": [{
                "id": f"fc-{response_id}",
                "type": "function_call",
                "call_id": effective_call_id,
                "name": tool_name,
                "arguments": json.dumps(arguments),
            }],
        },
    )
```

Add:

```python
def test_missing_call_id_fails_without_correction_call(monkeypatch):
    partition = _partition("partition-missing-call-id", "A1:B2")
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        arguments = _partition_args(partition)
        arguments["result"]["all_assumption_candidates"] = [
            _candidate_without_source()
        ]
        return _response(
            request,
            response_id="resp-missing-call-id",
            tool_name="submit_partition_result",
            arguments=arguments,
            call_id="",
        )

    driver = _driver(monkeypatch, handler)

    with pytest.raises(PartitionStructuredOutputError):
        driver.extract(partition, _envelope(partition))

    assert len(bodies) == 1
    assert driver.call_count == 1


def test_unexpected_function_call_fails_without_correction(monkeypatch):
    partition = _partition("partition-unexpected-tool", "A1:B2")
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return _response(
            request,
            response_id="resp-unexpected-tool",
            tool_name="unexpected_tool",
            arguments={},
        )

    driver = _driver(monkeypatch, handler)

    with pytest.raises(PartitionStructuredOutputError):
        driver.extract(partition, _envelope(partition))

    assert len(bodies) == 1
    assert driver.call_count == 1


def test_multiple_function_calls_fail_without_correction(monkeypatch):
    partition = _partition("partition-multiple-tools", "A1:B2")
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        arguments = json.dumps(_partition_args(partition))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp-multiple-tools",
                "object": "response",
                "created_at": 0,
                "model": "custom-full-deployment",
                "output": [
                    {
                        "id": "fc-multiple-1",
                        "type": "function_call",
                        "call_id": "call-multiple-1",
                        "name": "submit_partition_result",
                        "arguments": arguments,
                    },
                    {
                        "id": "fc-multiple-2",
                        "type": "function_call",
                        "call_id": "call-multiple-2",
                        "name": "submit_partition_result",
                        "arguments": arguments,
                    },
                ],
            },
        )

    driver = _driver(monkeypatch, handler)

    with pytest.raises(PartitionStructuredOutputError):
        driver.extract(partition, _envelope(partition))

    assert len(bodies) == 1
    assert driver.call_count == 1
```

Extend `test_invalid_output_gets_one_same_partition_correction_only` to prove
the no-function-call path remains an ordinary static user correction:

```python
assert bodies[1]["input"][0]["role"] == "user"
assert (
    bodies[1]["input"][0]["content"]
    == "Return exactly one submit_partition_result function call "
       "with every required field."
)
```

Add a malformed-arguments case to prove an expected pending function call is
acknowledged even when its JSON cannot be parsed:

```python
def test_malformed_arguments_get_function_output_correction(monkeypatch):
    partition = _partition("partition-malformed-arguments", "A1:B2")
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "resp-malformed",
                    "object": "response",
                    "created_at": 0,
                    "model": "custom-full-deployment",
                    "output": [{
                        "id": "fc-malformed",
                        "type": "function_call",
                        "call_id": "call-malformed",
                        "name": "submit_partition_result",
                        "arguments": "{",
                    }],
                },
            )
        return _response(
            request,
            response_id="resp-malformed-corrected",
            tool_name="submit_partition_result",
            arguments=_partition_args(partition),
        )

    result = _driver(monkeypatch, handler).extract(
        partition,
        _envelope(partition),
    )

    assert result["partition_id"] == partition.partition_id
    assert bodies[1]["previous_response_id"] == "resp-malformed"
    correction = bodies[1]["input"][0]
    assert correction["type"] == "function_call_output"
    assert correction["call_id"] == "call-malformed"
    rejection = json.loads(correction["output"])
    assert rejection["validation_code"] == "partition_tool_call_invalid"
```

- [ ] **Step 3: Run the focused tests to verify RED**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_driver.py::test_missing_candidate_source_gets_protocol_correct_correction \
  experiments/workbook_agent_poc/tests/test_partition_driver.py::test_missing_call_id_fails_without_correction_call \
  experiments/workbook_agent_poc/tests/test_partition_driver.py::test_unexpected_function_call_fails_without_correction \
  experiments/workbook_agent_poc/tests/test_partition_driver.py::test_multiple_function_calls_fail_without_correction \
  experiments/workbook_agent_poc/tests/test_partition_driver.py::test_malformed_arguments_get_function_output_correction \
  experiments/workbook_agent_poc/tests/test_partition_driver.py::test_invalid_output_gets_one_same_partition_correction_only \
  -q
```

Expected:

- the protocol-aware test receives the simulated HTTP 400 because the current
  correction is an ordinary user message;
- the empty-`call_id`, unexpected-tool, and multiple-call tests observe a
  second call instead of the required local failure;
- the malformed-arguments test observes an ordinary user correction instead
  of `function_call_output`;
- the generic no-function-call assertion passes.

- [ ] **Step 4: Add the private response-inspection value object**

In `partition_driver.py`, import `dataclass` and add this private type after the
logger:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class _ToolCallInspection:
    arguments: dict[str, Any] | None
    call_id: str | None
    has_function_calls: bool
```

Replace `_parse_tool_result` with `_inspect_tool_result`:

```python
@staticmethod
def _inspect_tool_result(
    response: Any,
    *,
    expected_tool_name: str,
    required_fields: set[str],
) -> _ToolCallInspection:
    function_calls = [
        item
        for item in getattr(response, "output", [])
        if getattr(item, "type", None) == "function_call"
    ]
    expected_calls = [
        item
        for item in function_calls
        if getattr(item, "name", None) == expected_tool_name
    ]
    if len(function_calls) != 1 or len(expected_calls) != 1:
        return _ToolCallInspection(
            arguments=None,
            call_id=None,
            has_function_calls=bool(function_calls),
        )

    call = expected_calls[0]
    raw_call_id = getattr(call, "call_id", None)
    call_id = (
        raw_call_id.strip()
        if isinstance(raw_call_id, str) and raw_call_id.strip()
        else None
    )
    try:
        parsed = json.loads(call.arguments or "{}")
    except (TypeError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict) or not required_fields <= set(parsed):
        parsed = None
    return _ToolCallInspection(
        arguments=parsed,
        call_id=call_id,
        has_function_calls=True,
    )
```

- [ ] **Step 5: Build the protocol-correct correction input**

In `_structured_operation`, replace the parser call with:

```python
inspection = self._inspect_tool_result(
    response,
    expected_tool_name=expected_tool_name,
    required_fields=required_fields,
)
parsed = inspection.arguments
```

Keep the existing validator and success return unchanged. Before preparing a
second attempt, reject an unsafe pending-call shape and otherwise choose the
protocol-correct input:

```python
if structured_attempt == 0:
    if inspection.has_function_calls and inspection.call_id is None:
        raise PartitionStructuredOutputError(
            "Azure response contained an unacknowledgeable function call."
        )
    previous_response_id = response.id
    repair_instruction = (
        issue.repair_instruction
        if issue is not None
        else (
            f"Return exactly one {expected_tool_name} function call "
            "with every required field."
        )
    )
    if inspection.call_id is not None:
        next_input = [{
            "type": "function_call_output",
            "call_id": inspection.call_id,
            "output": json.dumps(
                {
                    "accepted": False,
                    "validation_code": validation_code,
                    "repair_instruction": repair_instruction,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }]
    else:
        next_input = [{
            "role": "user",
            "content": repair_instruction,
        }]
```

Do not change `_call_with_retry`, `max_calls_per_operation`, token settings,
reasoning settings, schemas, or pipeline error mapping.

- [ ] **Step 6: Run focused tests to verify GREEN**

Run the exact command from Step 3.

Expected: `6 passed`.

- [ ] **Step 7: Run all partition-driver tests**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest experiments/workbook_agent_poc/tests/test_partition_driver.py -q
```

Expected: every driver test passes, including:

- source-less result corrected with `function_call_output`;
- second invalid result raises without a third call;
- no-function-call result retains its generic user correction;
- logs contain the static issue code but no raw cells, labels, or API keys.

- [ ] **Step 8: Verify scope and commit**

Run:

```bash
git diff --check -- \
  experiments/workbook_agent_poc/partition_driver.py \
  experiments/workbook_agent_poc/tests/test_partition_driver.py
git diff --name-only
git status --short
```

Review the complete diff. The task's intentional paths must be exactly:

```text
experiments/workbook_agent_poc/partition_driver.py
experiments/workbook_agent_poc/tests/test_partition_driver.py
```

Other user-owned dirty paths may remain visible in `git status`; do not stage
them.

Commit:

```bash
git add \
  experiments/workbook_agent_poc/partition_driver.py \
  experiments/workbook_agent_poc/tests/test_partition_driver.py
git diff --cached --check
git diff --cached --name-only
git commit -m "fix(agent): acknowledge rejected partition tool calls"
```

---

### Task 2: Run deterministic regression acceptance

**Files:**
- Do not modify production or test files.
- Do not create an acceptance report in this task.

**Interfaces:**
- Consumes: Task 1 commit.
- Produces: fresh test evidence separating task behavior from unrelated repository baseline changes.

- [ ] **Step 1: Run related partition and upload tests**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_contract.py \
  experiments/workbook_agent_poc/tests/test_partition_driver.py \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py \
  tests/test_workbook_validation.py \
  tests/test_experimental_workbook_upload.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run the deterministic extraction-to-calculation suite**

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
  tests/test_calculation_api.py \
  -q
```

Expected: all selected tests pass, with only explicitly marked skips.

- [ ] **Step 3: Run the full repository suite**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -m pytest -q
```

Expected task result: no failure in partition, extraction, upload,
persistence, or calculation tests. The pre-existing user-owned
`apps/ui/package.json` change may continue to fail
`test_package_keeps_dependencies_and_lint_contract_unchanged` because it adds
`check:number-format`; report that baseline separately and do not change it.

- [ ] **Step 4: Verify no new uncommitted task files remain**

Run:

```bash
git status --short --branch
git log -3 --oneline --decorate
```

Expected: Task 1's two paths are committed. Existing unrelated frontend,
Docker, report, Playwright, and workbook paths remain untouched.

---

### Task 3: Gated GPT-5.4 Mini acceptance

**Files:**
- Do not modify code, schemas, environment files, or Docker configuration.
- Consume:
  `/Users/kingjason/Downloads/fixed_solar_project_finance_model_financial_functions.xlsx`

**Interfaces:**
- Consumes: Task 1 commit and Task 2 deterministic evidence.
- Produces: one bounded upload response, safe runtime logs, and persisted model-version evidence.

- [ ] **Step 1: Stop for fresh live-call authorization**

Present:

```text
Deterministic function-call repair tests are green. May I rebuild the API and
analysis-worker images and run one billable GPT-5.4 mini upload of
fixed_solar_project_finance_model_financial_functions.xlsx?
```

Do not continue until the user explicitly approves. Approval of the spec,
plan, or deterministic implementation does not authorize this Azure request.

- [ ] **Step 2: Rebuild without deleting persistent data**

Run:

```bash
docker compose build api analysis-worker
docker compose up -d --force-recreate --no-deps api analysis-worker
docker compose ps -a
```

Do not run `docker compose down -v`.

- [ ] **Step 3: Verify container code and non-secret configuration**

Run:

```bash
shasum -a 256 \
  experiments/workbook_agent_poc/partition_driver.py \
  experiments/workbook_agent_poc/partition_contract.py
docker compose exec -T analysis-worker sha256sum \
  /app/experiments/workbook_agent_poc/partition_driver.py \
  /app/experiments/workbook_agent_poc/partition_contract.py
docker compose exec -T analysis-worker python -c '
import os
import urllib.parse
endpoint = urllib.parse.urlparse(os.getenv("AZURE_OPENAI_ENDPOINT", ""))
print({
    "deployment": os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT"),
    "endpoint_host": endpoint.hostname,
    "endpoint_path": endpoint.path,
    "api_key_configured": bool(os.getenv("AZURE_OPENAI_API_KEY")),
    "partitioned": os.getenv(
        "WORKBOOK_AGENT_PARTITIONED_EXTRACTION_ENABLED",
        "<default:true>",
    ),
})
'
```

Expected: host/container hashes match, deployment is `gpt-5.4-mini`, endpoint
and API key are configured, and partitioned mode is true or defaults to true.
Never print the API key and never run `docker compose config`.

- [ ] **Step 4: Run the deterministic workbook preflight**

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

Expected:

```text
content_sheets: 8
non_empty_cells: 1534
partitions: 8
max_estimated_total_tokens: 77374
max_estimated_raw_tokens: 65732
max_request_bytes: 154747
raw_evidence_bytes_total: 508362
```

- [ ] **Step 5: Upload exactly once**

Run:

```bash
curl --fail-with-body --silent --show-error --max-time 1800 \
  -X POST \
  -F 'file=@/Users/kingjason/Downloads/fixed_solar_project_finance_model_financial_functions.xlsx' \
  http://127.0.0.1:8000/api/v1/models/upload \
  -o /tmp/solar-mini-function-call-repair-result.json \
  -w 'http_code=%{http_code} total_seconds=%{time_total}\n'
```

Do not retry automatically for any HTTP status or client error.

- [ ] **Step 6: Inspect bounded response, logs, and database state**

Run:

```bash
'/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' \
  -c '
import json
from pathlib import Path
r = json.loads(
    Path("/tmp/solar-mini-function-call-repair-result.json").read_text()
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
    "errors": r.get("errors"),
})
'
docker compose logs --since 30m --no-color api analysis-worker | \
  rg 'partition_structured_output_rejected|partition_call_failed|partition_failed|candidate_source_missing|POST /api/v1/models/upload'
docker compose exec -T postgres sh -lc '
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -x -c "
SELECT id, status, validation_status, submitted, stop_reason,
       error_code, created_at, completed_at
FROM model_versions
ORDER BY created_at DESC
LIMIT 1;
"
'
```

Acceptance requires:

- HTTP 200;
- `submitted=true`;
- `stop_reason=submitted`;
- planned and completed partition counts both equal 8;
- empty missing partition IDs and ranges;
- `submission_allowed=true`;
- non-null workbook/model version IDs;
- no `AZURE_RESPONSES_ERROR`;
- no correction HTTP 400;
- latest persisted model version reaches the expected successful terminal state.

If any condition fails, stop without retrying. Report the safe terminal code,
Azure request ID, completed-partition count, and persisted state before
proposing another change.
