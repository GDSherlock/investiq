# Best-Match Semantic Recovery Design

**Date:** 2026-08-03

**Status:** Approved for implementation planning

## Goal

Populate Overview KPIs and charts from the best structurally valid workbook candidate when extraction produces multiple or imperfectly classified candidates. Ambiguity must no longer make a role unavailable when at least one source-valid candidate exists.

## Scope

This design repairs the remaining semantic-selection gap after the existing `period_range` recovery and financial-series `business_role` preservation work.

It covers:

- scalar Overview outputs such as project IRR, equity IRR, NPV, and minimum DSCR;
- financial-series roles used by Overview, including revenue, EBITDA, CFADS, and DSCR;
- deterministic ranking of multiple candidates;
- automatic `binding_source="extracted"` semantic bindings;
- binding-aware Overview resolution;
- auditable selection evidence and alternatives.

It does not change:

- workbook chunking or full-context observation;
- the extraction prompt, Azure call budget, or reconciliation-call budget;
- invalid-range or invalid-source quarantine;
- calculation-engine semantics;
- frontend chart construction or fallback data;
- database schema or migrations;
- existing materialized model versions;
- historical records through backfill or in-place repair.

## Design Principles

1. Ambiguity is a ranking problem, not a failure condition.
2. Structural invalidity remains a hard rejection condition.
3. The same workbook snapshot must always produce the same selection.
4. All alternatives remain persisted or retained in the extraction snapshot for provenance.
5. A reviewed binding always overrides an extracted binding.
6. No cached, guessed, or fabricated KPI/chart values are introduced.

## Minimal Architecture

The implementation adds one focused semantic-selection unit and wires it into two existing boundaries:

1. `ModelExtractionPersistenceService` runs selection after canonical row materialization has produced candidate row payloads but before the canonical transaction commits.
2. `AnalysisPresentationService` resolves a requested semantic role by persisted binding UUID first, then uses the current strict role resolver only when no binding exists.

The existing `model_semantic_bindings` table is reused. No schema change is required.

### New focused unit

Add a small backend module responsible only for:

- building normalized candidate records;
- excluding structurally invalid records;
- assigning deterministic evidence scores;
- selecting one record per semantic role;
- emitting persistence rows and JSON-safe audit evidence.

It must not query Azure, execute formulas, mutate workbook content, or contain frontend presentation logic.

## Candidate Sources

### Scalar candidates

The scalar pool includes candidates from:

- `output_candidates`;
- `derived_value_candidates`;
- source-valid `review_candidates` whose validation result is not rejected.

A derived or review candidate may become a canonical output only when:

- its source cell exists in the stored workbook;
- its source validation is accepted;
- its business role is registered;
- its source is a scalar cell rather than a range;
- its formula/value metadata can be reloaded from the workbook.

Bucket disagreement is retained in audit evidence but does not exclude the candidate.

### Series candidates

The series pool uses the canonical financial-series rows already produced by backend-owned range materialization. Points remain workbook-owned and are never reconstructed by the selector.

Multiple series with the same role remain separate canonical entities. Selection is represented by a semantic binding rather than by deleting or merging source data.

## Structural Exclusions

Only the following conditions make a candidate ineligible:

- missing or invalid workbook source;
- invalid or misaligned period/value range;
- source from another workbook or model version;
- rejected source validation;
- unregistered business role;
- non-scalar source offered as a scalar output;
- canonical entity ID that does not belong to the current model version.

Low confidence, bucket disagreement, duplicate roles, label variation, or a small score margin must not make the role unavailable.

## Deterministic Scoring

Each candidate receives an integer score and an ordered list of reasons.

| Evidence | Score |
|---|---:|
| Exact business-role match | +100 |
| Registered compatible-role conversion | +70 |
| Correct entity kind for the semantic role | +35 |
| Exact normalized canonical label/alias | +30 |
| Formula semantics match the requested role | +25 |
| Workbook formula has a valid cached value and traceable formula status | +25 |
| Source and role validation are accepted | +20 |
| Unit, scenario, frequency, and axis are compatible | +15 |
| Candidate is an explicit summary/display output | +15 |
| Terminal scalar with no downstream dependents | +10 |
| Candidate is a pure direct-reference alias of another candidate | -15 |
| Candidate originated in `review_candidates` | -5 |
| Formula is unsupported or blocked | -30 |
| Entity kind conflicts with the requested role | -80 |

The selector does not apply a minimum score or minimum winning margin. If at least one structurally valid candidate exists, it selects the highest-ranked candidate.

### Stable tie-breaking

Equal scores are resolved in this order:

1. valid cached workbook value with traceable formula status;
2. stronger source-validation state;
3. non-alias source;
4. workbook sheet position;
5. normalized A1 source address;
6. deterministic canonical entity ID.

The tie-break result is recorded in audit evidence.

## Role Compatibility

Compatibility is an explicit code-owned map, not fuzzy similarity.

The first required compatibility rule is:

- requested semantic role `dscr` may select a financial series whose extracted business role is `minimum_dscr` when its normalized label is exactly `dscr` and it contains multiple aligned period points.

The selector records this as `compatible_role:minimum_dscr->dscr`. The stored financial-series business role is not rewritten.

No other cross-role conversion is introduced without a separate test-backed rule.

## Extracted Bindings

