# Partition Strict Structured Output Design

**Date:** 2026-07-29
**Branch:** `feature/backend-scale-up`
**Status:** Approved for implementation planning

## Problem

The live GPT-5.4 mini upload of
`fixed_solar_project_finance_model_financial_functions.xlsx` completed three
partitions and then failed on `Debt Sculpting!A1:AB10`.

Azure returned a parseable `submit_partition_result` function call, but its
nested `result` omitted a required bucket. The driver sent one correction
turn through `previous_response_id`; the second response omitted a required
bucket again. The pipeline terminated with
`partition_structured_output_invalid`, surfaced by the API as
`WORKBOOK_VALIDATION_ERROR`.

The two calls were not identical:

- both used the same partition system instructions, function tool, forced
  `tool_choice`, and partition response chain;
- the second call added a rejected `function_call_output` containing the
  validation code and repair instruction;
- neither call used strict structured-output enforcement.

Repeating a non-strict request does not guarantee schema compliance. A stronger
prompt can improve model behavior, but deterministic field completeness
requires strict function calling.

## Goal

Make every Azure partition extraction response conform to a closed,
partition-specific schema on its first structured generation, while preserving
the existing rule that a missing or invalid candidate source rejects only that
candidate and does not fail the workbook.

## Scope

The implementation is limited to the partition Azure contract and driver:

- `experiments/workbook_agent_poc/partition_contract.py`;
- `experiments/workbook_agent_poc/partition_driver.py`;
- their focused contract, driver, pipeline, API-adapter, and lifecycle tests.

The implementation does not change:

- the shared legacy `SUBMIT_RESULT_SCHEMA`;
- workbook indexing or partition planning;
- reconciliation business roles or canonicalization rules;
- the candidate validator's accepted/rejected semantics;
- database tables or migrations;
- API response schemas;
- frontend behavior;
- the calculation engine;
- environment files or Docker configuration.

## Options Considered

### A. Partition-only strict schema and stronger prompt

Create a closed schema used only by `submit_partition_result`, enable
`strict: true`, and strengthen the partition system prompt with an exact output
contract and pre-submission checklist.

This is the selected design. It provides Azure-side schema enforcement while
keeping the legacy workbook-agent contract unchanged.

### B. Make the shared extraction schema strict

This would reduce schema duplication but would also change the legacy
non-partition agent and its fixtures, prompts, and downstream expectations. The
larger regression boundary is unnecessary for the observed failure.

### C. Prompt only, followed by backend bucket completion

This would be smaller, but it would remain probabilistic at the Azure boundary.
Automatically converting an omitted bucket to `[]` could also hide a genuine
model omission on a partition that contains relevant candidates.

## Architecture

The partition flow becomes:

```text
Bound partition evidence
        |
        v
Strict partition system prompt
        |
        v
submit_partition_result(strict=true)
        |
        v
Azure schema-conforming function arguments
        |
        v
Existing binding and reconciliation
        |
        +-- invalid source -> candidate rejected
        |
        `-- other binding or semantic structure error -> terminal
