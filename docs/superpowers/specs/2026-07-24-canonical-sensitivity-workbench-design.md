# Canonical Sensitivity Workbench Design

## Status and provenance

This design applies to the linked worktree
`Canonical_Output_Audit` on branch
`audit/canonical-output-sensitivity-readiness` at starting commit
`851f363`.

The branch already contains:

- canonical calculation input discovery;
- canonical scalar and financial-series output discovery;
- deterministic persisted calculation runs; and
- persisted run output projection.

The existing uncommitted frontend output viewer is preserved and becomes the
starting point for the interactive workbench.

## Goal

Turn `/sensitivity` into a model-driven workbench where:

- the left panel is populated from the selected model's editable numeric
  canonical assumptions;
- changing one or more assumptions submits canonical UUID overrides;
- the top output cards and baseline/current comparison use persisted,
  deterministic calculation results;
- a tornado chart is calculated from real low/high engine cases;
- a two-way sensitivity matrix is calculated from real Cartesian engine cases;
  and
- labels, values, units, inputs, outputs, and source mappings come from the
  selected model rather than workbook-specific names or cell addresses.

## Non-goals

- Do not reuse or extend the legacy name-based
  `/scenarios/{id}/sensitivity/realtime` interpolation.
- Do not add a second calculation engine.
- Do not expose workbook sheet names or cell addresses in public sensitivity
  requests.
- Do not invent output values when a formula is unsupported, blocked, missing,
  or unavailable.
- Do not add sensitivity result tables in the first slice. Existing immutable
  calculation runs are the persisted case store.
- Do not broadly expand the Excel function registry as part of the orchestration
  change. Unsupported functions remain explicit and can be added later from a
  measured model dependency closure.

## Architecture

### 1. Separate execution reuse from comparison baseline

`calculation_runs.base_run_id` currently records the latest compatible run used
for incremental reuse. That run is not necessarily the business baseline.

Add a repository query for a completed, zero-override run matching:

- model version;
- graph version;
- engine version;
- function-registry version;
- semantics profile; and
- run-policy hash.

Run output projection will keep `base_run_id` as execution provenance and add
`comparison_baseline_run_id`. Baseline values always come from that explicit
zero-override run. A missing matching baseline is an explicit error; the
projector must not compare an override to itself or to another override.

### 2. Add a bounded canonical sensitivity service

Add a small service beside `CalculationIntegrationService`. It reuses:

- canonical input validation and UUID-to-cell translation;
- deterministic calculation requests;
- persisted run reload;
- true-baseline output projection; and
- typed available/unavailable output values.

The request contains only:

- the graph version UUID;
- a selected scalar output UUID;
- current canonical overrides;
- canonical drivers with explicit low/high numeric values; and
- an optional pair of canonical drivers with explicit row/column numeric
  values for a two-way grid.

The service limits one analysis to:

- at most 12 one-way drivers;
- at most 5 row values;
- at most 5 column values; and
- at most 50 generated cases in total.

Every generated case is a normal deterministic calculation run. Repeating the
same analysis reuses the same run IDs instead of inserting duplicates.

The response returns:

- the zero-override comparison baseline run ID;
- the current-scenario run ID;
- selected output metadata and baseline/current typed values;
- one-way low/high case values and run IDs;
- tornado impact only when both endpoints are available numeric values;
- two-way cells with actual run IDs and typed availability; and
- warnings for unavailable drivers, outputs, or cells.

### 3. Reuse unclassified mapped series without guessing

Financial series with a null business role remain valid canonical model
content. Output discovery will expose them as `unclassified` rather than
silently filtering them out. The UI may group them under “Other model
outputs,” but must not infer a role from their label.

Historical models with no persisted scalar output rows still require
re-extraction or evidence-based persistence retry. The sensitivity layer will
not fuzzy-match workbook labels to synthesize missing output rows.

## Frontend data flow

### Initial load

1. Read model, graph, baseline run, and override run IDs from versioned
   calculation storage.
2. GET readiness and all pages of editable canonical parameter inputs.
3. GET the persisted baseline and current output projections.
4. Build sliders only for editable numeric parameters.
5. Build the output selector from available numeric scalar outputs.
6. Default the selected output in this order:
   `project_irr`, `equity_irr`, `npv`, then the first available numeric scalar
   output.

Reload remains GET-only. It does not submit calculations.

The page stores a versioned sensitivity UI document containing only:

- model and graph UUIDs;
- canonical target UUID to decimal-string override values;
- selected tornado driver UUIDs;
- selected output UUID; and
- selected two-way row and column driver UUIDs.

