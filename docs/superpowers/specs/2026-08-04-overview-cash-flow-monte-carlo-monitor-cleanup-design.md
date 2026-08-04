# Overview, Cash Flow, Monte Carlo, and Monitor Cleanup Design

**Date:** 2026-08-04

**Status:** Approved for implementation planning

## Goal

Make four bounded corrections without redesigning the application:

1. render Overview Capital Structure as a trustworthy Debt/Equity pie chart even when the workbook does not provide paired ratio series;
2. recover Annual Project Free Cash Flow and its derived Cumulative Cash Flow from already persisted workbook series;
3. fix Monte Carlo's only target output to Project IRR and complete one persisted end-to-end run;
4. remove the Monitor product page and its obsolete frontend, API, agent, orchestration, and deployment surfaces.

The work must reuse persisted canonical data, preserve provenance, and leave missing or ambiguous values as `Unavailable`.

## Current Evidence

The live local PostgreSQL database contains four materialized models with 30-37 financial series and 336-997 financial-series values per model. All four contain two or three persisted series labelled as Project Cash Flow, Project CF, Unlevered Project Cash Flow, or Project Free Cash Flow. None has the exact `project_free_cash_flow` business role or a `project_free_cash_flow` semantic binding. The Cash Flow API therefore returns empty Annual Project FCF, and Cumulative Cash Flow is empty because it is derived from that annual source.

The Capital Structure read model currently requires paired Debt/Equity ratio series or paired Debt/Equity amount series. The observed models do not provide those pairs. Three models contain an explicit `Debt share` parameter, while the remaining model contains debt and total funding/project-cost evidence suitable for a controlled ratio calculation.

Monte Carlo currently exposes every supported output, initializes all of them as selected, and accepts a list of one to five output roles. One existing PF Lean run completed with both Equity IRR and Project IRR. The new contract must create only Project IRR runs while continuing to read older multi-output history.

Monitor currently spans `/monitor`, two legacy backend endpoints, `MonitorAgent`, an orchestrator intent, and deployment-agent lists. The shared DSCR tool is also named by the Cash Flow agent and is not Monitor-exclusive.

## Scope

### Included

- Overview Capital Structure read-model derivation and pie-chart percentage presentation.
- A strict Project FCF compatible-role rule in the existing semantic-binding selector.
- A controlled, idempotent backfill of missing extracted Project FCF bindings for the four existing materialized models.
- Annual Project FCF resolution and existing cumulative derivation through the new binding.
- A Project-IRR-only Monte Carlo creation contract and fixed frontend target.
- One new 50,000-trial Project IRR Monte Carlo run for the existing `PF_Lean_Model.xlsx` model.
- Removal of all Monitor-specific frontend, API, agent, orchestration, and deployment surfaces.

### Excluded

- Workbook re-upload, Azure calls, extraction prompt changes, chunking changes, or reduced workbook context.
- Database schema changes or migrations.
- Fabricated chart data, fuzzy label matching, or zero-valued placeholders.
- Rewriting or deleting historical Monte Carlo records.
- Removing the shared DSCR tool, generic alert capability, report prose that uses the ordinary word "monitor", or Azure Monitor infrastructure commands.
- Unrelated frontend redesign or backend refactoring.

## Architecture and Data Flow

### 1. Capital Structure Pie Chart

`AnalysisPresentationService` remains the owner of the Overview read model. It will produce exactly two derived presentation series, Debt and Equity, each with one ratio point.

The debt ratio is resolved in this order:

1. Resolve the current calculation run's explicit `Debt share` parameter using the existing strict parameter-resolution boundary plus the exact normalized alias `debt share`. The current run override wins over the persisted validated parameter value.
2. If no explicit share resolves, divide a uniquely bound debt amount by a uniquely resolved `Total project cost` or `Total funding requirement` amount.

The derived equity ratio is `1 - debt_ratio`.

The amount fallback must use the persisted calculation projection rather than raw workbook cells. The debt numerator is the model's semantic debt binding. Project-cost candidates are restricted to the controlled business role and exact normalized labels. Duplicate candidates are acceptable only when their available numeric values and compatible units agree; otherwise the denominator is ambiguous.

The API returns the two derived series with the underlying parameter/output IDs in `source_ids`. `fallback_used` identifies either `model_debt_share` or `debt_over_total_project_cost`. `AnalysisChartItem` gains an optional `unavailable_reason` string for a failed capital-data contract; this is an API response extension, not a database change. The frontend does not search for data or calculate the ratio.

