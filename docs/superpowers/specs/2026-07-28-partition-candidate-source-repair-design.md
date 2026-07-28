# Partition Candidate Source Repair Design

## 1. Problem Statement

The real `gpt-5.4-mini` upload of
`fixed_solar_project_finance_model_financial_functions.xlsx` completed all
eight planned Azure partition operations, then failed during deterministic
reconciliation:

```text
terminal_code: candidate_source_missing
completed_partition_count: 8
HTTP response: 500 WORKBOOK_VALIDATION_ERROR
```

The extraction contract already declares `source_references` as required for
candidate objects. Azure function-call arguments are not currently enforced as
a strict nested schema, however, and `AzurePartitionDriver._parse_tool_result`
only verifies:

- exactly one function call with the expected name;
- valid JSON object arguments;
- the outer binding fields.

It therefore accepts a structurally incomplete nested candidate. The defect is
detected only after every partition has completed, when
`PartitionReconciler._normalize_candidate` rejects the candidate.

The fix must reject the malformed partial at the driver boundary and use the
already bounded second structured-output attempt to request one correction.

## 2. Goals

1. Validate source-bearing nested partition results before a partial result is
   accepted.
2. Allow exactly one targeted Azure correction within the same response chain.
3. Preserve workbook provenance: never infer or synthesize a missing source.
4. Fail atomically with the existing typed structured-output error if the
   corrected result is still invalid.
5. Keep public APIs, persistence, calculation preparation, frontend behavior,
   partition budgets, and reconciliation rules unchanged.

## 3. Non-Goals

- Enabling OpenAI/Azure strict JSON Schema mode.
- Adding a JSON Schema runtime dependency.
- Backfilling `source_references` from labels, values, partition ranges, or
  nearby cells.
- Changing candidate routing, business roles, financial-series semantics, or
  final extraction schemas.
- Increasing retry, call, token, byte, partition, or deadline limits.
- Persisting partial partition results or repair prompts.
- Retrying a whole failed upload automatically.

## 4. Selected Approach

Add a small deterministic nested-result validator to
`partition_contract.py`. `AzurePartitionDriver` invokes it after parsing the
outer tool arguments but before returning a partition partial.

When the first result is invalid:

1. record only the safe validation code in logs;
2. retain the first Azure response as `previous_response_id`;
3. send one short targeted correction instruction;
4. require a complete replacement `submit_partition_result` call.

When the second result is invalid, raise
`PartitionStructuredOutputError`. The existing pipeline then discards every
partial result and the API maps the failure to the current sanitized
`WORKBOOK_VALIDATION_ERROR`.

## 5. Contract Validator

### 5.1 Interface

`partition_contract.py` adds:

```python
@dataclass(frozen=True)
class PartitionResultIssue:
    code: str
    repair_instruction: str


def validate_partition_tool_arguments(
    arguments: dict[str, Any],
) -> PartitionResultIssue | None:
    ...
```

The function is pure. It reads no workbook, environment, database, or network
state.

### 5.2 Source-bearing buckets

The validator checks these candidate buckets when present:

```text
metadata
all_assumption_candidates
parameter_candidates
derived_value_candidates
output_candidates
financial_series_candidates
unclassified_inputs
review_candidates
scenario_structures
sensitivity_structures
```

For each bucket:

- the bucket must be a list;
- every item must be an object;
- every item must contain a non-empty `source_references` list;
- every source reference must be an object with non-empty string
  `sheet_name` and `cell` fields.

`all_assumption_candidates` and `output_candidates` remain required list
fields, matching `SUBMIT_RESULT_SCHEMA`.

Canonical `financial_series` is not included in this source-reference rule. It
uses the existing `period_range`, `value_range`, and optional
`label_reference` contract and remains validated by the current series
materialization/reconciliation path.

### 5.3 Issue codes

The validator returns the first deterministic issue in contract bucket order:

```text
partition_result_missing
partition_bucket_missing
partition_bucket_invalid
partition_candidate_invalid
candidate_source_missing
candidate_source_invalid
```

Messages are static and contain no workbook values, labels, formulas, ranges,
or user-authored text.

