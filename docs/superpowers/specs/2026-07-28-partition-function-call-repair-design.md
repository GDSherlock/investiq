# Partition Function-Call Repair Design

## Problem

The partition driver now rejects a `submit_partition_result` whose nested
candidates omit `source_references`. The first real Azure response therefore
reaches the intended local validator and produces
`candidate_source_missing`.

The correction request is currently invalid under the Responses API function
calling protocol. The first response contains a pending function call, but the
driver continues it with `previous_response_id` and an ordinary user message.
Azure requires a `function_call_output` tied to the pending call's `call_id`
before that response can be continued. Azure consequently rejects the
correction request with HTTP 400, which the upload endpoint exposes as
`AZURE_RESPONSES_ERROR`.

## Goal

Make the existing single correction attempt protocol-correct when a returned
partition function call fails local nested validation, without changing
partitioning, extraction semantics, persistence, frontend behavior, or runtime
budgets.

## Non-Goals

- Do not enable or redesign strict structured outputs.
- Do not change the partition or extraction schemas.
- Do not infer, repair, or backfill source references locally.
- Do not resend or summarize workbook evidence.
- Do not change database tables, migrations, calculation services, frontend
  code, Docker configuration, environment files, deployment settings, retry
  counts, call limits, token limits, byte limits, or deadlines.
- Do not add a third structured-output attempt.

## Chosen Design

`AzurePartitionDriver` will retain enough metadata from an expected function
call to distinguish two correction paths:

1. If exactly one expected function call is present but its arguments fail
   JSON parsing, top-level validation, or
   `validate_partition_tool_arguments`, the driver will retain the response ID
   and the function call's non-empty `call_id`.
2. The second request will set `previous_response_id` to the first response ID.
3. Its input will be one `function_call_output` item for that `call_id`.
4. The output string will contain only a static backend rejection envelope:

```json
{
  "accepted": false,
  "validation_code": "candidate_source_missing",
  "repair_instruction": "..."
}
```

The repair instruction will come from the existing `PartitionResultIssue`.
It will not contain candidate values, labels, workbook contents, API keys, or
other raw model output. Existing instructions, tools, forced tool choice,
parallel-call setting, token budget, and reasoning effort will be sent
unchanged.

The driver will not add an ordinary user message to this correction request.
The `function_call_output` closes the pending function call and communicates
the backend validation rejection in the protocol-defined form. Because the
first response remains linked through `previous_response_id`, Azure retains
the original partition context without a duplicate workbook payload or an
intermediate summary.

## Parsing Boundary

The private tool-result parser will return both:

- parsed function arguments; and
- the expected function call's `call_id`.

This is a private driver implementation detail. No public protocol,
partition-driver interface, pipeline return value, or persisted contract will
change.

Response inspection will first identify whether exactly one function call with
the expected name exists and capture its `call_id`. Argument parsing and
top-level required-field validation remain separate checks. This allows a
malformed but protocol-valid function call to be acknowledged with a static
validation rejection instead of being continued as an ordinary user turn.

A function call that lacks a non-empty string `call_id` cannot be acknowledged
safely. The driver will raise `PartitionStructuredOutputError` locally instead
of issuing a correction request that Azure must reject.

## Existing Generic Correction

The existing generic correction path for a response with no function-call
items will remain unchanged: it may continue the response with the current
static user instruction because there is no pending function call to
acknowledge.

A response containing an unexpected function name or multiple function calls
will fail locally as invalid structured output. The driver will not continue a
response whose pending calls it cannot acknowledge unambiguously.

## Error and Call-Budget Behavior

- A valid first result returns immediately with one Azure call.
- A source-less first result receives exactly one protocol-correct correction
  call.
- A valid corrected result returns normally.
- A second invalid result raises the existing
  `PartitionStructuredOutputError`.
- A missing `call_id` fails locally without a second Azure call.
- HTTP retry behavior remains unchanged and separate from the maximum of two
  structured-output attempts.
- Logs continue to contain static operation IDs, validation codes, attempts,
  HTTP status, Azure request IDs, and retry counters only.

## Test Design

Driver tests will use an Azure-protocol-aware fake:

1. Return a `submit_partition_result` function call whose candidate lacks
   `source_references`.
2. Reject a continuation that uses an ordinary user message without resolving
   the pending function call. This makes the current implementation fail for
   the same reason as Azure.
3. Accept a second request only when it contains:
   - the first response ID as `previous_response_id`;
   - exactly one `function_call_output`;
   - the original non-empty `call_id`;
   - the static validation code and repair instruction; and
   - no raw candidate content.
4. Return a corrected result with a valid source reference and assert success.

Additional focused tests will prove:

- a second source-less result raises without a third call;
- a missing `call_id` raises locally without a second call;
- the existing no-function-call correction path still uses its current static
  user instruction;
- correction inputs and logs do not include sentinel candidate or secret
  values.

Related partition contract, reconciler, pipeline, workbook upload, persistence,
and calculation tests will be rerun. The full repository suite will also be
run, while preserving and reporting unrelated user-owned frontend baseline
changes separately.

## Real Azure Acceptance Gate

No live request is part of deterministic implementation verification. After
the local tests and commit are complete, one upload of
`fixed_solar_project_finance_model_financial_functions.xlsx` against the
configured `gpt-5.4-mini` deployment may be run only after a fresh explicit
authorization.

The live acceptance succeeds only if:

- the correction request is not rejected with HTTP 400;
- no `AZURE_RESPONSES_ERROR` occurs;
- all planned partitions complete;
- reconciliation and submission complete; and
- the model version reaches the expected successful persisted state.

If the upload fails for a different reason, it will not be retried
automatically. Logs, Azure request IDs, and persisted state will be inspected
before proposing any further change.