For every supported semantic role with an eligible candidate, selection produces one `ModelSemanticBinding` row:

- `binding_source="extracted"`;
- exactly one of `canonical_output_id`, `financial_series_id`, or `model_parameter_id` populated;
- `evidence_json` containing score, reasons, alternatives, source, score margin, quality, and tie-break details.

Selection quality is informational:

- `high`: exact role and exact entity-kind match with a clear lead;
- `medium`: exact role with a narrow lead or one non-critical penalty;
- `low`: compatible-role conversion, exact tie, or selection from review candidates.

All qualities remain usable by Overview. Low quality adds a warning but does not block display.

If a reviewed binding already exists, automatic selection must not overwrite it. New uploads create new model versions, so this rule mainly protects future persistence retries and reviewed workflows.

## Scalar Promotion

When the selected scalar comes from a validated derived/review bucket and is not already in `canonical_outputs`, the persistence service creates one canonical-output row from the workbook-reloaded source fact and its validation result.

The promoted row must:

- use the deterministic output ID already derived from model version and source cell;
- retain the submitted bucket and conflict status in warnings/evidence;
- retain the registered business role;
- use the workbook's exact formula, cached value, type, format, sheet, and cell;
- pass the same source/role validation requirements as ordinary canonical outputs.

Non-selected derived/review candidates are not promoted.

## Bound Resolution

Overview resolution becomes:

1. load the model's binding for the requested semantic role;
2. find the projected calculation output whose `output_id` equals the bound canonical entity ID;
3. verify the projected entity kind matches the binding;
4. return the bound projection even when another projection has the same business role;
5. if no binding exists, use the current strict `resolve_analysis_output` behavior unchanged.

A dangling or cross-model binding is treated as a persistence/integrity error, not silently replaced with a different candidate.

The frontend remains unchanged because the Overview API contract remains unchanged.

## Balanced-Case Expected Selections

For `01_balanced_case.xlsx`, the deterministic selector is expected to choose:

- `Investor Returns!B8` for `project_irr`;
- `Investor Returns!B9` for `equity_irr`;
- `Investor Returns!B7` for `minimum_dscr`;
- the original Solar Operations series rather than its pointwise Cash Flow alias for `revenue`;
- the original Solar Operations series rather than its pointwise Cash Flow alias for `ebitda`;
- `Cash Flow!B15:AB15` for semantic role `dscr` through the explicit compatible-role rule;
- the existing unique CFADS series for `cfads`.

The Financial Functions IRR candidates and Cash Flow Revenue/EBITDA aliases remain available as audited alternatives.

## Transaction and Failure Behavior

Canonical parameters, promoted outputs, canonical series, series values, and extracted bindings are persisted in the existing canonical transaction.

If semantic selection or binding persistence raises an integrity error:

- the canonical transaction rolls back;
- the model follows the existing `persistence_failed` path;
- no partially materialized model or binding remains;
- a persistence retry reuses the stored extraction snapshot and workbook bytes.

Ambiguity, low margin, or a stable tie does not raise an error.

## Testing Strategy

Implementation must use strict RED to GREEN.

### Unit tests

- exact-role scalar ranking;
- scalar promotion from validated derived and review candidates;
- rejection of invalid or rejected sources;
- deterministic ties;
- direct-reference alias penalty;
- compatible `minimum_dscr` series to `dscr` binding;
- quality and complete alternative audit evidence;
- reviewed binding precedence.

### Persistence tests

- canonical outputs and extracted bindings commit atomically;
- rollback leaves no canonical rows or bindings;
- promoted source facts retain exact workbook provenance;
- no schema migration is needed;
- persistence retry remains deterministic.

### Presentation tests

- bound output wins over duplicate same-role projections;
- bound series wins over duplicate Revenue/EBITDA projections;
- DSCR binding resolves a series whose stored role is `minimum_dscr`;
- no-binding behavior remains strict and backward compatible;
- dangling/cross-model bindings produce a typed integrity failure.

### Balanced-case offline acceptance

Using the supplied workbook without Azure calls, prove the expected score ordering and selected sources from a stored extraction snapshot fixture.

### Forward-only live acceptance

After focused and full local verification, container provenance verification, and fresh user approval:

1. upload `01_balanced_case.xlsx` exactly once as a new model version;
2. do not retry the upload;
3. prepare calculation and submit one baseline with a fixed calculation idempotency key;
4. verify the selected binding UUIDs and evidence in PostgreSQL;
5. verify Outputs and Overview API roles and source IDs;
6. visually confirm Project IRR, Minimum DSCR, Operating trajectory, Debt coverage, and Project cash generation;
7. leave unsupported or genuinely absent roles as `Unavailable`.

## Acceptance Criteria

- Multiple structurally valid candidates always produce one deterministic extracted binding.
- Ambiguity alone never causes an Overview role to be unavailable.
- Structurally invalid sources remain quarantined and cannot be selected.
- Project IRR, Minimum DSCR, Revenue, EBITDA, CFADS, and DSCR resolve from real persisted calculation outputs for the balanced-case workbook.
- No frontend production code, migration, extraction prompt, Azure budget, chunking, or calculation-engine change is required.
- Existing materialized model versions are unchanged.
- The final real workbook acceptance uses one newly uploaded model version after explicit approval.