`CapitalStructure` remains a pie chart. When available it renders exactly two slices, Debt and Equity. The legend and tooltip show percentages such as `Debt 65.0%` and `Equity 35.0%`, and the subtitle describes the source. When unavailable, the existing card remains and displays `Unavailable` without an empty pie.

### 2. Annual and Cumulative Project Free Cash Flow

The existing `ModelSemanticBinding` mechanism remains the only selection boundary. `build_extracted_semantic_bindings()` receives one narrow compatible-role rule for requested semantic role `project_free_cash_flow`.

Eligible series must:

- belong to the current model;
- have valid persisted points and non-rejected validation;
- have business role `cash_flow`, or business role `cfads` only when its exact normalized label identifies Project FCF;
- have one of these exact normalized labels: `project free cash flow`, `project fcf`, `unlevered project cash flow`, `project cash flow`, or `project cf`.

The existing deterministic scoring remains in force. A workbook-authored calculated series outranks a pure cross-sheet direct-reference copy. Strong labels such as `project free cash flow` and `unlevered project cash flow` outrank generic `project cash flow`/`project cf` when provenance evidence is otherwise equal. Stable source and entity-ID ordering resolves a remaining tie. All alternatives and score reasons remain in binding evidence.

A bounded backfill previews and then inserts only missing `binding_source="extracted"` Project FCF bindings for existing materialized models. It is idempotent and never overwrites a reviewed binding or any existing binding. It does not rewrite the stored series, points, roles, or extraction snapshot.

Annual Project FCF continues to resolve by binding UUID through `AnalysisPresentationService`. Cumulative Cash Flow remains a read-model derivation that accumulates the annual values in period order. A missing annual value remains missing, and the cumulative series stays unavailable from the first missing period onward.

### 3. Project-IRR-Only Monte Carlo

The input catalog, distributions, correlation matrix, trial count, seed, calibration, queue, worker, and result-artifact model remain unchanged.

The creation contract changes as follows:

- the catalog exposes `project_irr` as its only supported output when it resolves unambiguously;
- a create request must contain exactly `selected_output_roles=["project_irr"]`;
- empty, multiple, or non-Project-IRR selections are rejected by the backend;
- when Project IRR is unavailable, the catalog has no supported target and the frontend disables execution with a specific explanation.

The frontend removes output-selection state and checkboxes. It displays a read-only `Target output: Project IRR` section and always submits the fixed list. Response and history types remain broad enough to read existing artifacts that contain other metrics.

The local runtime acceptance uses the existing prepared PF Lean model and its active calculation run. It creates a new 50,000-trial request with only Project IRR. Because the selected-output configuration differs from the old multi-output run, it produces a distinct request identity and artifact.

### 4. Monitor Removal

Remove the following Monitor-specific surfaces:

- the Next.js `/monitor` page and navigation item;
- Monitor-only frontend API functions;
- the Monitor tab type and Monitor-only assistant starter data;
- the legacy `/api/v1/investments/{investment_id}/monitor` router and registration;
- the `/api/v1/scenarios/{scenario_id}/monitor` handler and code used only by that handler;
- Monitor-only schemas after confirming no remaining imports;
- `apps/agents/monitor`;
- the Monitor orchestrator intent, keywords, and agent mapping;
- the Monitor agent entry in deployment lists and any Monitor-agent-only deployment block.

Do not remove the shared `DSCRMonitor` tool because the Cash Flow agent still declares it. Do not remove generic monitoring prose or Azure Monitor infrastructure commands.

After removal, `/monitor` returns the framework's normal 404 and neither legacy Monitor API appears in OpenAPI.

## Validation and Error Handling

### Capital Structure

- Debt share must be numeric and within `[0, 1]`.
- The amount fallback requires uniquely resolved values, compatible currency/unit scale, positive project cost, and `0 <= debt <= project_cost`.
- An explicit valid Debt share takes precedence over an available amount calculation.
- Any invalid, unavailable, unit-incompatible, or ambiguous input produces `Unavailable` with a typed quality/unavailable reason. It never produces zero or a guessed substitute.

### Project FCF

- Invalid ranges, missing points, rejected validation, non-whitelisted labels, and cross-model entities remain ineligible.
- Reviewed bindings always override extracted selection and are never overwritten by backfill.
- Backfill failure does not partially update a model; each model's binding insertion is transactional and the preview identifies the exact target model and series.

