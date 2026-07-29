# Quarantine Invalid Financial-Series Ranges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject only the individual `financial_series` descriptor whose range is empty, unqualified without `sheet_name`, or invalid A1 notation, while allowing the workbook and every other valid result to continue through submission and persistence.

**Architecture:** Add a narrow per-descriptor syntax gate in `PartitionReconciler` before canonical financial-series reconciliation. Only `series_range_invalid` is converted into an existing `review_candidates` audit item; `series_source_not_found`, `partition_series_invalid`, and all other structural errors remain terminal. Reuse the existing snapshot and validation JSON columns, so rejected series never reach canonical financial-series tables and no database schema changes are required.

**Tech Stack:** Python 3.12, pytest, openpyxl range parsing, FastAPI workbook validation, SQLAlchemy persistence, PostgreSQL/SQLite test fixtures.

## Global Constraints

- Work on the current `feature/backend-scale-up` branch and preserve unrelated dirty/untracked files.
- Use RED → GREEN for every production behavior change.
- Catch only `ReconciliationError.code == "series_range_invalid"` at the individual financial-series descriptor boundary.
- Empty range, unqualified range without `sheet_name`, and invalid A1 notation reject only that descriptor.
- `series_source_not_found`, `partition_series_invalid`, workbook/partition mismatches, and every other structural error remain workbook-terminal.
- Do not fabricate, infer, repair, or substitute any workbook range.
- Rejected series must not enter `financial_series` or `financial_series_values`.
- Persist the rejection audit through existing `extraction_snapshot_json` and `validation_results_json`.
- Do not create or modify migrations, tables, columns, ORM models, repository interfaces, calculation-engine code, frontend code, Docker configuration, Azure prompts, or Azure tool schemas.
- Local tests must not call Azure.
- Do not perform a real Azure upload until all local verification is green, the running container provenance/configuration is verified, and the user gives fresh approval for exactly one upload with no automatic retry.

---

### Task 1: Quarantine Only Syntactically Invalid Financial-Series Ranges

**Files:**
- Modify: `experiments/workbook_agent_poc/partition_reconciler.py`
- Test: `experiments/workbook_agent_poc/tests/test_partition_reconciler.py`

**Interfaces:**
- Consumes: `_parse_range(value: Any, *, default_sheet: Any = None) -> _RangeRef` and `ReconciliationError`.
- Produces: `_series_range_rejected_candidate(...) -> dict[str, Any]`, plus a `review_candidates` audit item marked with `reconciliation_rejection_reason="series_range_invalid"`.

- [ ] **Step 1: Add failing parameterized reconciliation tests**

Add `import pytest` and import `ReconciliationError` in
`test_partition_reconciler.py`. Add a parameterized test covering all approved
range failures while retaining one valid series in the same partial:

```python
@pytest.mark.parametrize(
    ("period_range", "value_range", "sheet_name"),
    [
        ("", "Forecast!C8:J8", "Forecast"),
        ("Forecast!C3:J3", "", "Forecast"),
        ("C3:J3", "C8:J8", None),
        ("Forecast!not-a-range", "Forecast!C8:J8", "Forecast"),
    ],
)
def test_invalid_series_range_is_quarantined_without_losing_valid_series(
    period_range,
    value_range,
    sheet_name,
):
    index = _index()
    partition = _partition("partition-mixed-series", "Forecast", "A1:J8")
    invalid = _series("Invalid", period_range, value_range)
    invalid["sheet_name"] = sheet_name
    valid = _series(
        "Revenue",
        "Forecast!C3:J3",
        "Forecast!C8:J8",
    )
    submitted = _bound(partition)
    submitted["result"]["financial_series"] = [invalid, valid]

    outcome = PartitionReconciler().reconcile(index, [submitted])

    assert len(outcome.final_extraction["financial_series"]) == 1
    assert outcome.final_extraction["financial_series"][0]["label"] == "Revenue"
    rejected = outcome.final_extraction["review_candidates"]
    assert len(rejected) == 1
    assert rejected[0]["original_label"] == "Invalid"
    assert rejected[0]["submitted_role"] == "financial_series"
    assert rejected[0]["source_contract_bucket"] == "financial_series"
    assert (
        rejected[0]["reconciliation_rejection_reason"]
        == "series_range_invalid"
    )
    assert rejected[0]["source_references"] == []
```

Add a terminal-boundary regression proving a syntactically valid but
nonexistent range is not quarantined:

