# Derived Equity Multiple Design

## Objective

Make the `Equity ×` cards in Overview and Sensitivity display a server-derived
money-on-money multiple calculated from the persisted equity cash-flow series:

```text
Equity × = sum(positive equity cash flows)
           / abs(sum(negative equity cash flows))
```

The system must calculate the metric from the exact baseline and current
calculation-run projections stored in the database. The frontend must not
reconstruct the ratio, guess missing data, or use a workbook-provided multiple.

## Current Behavior

Overview resolves its `leverage` slot from a scalar `equity_multiple`, with
`debt_to_equity_ratio` as a fallback. Sensitivity also resolves its fixed
`Equity ×` card from scalar `equity_multiple` calculation outputs. Models that
contain the underlying equity cash-flow series but no explicit multiple
therefore show `Unavailable`, while a model-provided scalar can use a different
financial definition.

The persisted calculation-run projection already exposes the canonical
`equity_cash_flow` series with separate baseline and current values for every
period. That run-scoped projection is the authoritative input for this metric.

## Selected Approach

Add an explicit `derived_kpis` collection to the calculation-run output
projection. A backend derivation component calculates Equity × from the
projected `equity_cash_flow` series and supplies both baseline and current
values. Overview and Sensitivity consume the same backend result.

This collection is separate from canonical scalar outputs. A derived Equity ×
is display evidence, not a selectable calculation output, formula-graph node,
override target, or Sensitivity analysis target.

## Data Contract

Add a derived KPI item to `CalculationRunOutputsResponse`:

```text
derived_kpis:
  - role: equity_multiple
    label: Equity ×
    unit: x
    source_type: derived
    availability_status: available | partial | unavailable
    source_ids: [<equity_cash_flow financial_series_id>]
    baseline: <CalculationProjectedValueItem>
    current: <CalculationProjectedValueItem>
```

`baseline` and `current` reuse the existing typed projected-value contract.
Numeric values remain decimal strings at the API boundary. The item has no
synthetic `output_id`, because consumers must not submit it as a calculation or
Sensitivity target.

`source_ids` contains the selected equity cash-flow series UUID. Point-level
provenance remains available in the existing series output projection and is
not duplicated in the derived item.

## Source Resolution

The derivation component operates on a completed
`CalculationRunOutputsResponse`, not on workbook cached values or extraction
JSON.

It resolves one `equity_cash_flow` series using the same strict presentation
rules as the existing analysis pages:

1. use the model's `ModelSemanticBinding` for `equity_cash_flow` when present;
2. otherwise accept exactly one series whose canonical business role is
   `equity_cash_flow`;
3. do not select candidates by fuzzy label similarity; and
4. treat missing, ambiguous, cross-model, or non-series sources as unavailable.

The selected series, calculation run, model version, graph version, baseline
identity, and current identity must all come from the same run projection.

## Calculation Rules

Baseline and current are calculated independently. For each side:

1. require every projected point in the selected series to be available and a
   numeric value;
2. parse every value as `Decimal`;
3. add values greater than zero to `total_inflow`;
4. add values less than zero to `total_outflow`;
5. ignore numeric zero values;
6. calculate `outflow_magnitude = abs(total_outflow)`; and
7. when `outflow_magnitude > 0`, return
   `total_inflow / outflow_magnitude`.

A complete series with zero inflow and non-zero outflow produces an available
`0` multiple. A zero outflow denominator is unavailable. The backend preserves
full `Decimal` precision in the API value; the UI applies the existing two
decimal `x` presentation.

If baseline is unavailable but current is valid, or vice versa, the derived KPI
has `partial` overall availability while preserving the status of each side.
If both sides are unavailable, overall availability is `unavailable`.

## Unavailability and Diagnostics

The derived metric must expose typed diagnostic reasons through the existing
projected-value fields:

- `EQUITY_CASH_FLOW_UNAVAILABLE`: the selected series contains a missing,
  non-numeric, unsupported, blocked, or failed point;
- `EQUITY_CASH_FLOW_NOT_FOUND`: no authoritative series can be resolved;
- `EQUITY_CASH_FLOW_AMBIGUOUS`: more than one unbound canonical series is
  eligible; and
- `EQUITY_CASH_OUTFLOW_ZERO`: the complete selected series has no negative cash
  outflow.

Existing point execution, engine, validation, and warning details remain on the
source series projection. The derived item may propagate a stable summary
warning, but it must not replace the underlying evidence.

The system must not fall back to:

- a workbook-provided `equity_multiple` scalar;
- `debt_to_equity_ratio`;
- `total_equity`, `total_project_cost`, `total_capex`, or another denominator;
- cached workbook values; or
- a partial sum of the available periods.

## Backend Components

Create a focused derivation module responsible for:

- resolving the authoritative equity cash-flow series from a run projection;
- aggregating one baseline/current point set;
- returning the typed derived KPI projection; and
- combining baseline/current availability into the item-level status.

`CalculationIntegrationService.get_run_outputs()` remains the persisted
run-projection boundary. After it builds the canonical scalar and series
outputs, it invokes the derivation component and attaches `derived_kpis` before
returning the response.