### Monte Carlo

- The API is the enforcement boundary; hiding controls in the UI is not sufficient.
- Existing queue error codes, persisted failed status, cancellation, and worker diagnostics remain unchanged.
- Historical multi-output records are read-only compatibility data and are neither converted nor deleted.

### Monitor

- Remove only definitions proven to be Monitor-specific by reference search and tests.
- Shared DSCR, alerts, scenario calculation, reporting, and infrastructure monitoring remain intact.

## Testing Strategy

Implementation uses strict RED to GREEN for each production behavior change.

### Backend focused tests

- Explicit Debt share produces Debt/Equity ratios with parameter provenance.
- A current-run Debt share override takes precedence over the persisted value.
- Debt divided by total project cost produces the same two ratios with output provenance.
- Duplicate equal project-cost candidates are accepted; conflicting values, incompatible units, zero denominator, negative values, and ratios over one are unavailable.
- Project FCF compatible-role selection accepts only the exact label allow-list.
- A workbook-authored series outranks a direct-reference alias.
- Reviewed binding precedence and idempotent missing-only backfill are preserved.
- Annual Project FCF resolves through the binding, and cumulative values propagate missing periods correctly.
- Monte Carlo catalog returns only Project IRR; create rejects zero, multiple, and non-Project-IRR roles.
- OpenAPI no longer contains either legacy Monitor endpoint.

### Frontend focused tests

- Capital Structure remains a pie chart with exactly Debt and Equity slices and percentage formatting.
- Unavailable capital data does not render an empty pie.
- Monte Carlo renders a read-only Project IRR target, submits only Project IRR, and has no output checkboxes.
- Navigation, API helpers, assistant starter data, and route sources contain no Monitor product entry.

### Static and full verification

- Run the focused backend and frontend tests first.
- Run the complete backend test suite with actual pass/skip counts.
- Run the complete frontend test suite and production build.
- Run Python compilation checks for changed backend modules.
- Run `git diff --check`.
- Confirm Monitor references that remain are limited to approved shared or infrastructure meanings.

## Local Runtime Acceptance

No workbook upload or Azure call is permitted for this acceptance.

1. Verify host and rebuilt API, analysis-worker, and UI source provenance.
2. Run Project FCF backfill in preview mode and record the four target model/series selections.
3. Apply the missing-only backfill and prove no reviewed or existing binding changed.
4. Call the four existing calculation-run Cash Flow APIs and confirm Annual Project FCF contains persisted points and Cumulative Cash Flow contains derived points with matching periods.
5. Call the four Overview APIs and confirm Capital Structure is available only where a validated explicit share or validated debt/project-cost calculation exists.
6. Visually verify the Overview Debt/Equity pie chart and its percentage tooltip/legend.
7. From the Monte Carlo page for existing `PF_Lean_Model.xlsx`, submit one 50,000-trial run.
8. Wait for persisted status `completed` and verify the result artifact contains exactly one metric, `project_irr`, with percentiles, distribution, probabilities when a hurdle exists, and ranking data.
9. Verify the page renders the persisted Project IRR results without output-selection controls.
10. Verify `/monitor` returns 404 and both removed Monitor APIs are absent from OpenAPI.

## Acceptance Criteria

- Capital Structure remains a Pie Chart and shows exactly Debt and Equity percentages from validated persisted evidence.
- Explicit Debt share is preferred; the fallback is Debt divided by Total Project Cost or Total Funding Requirement.
- Invalid or ambiguous capital data remains `Unavailable`.
- All four existing materialized models resolve a deterministic Project FCF binding without re-upload or Azure calls.
- Annual Project FCF and derived Cumulative Cash Flow contain real persisted data for the four existing calculation runs.
- New Monte Carlo requests can target only Project IRR.
- One new PF Lean 50,000-trial Project IRR run completes and persists a Project-IRR-only artifact that renders in the UI.
- Historical multi-output Monte Carlo artifacts remain readable.
- The Monitor page, frontend product references, two legacy APIs, Monitor Agent, orchestrator intent, and deployment-agent entry are removed.
- Shared DSCR and infrastructure-monitoring capability remain intact.
- Focused tests, full backend tests, full frontend tests, build, compilation, and `git diff --check` pass, apart from clearly identified pre-existing baseline failures.
