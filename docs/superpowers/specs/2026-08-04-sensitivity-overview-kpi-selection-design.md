# Sensitivity Overview-Aligned KPI Selection Design

## Objective

Make the fixed KPI cards on the Sensitivity page select the same persisted
calculation outputs as Overview, while leaving all Sensitivity calculation,
analysis, persistence, and restoration behavior unchanged.

## Problem

Overview resolves each KPI through its run-scoped presentation projection. That
projection applies the persisted `ModelSemanticBinding` and returns the selected
canonical output UUID in `source_ids`.

Sensitivity currently builds its fixed KPI cards directly from the complete
calculation-output projection. For roles with multiple candidates, it sorts by
business-role rank, label, and output UUID, then displays the first available
numeric candidate. A model can therefore show Project NPV in Overview and Equity
NPV in Sensitivity even though both pages refer to the same calculation run.

## Scope

This change affects the display source selected for four fixed Sensitivity KPI
slots:

- IRR;
- NPV;
- Payback;
- DSCR.

Sensitivity uses the current run's existing Overview response as the selection
authority for those four scalar slots. Each available Overview KPI identifies
its canonical calculation output through `source_ids[0]`. Sensitivity matches
that UUID to its existing `SensitivityKpi.outputId` and displays the matched
KPI's baseline, current value, delta, unit, and availability details.

Equity × is governed by
`2026-08-04-derived-equity-multiple-design.md`. It bypasses scalar source-ID
alignment and consumes the exact backend `derived_kpis` projection.

## Non-Goals

The change must not alter:

- `selected_output_id` used by Sensitivity analysis;
- calculation or sensitivity request payloads;
- assumption overrides;
- baseline, override, or sensitivity-case run creation;
- Tornado impact calculation or ranking;
- Two-way matrix calculation;
- debounce, request coalescing, or stale-response guards;
- localStorage keys, document format, or restoration behavior;
- routes, semantic-binding persistence, or calculation logic;
- fixed-page layout or user-facing KPI labels.

## Selected Approach

The Sensitivity page reuses `GET /api/v1/calculation-runs/{run_id}/overview`.
No new backend endpoint or semantic-binding contract is introduced.

The existing fixed-dashboard resolver remains responsible for all calculation
and analysis decisions, including `irrOutputId`. A new pure presentation adapter
aligns only the resolved dashboard slots with Overview:

```ts
alignDashboardSlotsWithOverview(
  dashboard: FixedDashboardViewModel,
  sensitivityKpis: readonly SensitivityKpi[],
  overviewKpis: readonly AnalysisKpi[],
  derivedKpis: readonly SensitivityDerivedKpi[] = [],
): FixedDashboardViewModel
```

The adapter returns a dashboard whose four scalar `slots[*].kpi` values are
selected by Overview source UUID. It fills Equity × from the separate derived
collection. It preserves `dashboard.irrOutputId` exactly, preventing the
presentation alignment from changing the Sensitivity analysis target.

## Slot Mapping

The display adapter uses these Overview slots:

| Sensitivity slot | Overview slot selection |
| --- | --- |
| `irr` | `primary_return` |
| `npv` | `npv` |
| `payback` | `payback_period` |
| `dscr` | `average_dscr` when available, otherwise `minimum_dscr` |

The DSCR order preserves the existing Sensitivity display preference. Each DSCR
candidate has already been resolved through Overview's semantic binding before
the display adapter sees it.

### Derived Equity × exception

Equity × consumes
`CalculationRunOutputsResponse.derived_kpis[role="equity_multiple"]`. The
derived item has no `output_id`, is not added to the scalar KPI/output catalog,
and cannot affect `irrOutputId`, `selected_output_id`, or a Sensitivity request.

## Data Flow

During initial workbench bootstrap:

1. restore the current calculation-output projection through the existing
   GET-only workflow;
2. after the final current run ID is known, request Overview for that exact run;
3. verify that Overview and calculation outputs have identical run, model, and
   graph identities;
