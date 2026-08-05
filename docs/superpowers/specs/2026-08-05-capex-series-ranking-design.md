# Capex Series Ranking Design

**Date:** 2026-08-05

**Status:** Approved for written-spec review

## Goal

Populate the Cash Flow page's `Capex construction profile` chart from the
best-ranked persisted Capex financial series. Candidate selection must reuse
the existing deterministic semantic-binding ranking mechanism; it must not use
an exact label as a hard mapping rule.

## Current Behavior and Root Cause

The frontend already renders the fixed `capex_construction_profile` slot from
the Cash Flow analysis API. The backend currently requests semantic role
`capex` for that slot.

For the latest persisted model, the workbook contains 35 materialized financial
series. The relevant candidates were extracted with business role
`total_capex`, including:

- `Base EPC spend ($mm)`;
- `Capex ($mm)`;
- `Contingency ($mm)`;
- `Cumulative capex ($mm)`; and
- `Total capex ($mm)`.

No `capex` semantic binding exists for that model. Because presentation
resolution currently accepts only an exact `capex` business role when no
binding exists, the Cash Flow API returns the Capex chart as `unavailable` with
an empty `series` array even though `Capex ($mm)` has 27 persisted points.

## Scope

This change covers:

- ranking `capex` and compatible `total_capex` financial-series candidates;
- persisting the selected `capex` semantic binding for future model versions;
- non-mutating read-time ranking for existing model versions that have no
  `capex` binding; and
- focused regression coverage for selection evidence and Cash Flow projection.

It does not change:

- frontend page structure or chart rendering;
- extraction prompts, workbook chunking, context limits, or Azure usage;
- the stored business role of any financial series;
- workbook formulas or calculation-engine behavior;
- database schema or migrations; or
- existing database rows through backfill, update, or reprocessing.

## Selected Approach

Extend the existing `deterministic_best_match` semantic selector so requested
role `capex` considers two eligible financial-series role classes:

1. exact `business_role=capex`; and
2. compatible `business_role=total_capex`.

All structurally valid candidates in those classes enter the ranking. Labels
affect score but do not determine eligibility or act as a hard gate.

The selector continues to choose the highest-scoring candidate, records all
alternatives and score evidence, and uses the existing deterministic tie-break.
No minimum score or score margin blocks selection.

## Ranking Rules

The Capex selection reuses the existing scoring model:

| Evidence | Score |
|---|---:|
| Exact `capex` business role | +100 |
| Compatible `total_capex` business role | +70 |
| Correct financial-series entity kind | +35 |
| Exact normalized canonical label/alias | +30 |
| Workbook value/formula evidence when available | +25 |
| Accepted validation status | +20 |
| Unit available | +15 |
| Review-origin warning | -5 |
| Pure direct-reference alias | -15 |

For the current five `total_capex` candidates, `Capex ($mm)` receives the
canonical-label score while Base EPC spend, Contingency, Cumulative capex, and
Total capex remain alternatives. Formula, validation, unit, provenance, and
alias evidence continue to participate in the result.

An exact-role `capex` candidate keeps its higher role score and therefore wins
over an otherwise equivalent compatible `total_capex` candidate. A compatible
candidate may still win when its complete evidence score is higher.

Equal scores use the existing stable ordering by source and canonical entity
ID. Evidence retains `selected_score`, ordered `alternatives`, `score_margin`,
`selection_quality`, and `tie_breaker_used`.

## Shared Ranking Boundary

There must be one scoring implementation.

`build_extracted_semantic_bindings()` remains the authoritative ranking entry
point for newly materialized model versions. The Capex compatibility rule is
added to its financial-series candidate collection, not reimplemented in the
Cash Flow presentation layer.

The presentation service may call a focused pure wrapper around that same
ranking entry point when an existing model lacks a `capex` binding. The wrapper
accepts persisted financial-series rows and point evidence, returns the ranked
binding payload for one semantic role, and performs no database writes.

## Resolution Order

`AnalysisPresentationService` resolves the Capex chart in this order:

1. use an existing reviewed semantic binding;
2. otherwise use an existing extracted semantic binding;
3. otherwise rank the model's persisted `capex` and compatible `total_capex`
   financial series with the shared selector;
4. find the selected financial-series UUID in the calculation-run projection;
5. return that projected series with semantic presentation role `capex`; and
6. remain `Unavailable` if no structurally eligible selected series exists or
   the selected series is absent from the matching run projection.

The read-time fallback does not insert or update `model_semantic_bindings`.
This makes existing models usable without hidden mutation or controlled
backfill. Reviewed bindings remain authoritative and are never overridden by
ranking.

Other semantic roles keep their current resolution behavior. This change does
not broadly replace strict no-binding resolution for unrelated KPIs or charts.

## Data and Provenance Behavior

The chart continues to expose:

- the selected financial-series UUID in `source_ids`;
- its persisted 27-point baseline/current calculation projection;
- its workbook label and unit;
- point-level financial-series-value UUIDs; and
- the calculation run, model version, and graph version already carried by the
  Cash Flow response.

No scalar `total_capex`, cached workbook summary, synthetic value, aggregation,
or frontend fallback may substitute for the selected financial series.

## Failure Behavior

- Missing or structurally invalid series remain ineligible.
- A candidate from another model version is never considered.
- A selected series missing from the current calculation-run projection leaves
  the chart unavailable rather than selecting a different unranked output.
- Low score, low margin, or a deterministic tie remains usable and is reported
  through ranking evidence.
- A reviewed binding to a valid model-owned financial series overrides the
  extracted/read-time result.

## Testing Strategy

Implementation follows strict RED to GREEN.

### Ranking tests

- the five current `total_capex` labels are all eligible candidates and
  `Capex ($mm)` wins by evidence score;
- evidence lists the other four candidates as ordered alternatives;
- exact-role `capex` receives its higher base score;
- stronger complete evidence can change the winner without changing a strict
  label mapping;
- equal scores use the deterministic source/UUID tie-break; and
- reviewed binding precedence remains unchanged.

### Presentation tests

- an existing model with no `capex` binding resolves its ranked
  `total_capex` financial series into `capex_construction_profile`;
- the returned chart uses the selected financial-series and point source IDs;
- read-time resolution does not create a binding row;
- a reviewed binding wins over the read-time ranking result;
- a selected series absent from the run projection leaves the chart
  unavailable; and
- unrelated Cash Flow slots retain their existing behavior.

### Regression gates

- run focused semantic-binding and analysis-presentation tests;
- run the complete backend test suite;
- run the frontend tests because the Cash Flow contract is consumed there;
- run the production frontend build;
- run Python compile checks for changed backend modules; and
- run `git diff --check`.

## Acceptance Criteria

1. The latest persisted model's `capex_construction_profile` selects the
   persisted `Capex ($mm)` financial series and exposes its calculated points.
2. Selection is produced by the shared deterministic ranking mechanism, not an
   exact-label hard mapping.
3. All compatible candidates and scoring evidence remain auditable.
4. Existing model rows remain unchanged; read-time fallback is non-mutating.
5. Future model materialization persists the selected extracted `capex`
   binding using the same ranking.
6. Reviewed bindings retain precedence.
7. No frontend, extraction-prompt, schema, migration, or calculation-engine
   change is required.
