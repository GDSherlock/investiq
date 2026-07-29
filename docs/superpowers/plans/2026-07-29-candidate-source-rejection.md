# Candidate-Level Source Rejection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A partition candidate with missing, malformed, or nonexistent `source_references` is preserved for deterministic validation and receives `validation_status="rejected"` without terminating the partition or workbook upload.

**Architecture:** Keep the current stateless Azure partition driver, partition envelopes, final extraction schema, and existing validator/persistence pipeline. Narrow the driver-side partition validator to envelope and bucket shape only; move source handling to `PartitionReconciler`, which passes source-valid candidates through the existing normalization path and moves source-invalid items into `review_candidates` for the existing deterministic validator. Source-invalid items are never canonicalized, because canonical persistence already requires a source-valid, non-rejected validation result.

**Tech Stack:** Python 3.12, OpenAI Responses function calls, openpyxl-backed workbook facts, pytest.

## Execution Status

- Tasks 1-4 and the local portions of Task 5 were completed on
  `feature/backend-scale-up`.
- Implementation commits:
  - `5069cf5 fix(agent): defer partition source defects to candidate validation`
  - `b9b4d01 fix(agent): reject malformed candidate sources safely`
  - `568bfa7 fix(agent): quarantine partition candidates with invalid sources`
  - `67deb11 test(agent): keep workbook submission after source rejection`
- Focused local acceptance: `355 passed, 1 skipped`.
- Full Python suite: `674 passed, 5 skipped, 1` unrelated existing frontend
  contract failure caused by the user-owned `apps/ui/package.json` change.
- Real Solar workbook local partition acceptance: `8/8` partitions completed,
  `submitted=true`, one source-less candidate rejected, and zero Azure calls.
- Task 5's real Azure upload remains intentionally unexecuted pending fresh
  user authorization.

## Global Constraints

- Work only on branch `feature/backend-scale-up`.
- Do not change database tables, Alembic migrations, public API schemas, frontend code, calculation-engine code, Docker configuration, environment files, prompts, partition sizes, token limits, byte limits, deadlines, retries, or Azure deployment settings.
- Do not add evidence IDs or redesign the Azure candidate output schema in this minimum change.
- Do not infer or backfill a source from labels, values, neighboring cells, sheet names, partition ranges, or formulas.
- A source-valid candidate must continue through the existing backend normalization, deduplication, and conflict-resolution path unchanged.
- A candidate source error (`candidate_source_missing`, `candidate_source_invalid`, or `candidate_source_not_found`) must be candidate-local and must not raise `PartitionPipelineError`.
- A malformed partition envelope, wrong workbook/partition binding, non-list bucket, Azure transport/authentication/context error, or invalid canonical financial-series descriptor remains terminal under existing behavior.
- `scenario_structures` and `sensitivity_structures` with source errors must not terminate the workbook. They are moved into `review_candidates` as source-rejected audit items and are omitted from their final structure buckets.
- Preserve invalid candidate content for audit, but logs must contain only static codes, partition IDs, bucket names, and item indexes; never cell values, labels, formulas, prompts, credentials, or raw Azure arguments.
- Deterministic verification must make zero Azure calls. Any real Azure validation requires a fresh explicit user approval after local tests and commits pass.

## File Structure

- Modify `experiments/workbook_agent_poc/partition_contract.py`: validate partition result/bucket container shape, but do not reject a whole function call for candidate-local source defects.
- Modify `experiments/workbook_agent_poc/validator.py`: make every missing or malformed source shape return a normal rejected validation result instead of raising.
- Modify `experiments/workbook_agent_poc/partition_reconciler.py`: quarantine source-invalid candidates in `review_candidates` per item while preserving current terminal behavior for partition-level faults.
- Modify `experiments/workbook_agent_poc/tests/test_partition_contract.py`: lock the new driver-boundary contract.
- Modify `experiments/workbook_agent_poc/tests/test_partition_driver.py`: prove source-less output is accepted in one Azure operation and is not sent through structured-output correction.
- Modify `experiments/workbook_agent_poc/tests/test_validator.py`: prove malformed source shapes are rejected safely.
- Modify `experiments/workbook_agent_poc/tests/test_partition_reconciler.py`: prove valid candidates survive and invalid candidates/structures are quarantined.
- Modify `experiments/workbook_agent_poc/tests/test_partition_pipeline.py`: prove a mixed partition run submits the workbook and produces candidate-level rejection.
- Modify `tests/test_workbook_validation.py`: prove the API adapter returns a successful workbook result with a rejected candidate instead of `WORKBOOK_VALIDATION_ERROR`.
- Do not modify `experiments/workbook_agent_poc/partition_driver.py`, `experiments/workbook_agent_poc/partition_pipeline.py`, `apps/api/app/workbook_validation.py`, or persistence production code unless a RED test exposes behavior inconsistent with this plan; stop for review before expanding production scope.