```python
def test_series_source_not_found_remains_terminal():
    index = _index()
    partition = _partition("partition-missing-series", "Forecast", "A1:J8")
    missing = _series(
        "Missing",
        "Forecast!K3:N3",
        "Forecast!K8:N8",
    )

    with pytest.raises(ReconciliationError) as exc:
        PartitionReconciler().reconcile(
            index,
            [_bound(partition, series=missing)],
        )

    assert exc.value.code == "series_source_not_found"
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py \
  -k 'invalid_series_range or series_source_not_found' -q
```

Expected:

```text
The four invalid-range cases fail with series_range_invalid instead of
returning a submitted reconciliation outcome. The source-not-found regression
already passes or fails only if terminal semantics were accidentally changed.
```

- [ ] **Step 3: Add a deterministic rejected-series audit helper**

Add this focused helper beside `_source_rejected_candidate`:

```python
def _series_range_rejected_candidate(
    index: WorkbookIndex,
    partition_id: str,
    item_index: int,
    descriptor: dict[str, Any],
) -> dict[str, Any]:
    rejected = deepcopy(descriptor)
    rejected["candidate_id"] = _hash_identity(
        index.workbook_version,
        partition_id,
        "financial_series",
        str(item_index),
        "range-rejected",
    )
    rejected["original_label"] = str(
        descriptor.get("label")
        or descriptor.get("series_id")
        or "Unlabelled financial series"
    )
    rejected["submitted_role"] = "financial_series"
    rejected["source_references"] = []
    rejected["source_contract_bucket"] = "financial_series"
    rejected["reconciliation_rejection_reason"] = "series_range_invalid"
    rejected.setdefault("raw_value", None)
    rejected.setdefault("displayed_value", None)
    rejected.setdefault("period", None)
    rejected.setdefault("formula_status", None)
    rejected.setdefault("canonical_name", descriptor.get("series_id"))
    rejected.setdefault("evidence", [])
    return rejected
```

The deterministic ID must depend only on workbook version, partition ID, item
index, bucket, and rejection kind. Do not include range contents in logs or
hash inputs.

- [ ] **Step 4: Validate each submitted series before aggregation**

Replace the unconditional `series.extend(deepcopy(submitted_series))` with:

```python
for item_index, descriptor in enumerate(submitted_series):
    if not isinstance(descriptor, dict):
        raise ReconciliationError(
            "partition_series_invalid",
            "Financial-series descriptor must be an object.",
        )
    try:
        _parse_range(
            descriptor.get("period_range"),
            default_sheet=descriptor.get("sheet_name"),
        )
        _parse_range(
            descriptor.get("value_range"),
            default_sheet=descriptor.get("sheet_name"),
        )
    except ReconciliationError as exc:
        if exc.code != "series_range_invalid":
            raise
        final["review_candidates"].append(
            _series_range_rejected_candidate(
                index,
                str(partial.get("partition_id")),
                item_index,
                descriptor,
            )
        )
        warnings.append(
            "financial_series_rejected:"
            f"{partial.get('partition_id')}:{item_index}:{exc.code}"
        )
        continue
    series.append(deepcopy(descriptor))
```

Do not catch around `_reconcile_series(...)` as a whole. Leaving the existing
canonical reconciliation call outside this catch is what keeps
`series_source_not_found` and all later structural failures terminal.

- [ ] **Step 5: Run focused reconciliation tests**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py -q
```

Expected: all reconciliation tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add \
  experiments/workbook_agent_poc/partition_reconciler.py \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py
git commit -m "fix(agent): quarantine invalid financial series ranges"
```

---

### Task 2: Persist an Explicit Rejected Validation Record

**Files:**
- Modify: `experiments/workbook_agent_poc/validator.py`
- Test: `experiments/workbook_agent_poc/tests/test_validator.py`
- Test: `experiments/workbook_agent_poc/tests/test_partition_pipeline.py`
- Test: `tests/test_workbook_validation.py`

**Interfaces:**
- Consumes: a `review_candidates` item with `reconciliation_rejection_reason="series_range_invalid"`.
- Produces: an existing validation-result object with `validation_status="rejected"`, `rejection_reason="series_range_invalid"`, `invalid_source=False`, and `_bucket="review_candidates"`.

- [ ] **Step 1: Add a failing validator test**

Add:

```python
def test_prevalidated_invalid_series_range_is_rejected_with_exact_reason():
    candidate = {
        "candidate_id": "range-rejected",
        "original_label": "Revenue",
        "submitted_role": "financial_series",
        "raw_value": None,
        "source_references": [],
        "reconciliation_rejection_reason": "series_range_invalid",
    }

    result = V("no_assumptions_sheet").run(candidate)

    assert result["validation_status"] == "rejected"
    assert result["rejection_reason"] == "series_range_invalid"
    assert result["invalid_source"] is False
    assert result["review_required"] is True
    assert result["rejected_claims"] == [
        "financial series range is invalid"
    ]
```

- [ ] **Step 2: Run the validator test to verify RED**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_validator.py::test_prevalidated_invalid_series_range_is_rejected_with_exact_reason \
  -q
```

Expected: FAIL because the current validator classifies the empty
`source_references` as `no_source`.

- [ ] **Step 3: Add the narrow validator branch**

At the start of `validate_candidate`, after reading `candidate_id` and
`submitted_role` but before reading `source_references`, add:

```python
    if (
        cand.get("reconciliation_rejection_reason")
        == "series_range_invalid"
    ):
        return _result(
            cid,
            submitted_role,
            source="rejected",
            overall="rejected",
            rejected=["financial series range is invalid"],
            review=True,
            invalid_source=False,
            rejection_reason="series_range_invalid",
            cand=cand,
        )
```

Do not generalize this into a pass-through for arbitrary model-supplied
rejection reasons. Only the backend-created exact marker is accepted.

- [ ] **Step 4: Run the validator suite**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_validator.py -q
```

Expected: all validator tests pass, including existing `no_source` behavior.

- [ ] **Step 5: Add a deterministic pipeline regression**

In `test_partition_pipeline.py`, add a driver that emits one invalid
financial series once while retaining the fixture's normal valid assumption:

```python
class InvalidSeriesRangeDriver(RecordingPartitionDriver):
    def __init__(self):
        super().__init__()
        self.emitted = False

    def extract(self, partition, envelope):
        result = super().extract(partition, envelope)
        if not self.emitted:
            self.emitted = True
            result["result"]["financial_series"] = [{
                "series_id": "invalid-series",
                "label": "Invalid series",
                "semantic_role": "financial_series",
                "business_role": "revenue",
                "category": "revenue",
                "unit": "USD",
                "frequency": "annual",
                "scenario": None,
                "entity": None,
                "currency": "USD",
                "sheet_name": "Model",
                "period_range": "",
                "value_range": "Model!B1:B4",
                "label_reference": None,
                "reasoning_summary": "No period range was available.",
                "llm_confidence": 0.2,
            }]
        return result
```

Add:

```python
def test_invalid_series_range_rejects_only_series_and_submits_workbook(tmp_path):
    tools = _tools(tmp_path)
    run = run_partitioned_extraction(
        InvalidSeriesRangeDriver(),
        tools,
        limits=_limits(),
    )
    series_outcome = materialize_financial_series(
        tools,
        run["final_extraction"],
    )
    validation = validate_extraction(
        tools,
        run["final_extraction"],
        financial_series_outcome=series_outcome,
    )

    assert run["submitted"] is True
    assert run["stop_reason"] == "submitted"
    assert run["final_extraction"]["financial_series"] == []
    rejected = next(
        item for item in validation
        if item["candidate_id"]
        == run["final_extraction"]["review_candidates"][0]["candidate_id"]
    )
    assert rejected["validation_status"] == "rejected"
    assert rejected["rejection_reason"] == "series_range_invalid"
    assert any(
        item["validation_status"] != "rejected"
        for item in validation
    )
```

- [ ] **Step 6: Add an API-adapter regression**

In `tests/test_workbook_validation.py`, add a
`PartitionedInvalidSeriesRangeDriver` following `PartitionedSourceLessDriver`.
It must emit exactly one range-invalid series on its first partition and
otherwise reuse `PartitionedEmptyDriver`.

Add:

```python
def test_partition_invalid_series_range_does_not_fail_workbook():
    result = run_workbook_validation(
        FIXTURE.read_bytes(),
        FIXTURE.name,
        partition_driver_factory=PartitionedInvalidSeriesRangeDriver,
    )

    assert result["submitted"] is True
    assert result["stop_reason"] == "submitted"
    assert result["errors"] == []
    assert result["validation_summary"]["rejected"] == 1
    assert result["final_extraction"]["financial_series"] == []
    assert any(
        item["validation_status"] == "rejected"
        and item["rejection_reason"] == "series_range_invalid"
        and item["_bucket"] == "review_candidates"
        for item in result["validation_results"]
    )
```