`AnalysisPresentationService.overview()` reads the derived
`equity_multiple` item for the `leverage` slot. It presents the current value as
`source_type="derived"`, label `Equity ×`, unit `x`, and the derived source IDs.
If the derived item is unavailable, Overview displays `Unavailable` without
trying its former scalar or debt/equity fallbacks.

No database migration or new canonical business role is required. Both inputs
are positive and negative values from the existing `equity_cash_flow` role.

## Sensitivity Integration

The Sensitivity output adapter reads `derived_kpis` alongside canonical scalar
and series outputs. It maps the derived baseline/current projected values into
the fixed dashboard's `equity_multiple` display slot without adding the item to
the selectable KPI/output catalog.

The derived metric must not change:

- `selected_output_id`;
- `irrOutputId`;
- calculation or Sensitivity request payloads;
- assumption overrides;
- baseline, override, or case-run creation;
- Tornado ranking or Two-way matrices;
- request coalescing or stale-response guards; or
- persisted localStorage/document formats.

An exact override run refreshes the derived baseline/current values as part of
the existing run-output GET. Estimated slider previews do not calculate Equity
× in the browser. Until an exact calculation completes, the card retains the
last exact derived value and existing pending/stale presentation behavior.

## Relationship to the KPI Alignment Design

This design supersedes only the Equity × selection described in
`2026-08-04-sensitivity-overview-kpi-selection-design.md`:

- IRR, NPV, Payback, and DSCR continue to align their displayed scalar outputs
  with Overview as specified there.
- Equity × no longer matches an Overview `source_ids[0]` value to a scalar
  `SensitivityKpi.outputId`.
- Both pages instead consume the backend's run-scoped derived KPI.
- The derived item identifies its source series but is never treated as a
  selectable output.

Before implementation, the KPI alignment spec must be amended so its slot
mapping, adapter signature, tests, and acceptance criteria reflect this
derived-metric exception.

## Testing Strategy

Implementation follows RED to GREEN.

### Pure backend derivation tests

- multiple negative contributions and positive distributions produce the exact
  expected Decimal ratio;
- cash flows `[-40, -60, 0, 25, 50, 75]` produce `1.5`;
- zero inflow with non-zero outflow produces available `0`;
- zero outflow produces `EQUITY_CASH_OUTFLOW_ZERO`;
- any unavailable, error, blank, text, or unsupported point makes that side
  unavailable without partial aggregation;
- baseline and current are derived independently and produce `partial` when
  only one side is valid;
- reviewed semantic binding wins over another same-role series;
- multiple unbound same-role series produce ambiguity rather than first-match
  selection; and
- an existing scalar `equity_multiple` or `debt_to_equity_ratio` is ignored.

### Backend API and Overview tests

- run outputs expose one derived Equity × item with decimal-string values and
  the authoritative series source UUID;
- the derived item carries the same run/model/graph/baseline identities as its
  source projection;
- Overview uses the derived current value and `source_type="derived"`;
- Overview returns `Unavailable` when derivation is unavailable and does not
  use the old fallbacks;
- a baseline run and an exact override run return the expected baseline/current
  ratios; and
- GET-only restoration does not create calculations or mutate database rows.

### Frontend tests

- Sensitivity maps the derived item into the fixed Equity × card with baseline,
  current, delta, and `x` formatting;
- Overview and Sensitivity display the same exact current value for the same
  run;
- unavailable and partial states remain typed and never render as zero;
- the derived item never becomes `selected_output_id` or `irrOutputId`;
- no frontend code divides or aggregates equity cash-flow points;
- an exact recalculation refreshes the card from the returned run projection;
  and
- calculation requests, automatic case counts, Tornado rows, and Two-way matrix
  inputs are unchanged.

### Regression gates

- run focused backend derivation, calculation-service, API, and presentation
  tests;
- run the complete backend test suite;
- run focused frontend calculation tests;
- run the complete frontend test suite;
- run the production frontend build; and
- run `git diff --check`.

## Acceptance Criteria

For a persisted model whose equity cash-flow series contains both contributions
and distributions:

1. the backend derives baseline and current Equity × using the approved
   positive-inflow/absolute-negative-outflow formula;
2. Overview and Sensitivity display the same current multiple for the same
   calculation run;
3. Sensitivity displays the correct baseline, current, and delta after an exact
   override run;
4. models without an explicit `equity_multiple` still display the derived value
   when their complete equity cash-flow series is available;
5. model-provided multiples and debt/equity ratios never override or backfill
   the derived result;
6. incomplete, ambiguous, non-numeric, or zero-outflow evidence displays
   `Unavailable` rather than a guessed or partial multiple; and
7. calculation identities, selected outputs, Sensitivity cases, Tornado data,
   Two-way data, and persisted browser state are unchanged by the display-only
   derived KPI.

## Non-Goals

- changing workbook extraction or reducing workbook context;
- adding a `total_assets` business role;
- adding a new database table or migration;
- persisting a synthetic canonical output;
- making Equity × an override or analysis target;
- calculating estimated Equity × values in the browser; or
- redesigning either page's fixed KPI layout.