The document is accepted only when its model and graph match current readiness.
It is cleared on a new upload or graph change. Persisted run IDs remain in the
existing calculation storage keys.

### Slider interaction

- A slider represents an actual canonical numeric value.
- Its default range is the uploaded value plus or minus 20 percent of its
  absolute magnitude.
- Step size is derived from that range and stored as a decimal string before
  submission.
- Percentage inputs use their stored decimal value; formatting may display a
  percent, but the request does not multiply or relabel the persisted value.
- A zero-valued assumption has a numeric text input but no invented relative
  slider range. It can enter an analysis after the user supplies a non-zero
  current value.
- All changed sliders are combined into one canonical multi-override request.
- A revision guard and debounce ensure only the newest response updates the
  page.
- A successful response persists the current run ID and the versioned
  sensitivity UI document together.

After a settled interaction, the page submits one bounded sensitivity request.
While it runs, the previous charts remain visible with a “recalculating” state.

### Driver selection

All editable numeric assumptions remain adjustable. Up to 12 may be included in
the current tornado analysis. The first 12 are selected deterministically by
category, label, and target UUID; users can replace them without changing the
underlying assumption values.

The two-way matrix uses two user-selectable assumptions and five relative
positions (`-20%`, `-10%`, current, `+10%`, `+20%`) translated to explicit
actual values before the request is sent.

## Layout derived from the reference image

The existing application theme and navigation stay intact.

- Left: scrollable canonical assumption controls, current value, unit,
  reset-all action, and driver inclusion control.
- Top: dynamically ordered output cards from the current persisted run.
- Center/right: selected-output control and a horizontal tornado chart ranked
  by absolute low/high impact.
- Bottom-left: baseline versus current scenario comparison for every returned
  scalar output.
- Bottom-right: selected-output two-way sensitivity matrix with dynamic row and
  column assumption selectors.
- Lower sections: the existing canonical time-series baseline/current charts.

No LNG project name, WACC label, throughput fee, IRR cell, or other
workbook-specific value is embedded in the page.

## Error and unavailable states

- No stored model or graph: link to the calculation flow.
- No zero-override run: explain that a baseline calculation is required; do not
  POST automatically on reload.
- Stale override run: clear only the stale override ID and fall back to the
  stored baseline through GET.
- Graph/model mismatch: reject the response and preserve the previous valid
  view.
- Unsupported or blocked output: show its reason and exclude it from numeric
  ranking without replacing it with zero.
- Partially unavailable two-way grid: render available cells and mark the
  failed cells individually.
- Request bounds exceeded: return a structured 422 error.

## Performance and React behavior

- Keep expensive chart derivation in pure adapter functions.
- Memoize chart rows and matrix cells by response identity.
- Use one debounced request per settled slider change.
- Use request revisions so an older response cannot overwrite newer slider
  state.
- Keep static role order and lookup structures outside React components.
- Do not add another chart dependency; use the installed Recharts package and
  an accessible HTML table for the heat matrix.

## Testing

### Backend

- Reproduce baseline → override A → override B and prove both projections use
  the same zero-override comparison baseline.
- Reject a baseline with non-empty overrides or mismatched run policy.
- Reject non-canonical targets, duplicate drivers, non-numeric values, and
  over-limit grids.
- Prove one-way endpoints and every two-way Cartesian cell are real persisted
  calculation runs.
- Prove deterministic replay returns the same run IDs.
- Preserve unavailable output states.
- Prove two models can use different canonical UUIDs and source cells without
  changing the sensitivity service.

### Frontend

- Load all paginated inputs and retain only editable numeric assumptions.
- Build multi-overrides using only canonical UUIDs and decimal strings.
- Derive slider ranges for positive, negative, percentage, and zero values.
- Select the default output by role order with a model-driven fallback.
- Ensure stale requests cannot replace the newest result.
- Map one-way cases into ranked tornado rows without label matching.
- Map partial two-way results into an accessible matrix.
- Restore through GET only and fall back from a stale override to baseline.
- Assert the page contains no legacy sensitivity call or workbook-specific
  mappings.

### Acceptance

For at least two model fixtures with different assumption and output UUIDs:

1. establish a zero-override persisted baseline;
2. load assumptions and outputs on `/sensitivity`;
3. change a slider;
4. observe a new persisted current run;
5. observe updated top outputs and baseline/current comparison;
6. observe tornado endpoints backed by run IDs;
7. observe a two-way matrix backed by Cartesian run IDs; and
8. reload and prove the persisted state is restored with GET requests only.

Formula outputs that remain unavailable are reported as limitations rather than
used as fabricated acceptance evidence.
