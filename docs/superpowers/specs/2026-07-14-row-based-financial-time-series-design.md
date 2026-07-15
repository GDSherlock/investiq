# Row-Based Financial Time-Series Extraction Design

## Scope and invariants

Add complete financial time-series objects to the existing full-context workbook-agent experiment without changing workbook coverage, observation chunking, opaque continuation tokens, submission gating, workbook-version binding, persistence, endpoint paths, frontend behavior, or unrelated candidate routing. Scenario tables and sensitivity matrices remain dedicated structures.

## Compatibility decision

Keep `financial_series_candidates` as the legacy point-candidate bucket and add a canonical `financial_series` bucket. Existing raw extraction payloads and point-candidate validation remain available for debugging. Canonical series get their own deterministic validator and summary; old consumers that only read existing buckets continue to work.

## Canonical contract

Each canonical series contains `series_id`, `label`, `semantic_role=financial_series`, `category`, `unit`, `frequency`, `period_axis`, `value_axis`, `calculation_type`, `formula_pattern`, `source_references`, `reasoning_summary`, and `llm_confidence`. Period and value axes contain a contiguous A1 range and aligned arrays. Missing workbook cells are explicit `null`; values and periods are never inferred or interpolated.

The prompt and submit schema explicitly require a full contiguous period/value axis and forbid representative-cell submissions as canonical series. Horizontal rows are required; compatible vertical columns are supported by the validator. The model must leave scenarios and two-way sensitivity matrices in their existing structures.

## Deterministic validation

The series validator parses and verifies both ranges, confirms one-dimensional compatible orientation and equal length, reads every referenced cell from the already-loaded workbook, compares the submitted axes positionally, and rejects fabricated, shifted, shortened, or representative-cell-only series. It reports duplicate and blank period warnings without dropping positions.

Semantic role and calculation type are independent. A formula row remains `financial_series`; formula/static/blank counts determine `formula`, `hardcoded`, `mixed`, `blank`, or `unknown`. Formula metadata preserves formula text, cached value availability, and unknown cache freshness. Formula consistency uses OpenPyXL's relative-reference translator to normalize copied formulas when safe; unsupported normalization returns `null`.

Exact duplicate source ranges are deterministically retained once and subsequent duplicates are flagged. Different source ranges are not merged merely because labels match, preserving scenario/entity/currency/unit distinctions.

## Reporting and API flow

`validate_extraction` returns legacy candidate results plus canonical series results. The API retains the original `final_extraction` and adds `time_series_summary` derived from canonical validation results. Runtime/token/tool-call metrics continue to come from the existing loop and driver telemetry.

## Tests

Tests cover complete horizontal series, formula series, mixed formula/static/blank rows, representative-cell rejection, period/value misalignment, source mismatch, scenario and sensitivity separation, duplicate ranges, prompt/tool contract, API summary, and the current `Financial_Model_Data.xlsx` coverage/submission regression with deterministic local drivers only.