```

The prompt, strict schema, and backend validation have separate
responsibilities:

- the prompt governs semantic classification, evidence discipline, and
  anti-fabrication rules;
- the strict schema guarantees field presence, types, and closed objects;
- backend binding proves that partition identity and source references match
  authoritative workbook evidence;
- the validator preserves the existing per-candidate acceptance and rejection
  behavior.

There is no fallback from strict mode to non-strict mode.

## Partition Tool Schema

### Function envelope

`submit_partition_result` is marked `strict: true`.

Its arguments object has `additionalProperties: false` and requires exactly:

- `workbook_version`;
- `partition_id`;
- `sheet_name`;
- `primary_range`;
- `result`.

These identity fields must match the bound partition envelope. Existing backend
binding remains authoritative.

### Result buckets

The strict `result` object has `additionalProperties: false`. It requires all
of the following list fields on every response:

1. `metadata`;
2. `all_assumption_candidates`;
3. `parameter_candidates`;
4. `derived_value_candidates`;
5. `output_candidates`;
6. `financial_series_candidates`;
7. `financial_series`;
8. `scenario_structures`;
9. `sensitivity_structures`;
10. `unclassified_inputs`;
11. `review_candidates`.

An empty bucket is represented as `[]`; it is never omitted.

`coverage_declaration` is excluded from the partition schema. Workbook-wide
coverage is backend-owned and is generated only after all planned partitions
complete.

### Candidate objects

The partition schema preserves the complete current candidate field set. It
does not remove `unit`, `period`, `scenario`, `category`, canonical naming,
confidence, reasoning, or evidence fields to reduce tokens.

The generic candidate definition contains exactly:

- `candidate_id: string`;
- `original_label: string`;
- `submitted_role: ROLE_ENUM`;
- `business_role: BUSINESS_OUTPUT_ROLE_ENUM | null`;
- `raw_value: string | number | boolean | null`;
- `displayed_value: string | number | null`;
- `unit: string | null`;
- `period: string | number | null`;
- `scenario: string | null`;
- `source_references: source_reference[] | null`;
- `formula_status: string | null`;
- `reasoning_summary: string | null`;
- `llm_confidence: number | null`;
- `category: string | null`;
- `canonical_name: string | null`;
- `evidence: string[]`.

The output-candidate definition has the same properties, except
`business_role` is a non-null `BUSINESS_OUTPUT_ROLE_ENUM`.

Because strict structured output requires every declared property to be
required, fields that are logically optional use nullable scalar types or an
empty list. In particular:

- `raw_value` is `string | number | boolean | null`;
- nullable scalar metadata uses its existing scalar type plus `null`;
- `evidence` uses an array and may be empty;
- `source_references` uses `array | null` and may be empty.

Every nested object sets `additionalProperties: false`. Source-reference
objects contain exactly `sheet_name` and `cell`, both required strings.

The current `minItems` constraint is not used in the strict schema because it
is outside Azure's supported strict JSON Schema subset. Source non-emptiness
and workbook existence remain backend validation responsibilities.

### Source-rejection compatibility

Strict field presence does not turn a source defect into a workbook failure:

- a candidate with `source_references: null` is source-rejected;
- a candidate with `source_references: []` is source-rejected;
- malformed or nonexistent source references are source-rejected;
- the reconciler moves the affected item to `review_candidates`;
- deterministic validation marks the affected item `rejected`;
- other candidates and partitions continue;
- canonical persistence excludes the rejected candidate.

The model is instructed to use `[]` and `review_candidates` when it cannot cite
exact supplied evidence. It must never invent a reference to satisfy the
schema.

### Scenario, sensitivity, and financial-series objects

The current open-ended structure objects are replaced in the partition-only
schema with the following closed definitions.

A scenario structure contains exactly:

- `structure_id: string | null`;
- `concept: string | null`;
- `scenarios: string[]`;
- `cells: string[]`;
- `source_references: source_reference[] | null`;
- `reasoning_summary: string | null`;
- `llm_confidence: number | null`.

A sensitivity structure contains exactly:

- `structure_id: string | null`;
- `label: string | null`;
- `row_driver: string | null`;
- `column_driver: string | null`;
- `row_values: (string | number)[]`;
- `column_values: (string | number)[]`;
- `matrix_range: string | null`;
- `source_references: source_reference[] | null`;
- `reasoning_summary: string | null`;
- `llm_confidence: number | null`.

A canonical financial-series descriptor contains exactly:

- `series_id: string`;
- `label: string`;
- `semantic_role: "financial_series"`;
- `business_role: BUSINESS_OUTPUT_ROLE_ENUM`;
- `category: string | null`;
- `unit: string | null`;
- `frequency: string | null`;
- `scenario: string | null`;
- `entity: string | null`;
- `currency: string | null`;
- `sheet_name: string | null`;
- `period_range: string`;
- `value_range: string`;
- `label_reference: string | null`;
- `reasoning_summary: string | null`;
- `llm_confidence: number | null`.

Every property in these definitions is required. Optional values are nullable,
and optional collections are present as empty lists.

The schema retains the current scenario, sensitivity, and financial-series
information; it does not flatten these structures into ordinary candidates or
materialized point arrays. Existing backend range validation and series
materialization remain unchanged.

The schema defines source reference, generic candidate, output candidate,
scenario structure, sensitivity structure, and financial-series descriptor once
under `$defs`; result buckets use `$ref` rather than duplicating these object
definitions. This keeps the total property count and nesting depth bounded and
makes conformance checks deterministic.

### Static conformance

Focused tests recursively verify that the partition schema:

- marks the function `strict: true`;
- sets `additionalProperties: false` on every object;
- makes each object's `required` set equal its `properties` set;
- contains none of the unsupported keywords used by the previous schema,
  including `minItems`;
- stays within Azure's supported property-count and nesting-depth limits;
- retains all eleven required result buckets;
- remains isolated from the shared legacy extraction schema.

## System Prompt

The existing evidence, classification, and anti-injection instructions remain.
The output section is replaced with an explicit mandatory contract equivalent
to:

```text
MANDATORY OUTPUT CONTRACT

Return exactly one submit_partition_result function call.
Do not return prose, markdown, analysis text, or another tool call.

The result object MUST contain exactly these eleven list fields:
metadata
all_assumption_candidates
parameter_candidates
derived_value_candidates
output_candidates
financial_series_candidates
financial_series
scenario_structures
sensitivity_structures
unclassified_inputs
review_candidates

Every field above is mandatory.
If a bucket has no candidates, return [].
Never omit a bucket to save output tokens.
Do not return coverage_declaration or a workbook-wide completion claim.

Every candidate must contain every field required by the tool schema.
Use null for an unavailable nullable scalar.
Use [] for an unavailable list.
Never invent a value, label, role, source reference, range, or formula.

