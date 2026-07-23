# Canonical Sensitivity Workbench Acceptance

## Outcome

PASS for the minimum canonical sensitivity workbench slice on
`audit/canonical-output-sensitivity-readiness`.

The implementation range starts after `851f363` and ends at `24c6370`.
It reuses persisted, model-specific canonical assumptions and outputs; it does
not define a workbook-specific assumption list, KPI list, sheet name, cell
address, or display-label mapping.

## Gap closure

| Starting gap | Minimum implemented closure |
| --- | --- |
| Incremental calculation reuse and business comparison both followed `base_run_id`. | `comparison_baseline_run_id` now identifies an exact, completed zero-override run; `base_run_id` keeps its execution-reuse meaning. |
| Mapped financial series with no business role were omitted. | They remain discoverable as `unclassified`; unavailable values remain typed and are never fabricated. |
| No bounded service composed current, one-way, and two-way sensitivity cases. | The canonical sensitivity endpoint runs current overrides, up to 12 one-way drivers, and an optional 5×5 Cartesian grid with a 50-generated-run request cap. |
| The sensitivity screen did not discover model-specific canonical parameters and outputs. | It paginates editable numeric parameters and renders every returned scalar and time-series output by canonical UUID. |
| The reference interaction was not wired to real persisted calculations. | Assumption changes are persisted locally, debounced for 400 ms, submitted to the real calculation facade, and reflected in output cards, tornado rows, baseline/current comparison, two-way matrix, and series charts. |
| Reload could have submitted work or mixed stale model/graph state. | Bootstrap and explicit refresh are GET-only; model/graph/output/revision guards reject stale responses and cross-tab identity changes. |
| Persisted off-grid decimals could be sanitized by a native range input. | The control derives an exact bounded step when possible and uses a focus-pinned `step="any"` number editor otherwise. |
| Narrow layouts could leak chart, table, or navigation min-content width. | Navigation rows, comparison tables, the two-way grid, and series cards contain their own horizontal overflow. |

## Canonical contract

- Public override and driver targets use only canonical `parameter_id` UUIDs.
- Selected outputs use canonical `output_id` UUIDs.
- Series points retain stable `financial_series_value_id` UUIDs.
- The UI uses labels, categories, units, scenarios, and periods only as
  response metadata for display.
- Every current, low, high, and matrix case is an ordinary immutable
  `calculation_run`; no sensitivity table or interpolation route was added.
- Unsupported, blocked, missing, and cycle outputs stay explicitly
  unavailable with their persisted reason and run provenance.

## Automated verification

### Backend non-PostgreSQL suite

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 \
  -m pytest -p no:cacheprovider -m 'not postgres' -q
```

Result: `481 passed, 5 deselected, 2338 warnings in 19.30s`.

The warnings are existing Pydantic protected-namespace warnings and openpyxl
`datetime.utcnow()` deprecations.

### Frontend component and contract suite

```bash
cd apps/ui
npm test
```

Result: `53 passed, 0 failed`.

This includes a rendered React component interaction covering the persisted
fallback decimal sequence `100.000001 -> 99 -> 99.5 -> blur`, after which the
control safely returns to a range with `step=0.1`.

### Frontend production build

```bash
cd apps/ui
npm run build
```

Result: PASS. Next.js compiled, type-checked, and generated all 12 pages.
`/sensitivity` was emitted at 15.8 kB with a 219 kB first load.

## Two-model persisted acceptance

The isolated executable acceptance harness used FastAPI `TestClient`, the
real repository workbook fixture factory, preparation/calculation/sensitivity
services, SQLAlchemy persistence, and public run/output reload routes.

Result:

```json
{
  "models": 2,
  "baseline_runs": 2,
  "drivers": 4,
  "matrix_cells": 18,
  "returned_case_ids": 28,
  "persisted_reload_checks": 28,
  "replays_without_new_runs": 2,
  "final_calculation_run_count": 30,
  "typed_unavailable_output_samples": 2
}
```

The two workbooks had different workbook, model, graph, selected parameter,
parameter source, selected output, and output source identities. Each response
returned 14 distinct persisted current/low/high/matrix run IDs; every ID
reloaded through the public run and output GET routes. Identical replay returned
the same case IDs without increasing the run count. Both cycle outputs remained
typed as unavailable.

## Browser acceptance

The fixture-backed workbench was exercised in the in-app browser at the
reference desktop viewport and at 320, 640, and 1024 CSS pixels.

Observed:

- the left panel displayed the fixture model's three discovered parameters;
- the top displayed only the scalar outputs returned by that model;
- one-way selection produced two real tornado drivers;
- the lower comparison showed the explicit zero-override baseline;
- the two-way section rendered a real 5×5 matrix;
- the returned canonical time series rendered below;
- rapid `Volume -> First reporting year` selection changes produced one
  sensitivity POST after debounce;
- reload issued readiness/input/run-output GETs and no calculation POST;
- persisted year `2030` reloaded as range value `2030`, `step=0.008`, with
  `stepMismatch=false`;
- document width equaled viewport width at all three responsive checks:
  `314/314`, `634/634`, and `1018/1018`.

Local visual evidence:

- `.superpowers/sdd/sensitivity-browser-wide.png`
- `.superpowers/sdd/sensitivity-browser-320.png`
- `.superpowers/sdd/sensitivity-browser-640.png`
- `.superpowers/sdd/sensitivity-browser-1024.png`
- `.superpowers/sdd/sensitivity-reference-comparison.png`

## Review

Task-level and final fix reviews found no remaining Critical or Important
findings. The final fix review specifically covered off-grid decimal editing,
native range validity, all navigation rows, series-chart overflow containment,
comparison formatting, and the responsive layout.

## Boundaries and limitations

- The two-model acceptance database was temporary SQLite, not PostgreSQL.
- The acceptance used two materially different real calculation fixtures, not
  live workbook upload, extraction/LLM execution, or production data.
- The browser fixture exposed two scalar outputs and three assumptions because
  those are the canonical values discovered for that fixture. The UI did not
  fabricate the five KPI cards or eight assumptions visible in the reference
  image.
- Circular outputs remain unavailable by design; this slice does not broaden
  the formula-function registry.
- No merge or push was performed.