---

### Task 1: Make Source Defects Non-Terminal at the Azure Driver Boundary

**Files:**
- Modify: `experiments/workbook_agent_poc/partition_contract.py:31-118`
- Modify: `experiments/workbook_agent_poc/tests/test_partition_contract.py:14-90`
- Modify: `experiments/workbook_agent_poc/tests/test_partition_driver.py:242-331,445-498`

**Interfaces:**
- Consumes: `validate_partition_tool_arguments(arguments: dict[str, Any]) -> PartitionResultIssue | None`.
- Produces: the same function and return type, but source defects inside otherwise object-shaped candidate items return `None`.

- [ ] **Step 1: Replace the source-fatal contract tests with candidate-local expectations**

Replace the current assertions that expect `candidate_source_missing` or
`candidate_source_invalid` with:

```python
@pytest.mark.parametrize("bucket", SOURCE_BOUND_BUCKETS)
def test_source_defect_does_not_reject_complete_partition_arguments(bucket):
    arguments = _arguments()
    arguments["result"][bucket] = [{
        key: value
        for key, value in _valid_candidate().items()
        if key != "source_references"
    }]

    assert validate_partition_tool_arguments(arguments) is None


@pytest.mark.parametrize(
    "source_references",
    [
        [],
        ["Inputs!B2"],
        [{}],
        [{"sheet_name": "", "cell": "B2"}],
        [{"sheet_name": "Inputs", "cell": ""}],
    ],
)
def test_invalid_source_shape_is_deferred_to_candidate_validator(source_references):
    arguments = _arguments()
    candidate = _valid_candidate()
    candidate["source_references"] = source_references
    arguments["result"]["all_assumption_candidates"] = [candidate]

    assert validate_partition_tool_arguments(arguments) is None
```

Keep the tests proving that a missing `result`, missing required bucket,
non-list bucket, or non-object candidate item is still rejected at this
boundary.

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_contract.py -q
```

Expected: the new source-deferral cases fail because the current validator
still returns `candidate_source_missing` or `candidate_source_invalid`.

- [ ] **Step 3: Remove only candidate source-content checks from the partition validator**

Keep the existing `result`, required-bucket, list, and object checks. Remove
the `source_references` loop from `validate_partition_tool_arguments`:

```python
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
return None
```

Do not remove `source_references` from `SUBMIT_PARTITION_TOOL`. It remains the
desired model output and schema guidance; the change is only failure
granularity.

- [ ] **Step 4: Update driver protocol tests**

Replace the source-repair tests with assertions that one source-less function
call is returned without a correction request:

```python
def test_missing_candidate_source_returns_without_correction(monkeypatch):
    partition = _partition("partition-source-local-rejection", "A1:B2")
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        arguments = _partition_args(partition)
        arguments["result"]["all_assumption_candidates"] = [
            _candidate_without_source()
        ]
        return _response(
            request,
            response_id="resp-source-local-rejection",
            tool_name="submit_partition_result",
            arguments=arguments,
        )

    result = _driver(monkeypatch, handler).extract(
        partition,
        _envelope(partition),
    )

    assert len(bodies) == 1
    assert result["result"]["all_assumption_candidates"][0].get(
        "source_references"
    ) is None
```

Change the missing-`call_id` test to use malformed JSON arguments, because a
valid accepted function call does not need a follow-up acknowledgement.
Keep the existing protocol-correction tests for malformed JSON, missing outer
fields, no function call, unexpected function name, and multiple function
calls.

- [ ] **Step 5: Run contract and driver tests**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_contract.py \
  experiments/workbook_agent_poc/tests/test_partition_driver.py -q
```

Expected: PASS; a source-less candidate uses one driver call, while malformed
partition-level output retains the existing bounded correction behavior.

- [ ] **Step 6: Commit the driver-boundary change**

```bash
git add \
  experiments/workbook_agent_poc/partition_contract.py \
  experiments/workbook_agent_poc/tests/test_partition_contract.py \
  experiments/workbook_agent_poc/tests/test_partition_driver.py
git diff --cached --check
git commit -m "fix(agent): defer partition source defects to candidate validation"
```

---

### Task 2: Make the Existing Validator Reject Every Invalid Source Shape Safely