4. build the existing exact or estimated Sensitivity KPI view;
5. build the existing fixed dashboard, retaining its calculation-owned
   `irrOutputId`; and
6. align four scalar dashboard slots using Overview `source_ids`; and
7. fill Equity × from the exact `derived_kpis` item returned with the run
   projection.

After an exact override calculation completes, Overview is fetched for the new
current run so the displayed cards remain aligned. Failure to refresh Overview
must not modify the calculation request, calculation result, or persisted
Sensitivity document.

The Overview response and derived display selection remain in React memory.
They are not written to localStorage because Overview remains the server-owned
selection authority.

Estimated slider previews continue to update the already selected scalar output
UUIDs. Equity × retains the last exact derived baseline/current values until a
new exact calculation-run projection arrives; the browser does not aggregate
or divide equity cash-flow points.

## Availability and Error Behavior

- An available Overview KPI must contain exactly one usable source output UUID.
- If the Overview slot is unavailable or has no source UUID, the corresponding
  Sensitivity slot displays `Unavailable`; it does not fall back to another
  same-role or similarly labelled output.
- If an available Overview source UUID is absent from the same run's Sensitivity
  output projection, the display adapter treats the slot as unavailable and
  exposes an identity-mismatch detail. It does not guess a replacement.
- A matched output that is non-numeric or unavailable remains `Unavailable` and
  retains its typed calculation diagnostics.
- An Overview response whose calculation-run, model, or graph identity differs
  from the output projection is rejected as stale. The previous verified display
  remains visible.
- Overview fetch failure affects only the aligned KPI display. It must not submit
  another calculation or mutate calculation identity in browser storage.
- Missing, partial, or unavailable derived Equity × evidence remains typed
  `Unavailable` and never falls back to scalar `equity_multiple` or
  `debt_to_equity_ratio`.

## Testing Strategy

Implementation follows RED to GREEN with focused frontend tests.

### Pure adapter tests

- Provide available Project NPV and Equity NPV outputs and prove an Overview
  `source_ids` reference to Project NPV selects Project NPV regardless of label
  order.
- Prove each of the four scalar fixed slots maps to its specified Overview slot.
- Prove Average DSCR remains preferred over Minimum DSCR when both Overview slots
  are available.
- Prove an unavailable Overview slot remains unavailable without role or label
  fallback.
- Prove an unknown or non-scalar Overview source UUID produces a typed unavailable
  display slot.
- Prove `irrOutputId` is byte-for-byte identical before and after display
  alignment.
- Prove estimated KPI values update the bound UUID without changing the bound
  UUID.
- Prove Equity × uses the derived KPI with `outputId: null`, never displays a
  scalar workbook multiple, and is never marked as an estimated output.

### Page contract tests

- Prove the Sensitivity page reads Overview for the restored current run.
- Prove a completed exact calculation refreshes Overview for the returned run ID.
- Prove cross-run, cross-model, and cross-graph Overview responses cannot replace
  a verified display.
- Prove GET-only restoration remains GET-only.
- Prove Sensitivity request construction, Tornado rows, and Two-way matrix inputs
  remain unchanged.

### Regression gates

- run the focused calculation frontend test suite;
- run the full frontend test suite;
- run the production frontend build; and
- run `git diff --check`.

## Acceptance Criteria

Using a persisted model with distinct Project NPV and Equity NPV outputs:

1. Overview and Sensitivity use the same NPV `source_id` for the same calculation
   run;
2. both pages display the same rounded NPV value and unit;
3. the current observed run displays Project NPV rather than the alphabetically
   first Equity NPV candidate;
4. Sensitivity `selected_output_id`, request payloads, run identities, case count,
   Tornado results, and Two-way matrix results are unchanged by the display
   alignment; and
5. missing or inconsistent Overview selection displays `Unavailable` instead of
   another same-role candidate.
