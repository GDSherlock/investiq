# Backend-Owned Canonical Financial Series Design

## Decision

The LLM submits semantic descriptors and workbook-qualified source ranges. A dedicated
`FinancialSeriesMaterializer` reads the already-loaded workbook and becomes the sole source of
truth for canonical period points, value points, formula telemetry, calculation type, statuses,
and duplicate handling.

This design replaces the current validator-shaped implementation, which trusts LLM-authored
`periods[]` and `values[]` enough to reject a series when those arrays disagree. Canonical output
will instead ignore those arrays as authoritative data and use them only for legacy disagreement
telemetry.

## Considered Approaches

1. **Backend-owned materializer in `time_series.py` (selected).** The extraction contract emits
   compact descriptors, while one deterministic component validates ranges and builds canonical
   series. This gives future consumers one stable output and reduces model payload size without
   changing agent calls or workbook coverage.
2. **Keep LLM-authored arrays and repair them in validation.** This would preserve the current
   schema but retain the oversized payload and ambiguous source-of-truth problem.
3. **Materialize in the API adapter.** This would couple workbook semantics to the transport layer
   and leave non-API PoC callers without canonical output.

## Component Boundary

`experiments/workbook_agent_poc/time_series.py` owns:

- descriptor parsing and legacy normalization;
- workbook-qualified and explicit-sheet range parsing;
- one-dimensional range geometry and alignment validation;
- deterministic period and value point materialization;
- safe period normalization;
- formula/static/blank counts and copied-formula consistency;
- series-level status, warnings, and structured failures;
- evidence-based deduplication and alias preservation;
- conversion of canonical series to chart-ready points.

It consumes a single `WorkbookToolset` instance and uses its already-loaded formula and cached-value
workbooks. It does not call the LLM and does not issue model-visible `read_range` calls.

## Data Flow

1. `validate_extraction()` collects descriptors from `financial_series`.
2. It detects compatible legacy complete-series objects in `financial_series_candidates` and
   normalizes their period/value source ranges into descriptors.
3. Scenario and sensitivity buckets are never inspected as financial-series inputs.
4. `FinancialSeriesMaterializer.materialize_collection()` builds canonical objects and structured
   rejected results.
5. Valid canonical objects replace/add `final_extraction.financial_series`; raw legacy buckets remain
   untouched for debugging.
6. Validation results and `time_series_summary` are derived from the same materialization outcome so
   compatible legacy series cannot produce a zero summary.

## Descriptor Contract

Required fields are `series_id`, `label`, `semantic_role`, `category`, `unit`, `frequency`,
`period_range`, and `value_range`. Optional semantic fields are `scenario`, `entity`, `currency`,
`label_reference`, `reasoning_summary`, `llm_confidence`, and explicit `sheet_name` for unqualified
ranges.

Legacy objects with `period_axis.source_range` and `value_axis.source_range` are accepted. Their
LLM-authored arrays and formula metadata never override workbook-derived data.

## Canonical Output

Each materialized series contains the submitted semantic fields plus `orientation`, `period_axis`
period objects, `value_axis` value objects, backend-derived `calculation_type`, backend-derived
`formula_pattern`, `materialization_status`, `validation_status`, warnings, aliases, and source
references. Every point includes its zero-based index and qualified source cell.

Period normalization is deliberately partial: raw/display labels are always preserved; year,
quarter, month, period type, and forecast state are populated only when safely identifiable.
Unrecognized labels generate a warning rather than rejection.

Formula cached values are read from the cached-value workbook. Formula text comes from the formula
workbook. Freshness is always `unknown` unless deterministic repository evidence becomes available.

## Errors and Warnings

Descriptor/range failures become structured series results with stable error codes; they do not
raise raw `KeyError` or `IndexError`. Safe telemetry is limited to identifiers and ranges.

Warnings do not reject usable series. Mixed formula/static rows, partial blanks, unrecognized
periods, cached-value freshness uncertainty, duplicate labels with different evidence, and legacy
array disagreements are warnings.

## Duplicate Policy

Exact period/value ranges with the same scenario, entity, unit, and currency produce one canonical
series. Differing labels are retained as aliases. Same labels with different evidence remain separate
and receive `DUPLICATE_LABEL_DIFFERENT_RANGE`; scenario, entity, unit, and currency boundaries prevent
merging. Detailed schedules are preferred over dashboard/cover/summary sheets only when duplicate
evidence is otherwise equivalent.

## Protected Semantics

Coverage, observation chunking, opaque continuation tokens, workbook-version binding, submission
gating, API paths, persistence, frontend behavior, and model tool-call count remain unchanged.
Scenario and sensitivity structures remain separate.

## Verification Strategy

Strict RED-to-GREEN tests cover descriptor-only materialization, legacy disagreement, formula/static/
blank telemetry, zeros, period normalization, vertical axes, geometry errors, representative-cell
misuse, deduplication, scenario/sensitivity separation, chart points, API write-back and summary, and
the deterministic `Financial_Model_Data.xlsx` acceptance flow. No live Azure request is permitted.