**Files:**
- Modify: `experiments/workbook_agent_poc/validator.py:50-70`
- Modify: `experiments/workbook_agent_poc/tests/test_validator.py:81-90`

**Interfaces:**
- Consumes: `validate_candidate(tools, graph, cand) -> dict[str, Any]`.
- Produces: the same validation-result schema with `source_validation_status="rejected"`, `validation_status="rejected"`, `invalid_source=True`, and a static `rejection_reason`.

- [ ] **Step 1: Add RED tests for malformed source containers**

Add:

```python
def test_non_list_source_references_rejected_without_exception():
    r = V("no_assumptions_sheet").run({
        "candidate_id": "shape-1",
        "submitted_role": "hardcoded_input",
        "raw_value": 1,
        "source_references": "Funding!C3",
    })
    assert r["validation_status"] == "rejected"
    assert r["invalid_source"] is True
    assert r["rejection_reason"] == "invalid_source_shape"


def test_non_object_source_reference_rejected_without_exception():
    r = V("no_assumptions_sheet").run({
        "candidate_id": "shape-2",
        "submitted_role": "hardcoded_input",
        "raw_value": 1,
        "source_references": ["Funding!C3"],
    })
    assert r["validation_status"] == "rejected"
    assert r["invalid_source"] is True
    assert r["rejection_reason"] == "invalid_source_shape"


def test_blank_source_fields_rejected_without_exception():
    r = V("no_assumptions_sheet").run({
        "candidate_id": "shape-3",
        "submitted_role": "hardcoded_input",
        "raw_value": 1,
        "source_references": [{"sheet_name": "", "cell": ""}],
    })
    assert r["validation_status"] == "rejected"
    assert r["invalid_source"] is True
    assert r["rejection_reason"] == "invalid_source_shape"
```

- [ ] **Step 2: Run the validator tests and verify RED**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_validator.py -q
```

Expected: malformed string/list shapes currently raise before producing a
validation result.

- [ ] **Step 3: Add explicit source-container validation**

Replace the first-reference extraction with:

```python
refs = cand.get("source_references")
if not isinstance(refs, list) or not refs:
    return _result(
        cid,
        submitted_role,
        source="rejected",
        overall="rejected",
        rejected=["no source_references"],
        review=True,
        invalid_source=True,
        rejection_reason="no_source",
        cand=cand,
    )

ref = refs[0]
if not isinstance(ref, dict):
    return _result(
        cid,
        submitted_role,
        source="rejected",
        overall="rejected",
        rejected=["invalid source reference shape"],
        review=True,
        invalid_source=True,
        rejection_reason="invalid_source_shape",
        cand=cand,
    )

sheet = ref.get("sheet_name")
cell = ref.get("cell")
if (
    not isinstance(sheet, str)
    or not sheet.strip()
    or not isinstance(cell, str)
    or not cell.strip()
):
    return _result(
        cid,
        submitted_role,
        source="rejected",
        overall="rejected",
        rejected=["invalid source reference shape"],
        review=True,
        invalid_source=True,
        rejection_reason="invalid_source_shape",
        cand=cand,
    )
```

Then keep the existing `tools.get_cell(sheet, cell)` and `ToolError`
handling. Do not parse or repair model-authored references.

- [ ] **Step 4: Run validator tests**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_validator.py -q
```

Expected: PASS; every invalid source shape returns a rejected result without
raising.

- [ ] **Step 5: Commit validator hardening**

```bash
git add \
  experiments/workbook_agent_poc/validator.py \
  experiments/workbook_agent_poc/tests/test_validator.py
git diff --cached --check
git commit -m "fix(agent): reject malformed candidate sources safely"
```

---

### Task 3: Quarantine Source-Invalid Candidates During Reconciliation

**Files:**
- Modify: `experiments/workbook_agent_poc/partition_reconciler.py:42-55,138-184,237-370`
- Modify: `experiments/workbook_agent_poc/tests/test_partition_reconciler.py:169-275`
- Modify: `experiments/workbook_agent_poc/tests/test_partition_pipeline.py:49-161`

**Interfaces:**
- Consumes: `_normalize_candidate(index, bucket, candidate) -> _CandidateRecord`, which continues to raise source-specific `ReconciliationError` values.
- Produces: `PartitionReconciler.reconcile(...) -> ReconciliationOutcome`; source-valid items are normalized and source-invalid candidates or structures move to `review_candidates` with their original bucket recorded in `source_contract_bucket`.

- [ ] **Step 1: Add RED tests for mixed valid and source-invalid candidates**

Add:

```python
def test_source_invalid_candidate_is_quarantined_without_losing_valid_candidate():
    index = _index()
    partition = _partition("partition-mixed-source")
    valid = _candidate("Inputs", "B1")
    invalid = _candidate("Inputs", "B1")
    invalid["candidate_id"] = "missing-source"
    invalid["source_references"] = []
    submitted = _bound(partition)
    submitted["result"]["all_assumption_candidates"] = [valid, invalid]

    outcome = PartitionReconciler().reconcile(index, [submitted])

    candidates = outcome.final_extraction["all_assumption_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["reconciliation_status"] == "validated_source"
    review = outcome.final_extraction["review_candidates"]
    assert any(
        candidate.get("candidate_id") == "missing-source"
        and candidate.get("source_references") == []
        for candidate in review
    )
```

Add separate cases for a source string, a nonexistent sheet/cell, and a
source-less `scenario_structures` item. The structure case must assert that
the item is absent from `scenario_structures`, present in
`review_candidates`, and carries `source_contract_bucket="scenario_structures"`.

Also add this deterministic mixed-source driver and pipeline test to
`test_partition_pipeline.py` before changing the reconciler:

```python
class MixedSourcePartitionDriver(RecordingPartitionDriver):
    def __init__(self):
        super().__init__()
        self.emitted = False

    def extract(self, partition, envelope):
        result = super().extract(partition, envelope)
        if not self.emitted:
            self.emitted = True
            result["result"]["all_assumption_candidates"].append({
                "candidate_id": "source-less",
                "original_label": "Unbound candidate",
                "submitted_role": "hardcoded_input",
                "raw_value": 123,
                "source_references": [],
            })
        return result


def test_source_less_candidate_is_rejected_without_failing_workbook(tmp_path):
    tools = _tools(tmp_path)
    run = run_partitioned_extraction(
        MixedSourcePartitionDriver(),
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
    assert run["coverage"]["submission_allowed"] is True
    assert any(
        item["candidate_id"] == "source-less"
        and item["validation_status"] == "rejected"
        and item["invalid_source"] is True
        for item in validation
    )
    assert any(
        item["validation_status"] != "rejected"
        for item in validation
    )
```

- [ ] **Step 2: Run reconciler tests and verify RED**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py::test_source_less_candidate_is_rejected_without_failing_workbook \
  -q
```

Expected: source errors currently raise `ReconciliationError` and abort the
entire reconciliation/pipeline.

- [ ] **Step 3: Add a narrow source-error classification**

Add:

```python
_CANDIDATE_SOURCE_ERROR_CODES = {
    "candidate_source_missing",
    "candidate_source_invalid",
    "candidate_source_not_found",
}
```

Do not catch `partition_workbook_mismatch`, `partition_result_invalid`,
`partition_bucket_invalid`, series errors, or any other reconciliation code.

- [ ] **Step 4: Preserve source-invalid candidate items for validation**

Wrap only `_normalize_candidate` in the candidate loop:

```python
try:
    record = _normalize_candidate(index, bucket, item)
except ReconciliationError as exc:
    if exc.code not in _CANDIDATE_SOURCE_ERROR_CODES:
        raise
    rejected = deepcopy(item)
    rejected.setdefault(
        "candidate_id",
        _hash_identity(
            index.workbook_version,
            str(partial.get("partition_id")),
            bucket,
            str(item_index),
            "source-rejected",
        ),
    )
    rejected["source_contract_bucket"] = bucket
    final["review_candidates"].append(rejected)
    warnings.append(
        f"candidate_source_rejected:{partial.get('partition_id')}:"
        f"{bucket}:{item_index}:{exc.code}"
    )
    continue
records_by_source.setdefault(record.sources, []).append(record)
```

Use `enumerate(items)` to provide `item_index`. The warning is static
provenance only and must not include `item`, source text, labels, or values.

- [ ] **Step 5: Quarantine invalid structures as rejected review candidates**

Apply the same narrow catch to `STRUCTURE_BUCKETS`. On a source error, copy
the structure, assign a deterministic `candidate_id` when missing, set
`source_contract_bucket` to its original structure bucket, and append it to
`final["review_candidates"]`. Do not append it to the final scenario or
sensitivity structure bucket.

Return `warnings=tuple(warnings)` in `ReconciliationOutcome`. Keep source-valid
structures on the existing normalization path.

- [ ] **Step 6: Run reconciler and validator tests**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py \
  experiments/workbook_agent_poc/tests/test_validator.py -q
```

Expected: PASS; source-valid candidates retain authoritative workbook values,
while every source-invalid item remains available for a rejected validation
result.

- [ ] **Step 7: Commit candidate-level reconciliation**