For source_references:
- Cite only exact sheet/cell or range evidence supplied in this partition.
- If exact evidence is unavailable, use [] and place the item in
  review_candidates.
- Never fabricate a reference merely to satisfy the schema.

Before calling submit_partition_result, verify:
- all eleven result buckets exist;
- every bucket is a list;
- all object fields required by the schema exist;
- every cited source exists in supplied evidence;
- workbook_version, partition_id, sheet_name, and primary_range exactly
  match the supplied partition envelope.
```

The prompt does not attempt to replace schema enforcement. It explains the
business meaning of empty and unavailable values and prevents strict field
requirements from encouraging fabricated evidence.

## Azure Call Policy

Each partition receives one structured-output generation attempt.

The current second structured correction turn is removed. Strict mode is the
enforcement mechanism for field completeness; repeating the same semantic task
is not.

Existing limited transport retries remain for:

- HTTP 429;
- HTTP 5xx;
- transient connection failures.

These retries repeat a failed transport, not a completed model response.

The following completed-response failures are terminal and are not sent back to
the model:

- Azure rejects the strict schema;
- the response is incomplete because the output-token budget was exhausted;
- the response is refused or content-filtered;
- the response contains no forced function call;
- the response contains an unexpected or unparseable function call;
- a mocked or nonconforming response still omits a required bucket.

Context-length rejection continues through the existing bounded partition-split
path. There is no automatic non-strict fallback.

`max_calls_per_operation` accounts for one structured attempt multiplied only
by the existing transport retry budget.

Conflict reconciliation remains a separate bounded operation and is not
silently counted as an extraction correction call.

## Error Classification and Safe Diagnostics

Logs identify the failing boundary without logging workbook content:

- deployment;
- partition ID;
- sheet name and primary range;
- Azure request ID;
- response status;
- incomplete reason, when available;
- contract validation code and field path;
- cumulative Azure call count.

For example:

```text
partition_bucket_missing:result.output_candidates
```

Logs do not include:

- workbook cell values;
- complete candidates;
- serialized partition evidence;
- system or repair prompts;
- full Azure responses;
- API keys or other secrets.

Strict-schema rejection, incomplete output, refusal, missing function call, and
binding failures remain distinguishable. Candidate source failures remain
bounded candidate validation outcomes rather than terminal Azure errors.

## Output Budget

Preserving the full candidate field set increases output size because strict
mode requires every declared field to appear.

The implementation does not edit `.env`, Docker configuration, or the driver's
configured output budget. A live acceptance run is blocked unless the running
container reports:

```text
deployment=gpt-5.4-mini
max_output_tokens=66298
reasoning_effort=medium
partitioned=true
```

The preflight reads and prints only these non-secret values and whether the
Azure key is configured. It never prints the key or runs a command that expands
all Compose environment values.

## Verification

### Local schema and prompt verification

Tests prove:

- the request tool contains `strict: true`;
- the strict schema passes the recursive conformance checks;
- the system prompt names all eleven buckets;
- the prompt requires `[]` for empty buckets;
- the prompt forbids bucket omission and fabricated sources;
- the shared legacy schema remains unchanged.

### Driver behavior

Mocked Responses tests prove:

- a valid strict function call is accepted in one Azure call;
- an omitted bucket produces a terminal structured-output error after one call;
- there is no `previous_response_id` correction turn;
- a strict-schema 400 is not downgraded to non-strict;
- incomplete output is classified and not retried as a model correction;
- 429, 5xx, and transient connection retries retain their current bounds;
- request IDs and safe failure metadata are retained.

### Workbook behavior

Pipeline, API-adapter, and lifecycle tests prove:

- a `null` or empty source rejects only the affected candidate;
- the workbook still returns `submitted=true`;
- the rejected item remains available for review and audit;
- the rejected item does not create canonical parameters or outputs;
- binding, series-range, and other non-source structural errors remain terminal;
- no database, frontend, or calculation contract changes.

### Real Azure acceptance

A billable Azure upload requires fresh explicit authorization after all local
tests pass and the effective container configuration passes the output-budget
preflight.

The Solar workbook is uploaded exactly once with no automatic upload retry.
Acceptance requires:

- HTTP 200;
- `submitted=true`;
- `stop_reason=submitted`;
- all eight planned partitions complete;
- no `partition_bucket_missing`;
- no structured correction call;
- source defects, if any, appear only as rejected candidates;
- no `AZURE_RESPONSES_ERROR`;
- no `WORKBOOK_VALIDATION_ERROR`.

Transport-level retries inside the one upload remain limited to the existing
driver policy and are reported separately from logical partition calls.

## External Constraint Reference

This design follows the Microsoft Foundry structured-output requirements:

- strict function calling uses `strict: true`;
- parallel tool calls are disabled;
- every object is closed with `additionalProperties: false`;
- all declared properties are required, with nullable types representing
  optional values;
- only the documented JSON Schema subset is used.

Reference:
<https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs>