- [ ] **Step 7: Run Task 2 focused tests**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_validator.py \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py \
  tests/test_workbook_validation.py::test_partition_invalid_series_range_does_not_fail_workbook \
  tests/test_workbook_validation.py::test_partition_source_rejection_does_not_fail_workbook \
  -q
```

Expected: all focused tests pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add \
  experiments/workbook_agent_poc/validator.py \
  experiments/workbook_agent_poc/tests/test_validator.py \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py \
  tests/test_workbook_validation.py
git commit -m "test(agent): preserve invalid series rejection audit"
```

---

### Task 3: Prove Canonical Persistence Excludes Only the Rejected Series

**Files:**
- Test: `tests/test_model_extraction_lifecycle.py`
- No production persistence file changes are planned.

**Interfaces:**
- Consumes: existing `final_extraction.review_candidates`,
  `final_extraction.financial_series`, and `validation_results`.
- Produces: evidence that existing JSON snapshot fields retain the rejection
  while canonical tables persist only valid entities.

- [ ] **Step 1: Add the persistence regression**

Add a test beside
`test_source_rejected_review_candidate_is_not_canonicalized`:

```python
def test_range_rejected_series_is_audited_but_not_canonicalized(
    lifecycle_context,
) -> None:
    _engine, _session_factory, session = lifecycle_context
    result = deterministic_extraction_result()
    valid_series_count = len(result["final_extraction"]["financial_series"])
    valid_value_count = 2
    result["final_extraction"]["review_candidates"].append({
        "candidate_id": "range-rejected-series",
        "original_label": "Invalid series",
        "submitted_role": "financial_series",
        "raw_value": None,
        "source_references": [],
        "source_contract_bucket": "financial_series",
        "reconciliation_rejection_reason": "series_range_invalid",
        "period_range": "",
        "value_range": "P&L!B2:C2",
    })
    result["validation_results"].append({
        "candidate_id": "range-rejected-series",
        "original_label": "Invalid series",
        "source_validation_status": "rejected",
        "submitted_role": "financial_series",
        "validated_role": None,
        "validation_status": "rejected",
        "invalid_source": False,
        "rejection_reason": "series_range_invalid",
        "review_required": True,
        "_bucket": "review_candidates",
    })
    service = ModelExtractionPersistenceService(
        session,
        validation_runner=RecordingRunner(result),
    )

    response = service.process_upload(
        persistence_workbook_bytes(),
        "model.xlsx",
    )

    assert _count(session, FinancialSeries) == valid_series_count
    assert _count(session, FinancialSeriesValue) == valid_value_count
    assert _count(session, ModelParameter) == 2
    assert _count(session, CanonicalOutput) == 1
    model_version = session.get(ModelVersion, response["model_version_id"])
    assert any(
        item.get("candidate_id") == "range-rejected-series"
        and item.get("reconciliation_rejection_reason")
        == "series_range_invalid"
        for item in model_version.extraction_snapshot_json[
            "final_extraction"
        ]["review_candidates"]
    )
    assert any(
        item.get("candidate_id") == "range-rejected-series"
        and item.get("rejection_reason") == "series_range_invalid"
        and item.get("validation_status") == "rejected"
        for item in model_version.validation_results_json
    )
```

Use the fixture's actual expected valid-series/value counts if they differ
from the constants above; do not change production persistence behavior to
fit the test.

- [ ] **Step 2: Run the persistence regression to verify GREEN**

This test exercises existing persistence behavior and is expected to pass
without production persistence changes:

```bash
.venv_mac/bin/python3 -m pytest \
  tests/test_model_extraction_lifecycle.py::test_range_rejected_series_is_audited_but_not_canonicalized \
  tests/test_model_extraction_lifecycle.py::test_success_persists_parameter_series_values_and_returns_ids \
  tests/test_model_extraction_lifecycle.py::test_source_rejected_review_candidate_is_not_canonicalized \
  -q
```

Expected: all selected lifecycle tests pass.

- [ ] **Step 3: Prove no database structure files changed**

Run:

```bash
git status --short -- \
  apps/api/alembic \
  apps/api/app/model_extraction_models.py \
  apps/api/app/model_extraction_repository.py \
  apps/api/app/model_extraction_service.py
```

Expected: no Task 1–3 changes in any listed path. Pre-existing user changes,
if any, must be reported and left untouched.