```bash
git add \
  experiments/workbook_agent_poc/partition_reconciler.py \
  experiments/workbook_agent_poc/tests/test_partition_reconciler.py \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py
git diff --cached --check
git commit -m "fix(agent): quarantine partition candidates with invalid sources"
```

---

### Task 4: Prove Workbook Submission Continues and Persistence Excludes Rejected Candidates

**Files:**
- Modify: `tests/test_workbook_validation.py:130-160,489-538`
- Modify: `tests/test_model_extraction_lifecycle.py`
- Test only: `tests/test_model_extraction_persistence.py`

**Interfaces:**
- Consumes: unchanged `run_partitioned_extraction(...)` and `run_workbook_validation(...)`.
- Produces: no new public fields; existing `validation_results` contains source rejections and existing `validation_summary.rejected` counts them.

- [ ] **Step 1: Re-run the candidate-level pipeline acceptance from Task 3**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py::test_source_less_candidate_is_rejected_without_failing_workbook \
  -q
```

Expected: PASS.

- [ ] **Step 2: Add an API adapter regression**

Add a `PartitionedSourceLessDriver` in `tests/test_workbook_validation.py` and
assert:

```python
result = run_workbook_validation(
    FIXTURE.read_bytes(),
    FIXTURE.name,
    partition_driver_factory=PartitionedSourceLessDriver,
)

assert result["submitted"] is True
assert result["stop_reason"] == "submitted"
assert result["errors"] == []
assert result["validation_summary"]["rejected"] >= 1
assert any(
    item["validation_status"] == "rejected"
    and item["invalid_source"] is True
    for item in result["validation_results"]
)
```

This test must call no network and must not expect
`WorkbookValidationError`.

- [ ] **Step 3: Run integration and persistence regressions**

Run:

```bash
.venv_mac/bin/python3 -m pytest \
  experiments/workbook_agent_poc/tests/test_partition_pipeline.py \
  tests/test_workbook_validation.py \
  tests/test_experimental_workbook_upload.py \
  tests/test_model_extraction_lifecycle.py \
  tests/test_model_extraction_persistence.py \
  tests/test_model_upload_orchestration_service.py -q
```

Expected: PASS. Rejected candidates remain in the extraction/validation audit
snapshot but create no canonical parameter or output rows because persistence
requires source-valid, non-rejected validation.

- [ ] **Step 4: Commit the end-to-end regression**

```bash
git add \
  tests/test_workbook_validation.py \
  tests/test_model_extraction_lifecycle.py
git diff --cached --check
git commit -m "test(agent): keep workbook submission after source rejection"
```

---

### Task 5: Local Acceptance and Gated Live Validation

**Files:**
- No production changes.
- Update only this plan's checkbox state during execution if requested.

**Interfaces:**
- Consumes: Tasks 1-4 commits.
- Produces: deterministic acceptance evidence and, only after separate approval, one real Azure upload result.

- [ ] **Step 1: Run the focused workbook-agent suite**

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
  tests/test_calculation_api.py -q
```

Expected: PASS, with no Azure requests.

- [ ] **Step 2: Run repository hygiene checks**

```bash
git diff --check
git status --short --branch
git log -5 --oneline --decorate
```

Expected: only pre-existing user-owned frontend, Docker, report, Playwright,
and workbook changes remain uncommitted. No unrelated path is staged.

- [ ] **Step 3: Review the exact implementation range**

```bash
git diff --stat 9cfce68..HEAD
git diff --check 9cfce68..HEAD
```

Expected: production changes are limited to
`partition_contract.py`, `validator.py`, and `partition_reconciler.py`;
remaining changes are focused tests and this plan.

- [ ] **Step 4: Stop for fresh Azure authorization**

Present the deterministic results, commit hashes, and exact diff. Ask for
approval before rebuilding Docker or uploading
`fixed_solar_project_finance_model_financial_functions.xlsx`.

- [ ] **Step 5: If separately approved, run one upload and do not retry**

Acceptance requires:

- HTTP 200;
- `submitted=true`;
- `stop_reason=submitted`;
- planned and completed partition counts both equal 8;
- `submission_allowed=true`;
- no `AZURE_RESPONSES_ERROR`;
- no `WORKBOOK_VALIDATION_ERROR`;
- at least one source-invalid Azure candidate, if emitted, appears as a
  candidate-level rejected validation result;
- the model version reaches the normal successful terminal state;
- rejected source candidates produce no canonical parameter/output rows.

If the model emits no source-invalid candidate on that run, success is still
valid; the deterministic regression is the proof of the rejection branch.
Do not issue a second upload automatically.