The correction instruction for `candidate_source_missing` states that every
candidate or structure must cite at least one exact `sheet_name` and `cell`
from the supplied evidence and must return a complete replacement result. It
does not suggest a source and does not repeat raw evidence.

## 6. Driver Flow

`AzurePartitionDriver._structured_operation` gains an optional validator:

```python
payload_validator: (
    Callable[[dict[str, Any]], PartitionResultIssue | None] | None
)
```

`extract()` passes `validate_partition_tool_arguments`.
`resolve_conflict()` passes no nested partition validator and preserves its
current behavior.

For each of the existing two structured attempts:

1. make the Azure Responses call with the current forced tool choice;
2. parse exactly one matching function call;
3. validate the existing outer required fields;
4. run the optional nested validator;
5. return only when both parsing and validation succeed.

After a first invalid result, the next request uses the response's ID as
`previous_response_id` and a targeted repair instruction. After a second
invalid result, it raises `PartitionStructuredOutputError`.

The existing `max_calls_per_operation` remains unchanged. It already accounts
for two structured attempts and the bounded transport retry allowance.

## 7. Error and Logging Behavior

Add one safe warning event:

```text
partition_structured_output_rejected
operation_id=<partition id>
validation_code=<static issue code>
structured_attempt=<0 or 1>
```

The log must not contain:

- raw cells;
- formulas or labels;
- request payloads;
- API keys or endpoint credentials;
- model-authored candidate contents.

No public error message changes. Two invalid structured results still surface
as the existing sanitized local workbook validation error.

Azure HTTP, authentication, context-limit, and transient retry behavior remain
unchanged.

## 8. Test Strategy

### 8.1 Contract tests

Deterministic parameterized tests cover:

- every source-bearing bucket rejects a missing `source_references`;
- an empty source list is rejected;
- non-object source entries are rejected;
- blank or non-string `sheet_name`/`cell` is rejected;
- canonical `financial_series` is not incorrectly required to carry
  `source_references`;
- a valid candidate result returns no issue.

### 8.2 Driver tests

Mocked Azure Responses tests prove:

1. first response missing candidate sources, second response valid:
   - exactly two calls;
   - second call uses `previous_response_id`;
   - repair prompt contains only the safe issue code/instruction;
   - corrected result is returned;
2. both responses missing candidate sources:
   - exactly two calls;
   - raises `PartitionStructuredOutputError`;
   - no third call;
3. initially valid result:
   - exactly one call;
4. logs do not expose candidate data, raw cells, or API keys.

### 8.3 Regression

Run:

```text
experiments/workbook_agent_poc/tests/test_partition_driver.py
experiments/workbook_agent_poc/tests/test_partition_reconciler.py
experiments/workbook_agent_poc/tests/test_partition_pipeline.py
tests/test_workbook_validation.py
tests/test_experimental_workbook_upload.py
```

Then run the complete workbook-agent and upload regression set defined by the
large-workbook partitioned extraction plan.

## 9. Live Acceptance

No live Azure call is part of implementation itself.

After deterministic tests pass and the user separately authorizes one billable
acceptance upload:

1. confirm the container still uses `gpt-5.4-mini`;
2. rebuild/restart only the API service;
3. upload
   `fixed_solar_project_finance_model_financial_functions.xlsx` once through
   `/api/v1/models/upload`;
4. require:
   - HTTP 200;
   - `submitted=true`;
   - all eight planned partitions completed;
   - no missing partition/range coverage;
   - non-null workbook and model version IDs;
   - materialized model version;
   - calculation preparation reaches an existing success/warning terminal
     state;
5. if the model still returns an invalid nested result twice, retain the
   failure and do not retry the full upload automatically.

## 10. Scope and Rollback

Expected implementation files:

```text
experiments/workbook_agent_poc/partition_contract.py
experiments/workbook_agent_poc/partition_driver.py
experiments/workbook_agent_poc/tests/test_partition_contract.py
experiments/workbook_agent_poc/tests/test_partition_driver.py
```

No database migration, router, API response model, calculation module, frontend
file, environment file, or Docker Compose change is required.

Rollback reverts the validator and driver correction wiring. It requires no
data migration and does not affect already failed model-version records.