- [ ] **Step 4: Commit Task 3**

```bash
git add tests/test_model_extraction_lifecycle.py
git commit -m "test(agent): exclude rejected series from canonical persistence"
```

---

### Task 4: Run Local Regression and a Gated Live Acceptance

**Files:**
- Read only: `.env`
- Read only: `docker-compose.yml`
- Read only:
  `/Users/kingjason/Downloads/fixed_solar_project_finance_model_financial_functions.xlsx`
- No repository file changes are planned.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: local regression evidence and, only after fresh authorization, one
  bounded live upload result.

- [ ] **Step 1: Run the strict focused suite**

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_contract.py \
  experiments/workbook_agent_poc/tests/test_partition_driver.py \
  experiments/workbook_agent_poc/tests/test_validator.py \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py \
  tests/test_workbook_validation.py \
  tests/test_model_extraction_lifecycle.py \
  -q
```

Expected: all task-related tests pass. Existing openpyxl/Pydantic warnings may
remain.

- [ ] **Step 2: Run the established backend acceptance set**

```bash
.venv_mac/bin/python3 -m pytest \
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

Expected: all task-related tests pass.

- [ ] **Step 3: Run the full local suite**

```bash
.venv_mac/bin/python3 -m pytest -q
```

Expected: no task-related failure. If the pre-existing dirty
`apps/ui/package.json` still adds `check:number-format`, report the known
unrelated failure
`tests/test_frontend_extraction_loading_contracts.py::test_package_keeps_dependencies_and_lint_contract_unchanged`
without modifying UI files.

- [ ] **Step 4: Rebuild without deleting persistent data**

```bash
docker compose build api analysis-worker
docker compose up -d --force-recreate api analysis-worker
docker compose ps -a
```

Do not run `docker compose down`, `down -v`, or remove volumes.

- [ ] **Step 5: Verify current container provenance and non-secret config**

Verify host/container hashes for:

```text
partition_contract.py
partition_driver.py
partition_pipeline.py
partition_reconciler.py
validator.py
```

Then print only:

```text
deployment
endpoint_host/path
api_key_configured boolean
max_output_tokens
reasoning_effort
partitioned flag
```

Required for the current approved environment:

```text
deployment=gpt-5.4-mini
max_output_tokens=66298
reasoning_effort=low
api_key_configured=True
partitioned=true or <default:true>
```

Never print the API key.

- [ ] **Step 6: Stop for fresh live-call approval**

Present:

```text
All local range-quarantine regressions are green. The running worker matches
the current code and uses gpt-5.4-mini / 66298 / low. May I make exactly one
billable Solar workbook upload with no automatic retry?
```

Do not continue until the user explicitly approves this exact call.

- [ ] **Step 7: Upload exactly once after approval**

```bash
curl --fail-with-body --silent --show-error --max-time 1800 \
  -X POST \
  -F 'file=@/Users/kingjason/Downloads/fixed_solar_project_finance_model_financial_functions.xlsx' \
  http://127.0.0.1:8000/api/v1/models/upload \
  -o /tmp/solar-range-quarantine-result.json \
  -w 'http_code=%{http_code} total_seconds=%{time_total}\n'
```

Do not retry for any HTTP status, timeout, Azure error, or local validation
error.

- [ ] **Step 8: Inspect bounded result fields and safe logs**

PASS requires:

```text
http_code=200
submitted=True
stop_reason=submitted
planned_partitions=8
completed_partitions=8
missing_partitions=[]
errors=[]
at least one validation result may be rejected with
rejection_reason=series_range_invalid
no invalid financial series persisted in canonical tables
```

`series_source_not_found` or another structural terminal code remains a real
failure. Report it without retrying or broadening the quarantine boundary.

- [ ] **Step 9: Confirm final Git scope**

```bash
git diff --check
git status --short --branch
git log --oneline -8
git diff --stat HEAD~3..HEAD
```

Expected committed production scope:

```text
experiments/workbook_agent_poc/partition_reconciler.py
experiments/workbook_agent_poc/validator.py
```

Expected committed test scope:

```text
experiments/workbook_agent_poc/tests/test_partition_reconciler.py
experiments/workbook_agent_poc/tests/test_validator.py
experiments/workbook_agent_poc/tests/test_partition_pipeline.py
tests/test_workbook_validation.py
tests/test_model_extraction_lifecycle.py
```

No database migration/model/repository/service, frontend, calculation-engine,
Compose, or environment file belongs in these commits.
