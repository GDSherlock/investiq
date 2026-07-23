# Canonical Sensitivity Workbench Acceptance

## Outcome

PASS for the minimum canonical sensitivity workbench slice on
`audit/canonical-output-sensitivity-readiness`.

The implementation range is `851f363..69c97b9`. It reuses persisted,
model-specific canonical assumptions and outputs. It does not define a
workbook-specific assumption list, KPI list, sheet/cell request contract, or
display-label mapping.

The linked worktree already contained in-progress sensitivity frontend files
when this acceptance pass began. Those changes were preserved and reviewed.
The main checkout's unrelated untracked report and Excel lock file were not
modified.

## Gap closure

| Starting gap | Minimum implemented closure |
| --- | --- |
| Incremental calculation reuse and business comparison both followed `base_run_id`. | `comparison_baseline_run_id` identifies the exact completed zero-override run; `base_run_id` keeps its execution-reuse meaning. |
| Mapped financial series without a business role were omitted. | They remain discoverable as `unclassified`; unsupported, blocked, missing, and cycle values remain typed unavailable. |
| No bounded service composed current, one-way, and two-way cases. | The canonical sensitivity endpoint runs current overrides, up to 12 one-way drivers, and an optional 5×5 Cartesian grid within a 50-generated-run request cap. |
| The sensitivity screen did not discover model-specific inputs and outputs. | It paginates editable numeric parameters and renders every returned scalar and time-series output using canonical IDs and response metadata. |
| The reference interaction was not wired to persisted calculations. | A 400 ms debounced control change updates current output cards, tornado rows, baseline/current comparison, two-way matrix, and series charts from persisted calculation runs. |
| Reload and cross-tab activity could mix stale model/run state or silently lose a workbench update. | Bootstrap and reconciliation are GET-only. A shared Web Lock serializes writers; operation-start model/graph/run snapshots provide compare-and-set rejection for stale readiness, baseline, override, and cleanup completions; the revisioned workbench transaction verifies commit or rollback and exposes failures. |
| Partial comparisons could look fully available. | Baseline and current availability are aggregated, invalid deltas are suppressed, and side-specific typed reasons are displayed. |
| Persisted decimals and intermediate numeric drafts could be coerced. | Range steps preserve valid persisted decimals; the fallback editor keeps local string drafts such as `-`, `.`, and scientific notation until a finite value is committed. |
| Narrow layouts could leak chart/table min-content width. | Navigation, comparison tables, the two-way grid, and series cards contain their own horizontal overflow; the document itself does not overflow at 320, 640, or 1024 CSS pixels. |

## Canonical contract

- Override and driver targets use canonical `parameter_id` or
  `financial_series_value_id` UUIDs.
- Selected outputs use canonical `output_id` UUIDs.
- Labels, categories, units, scenarios, periods, source cells, and formulas
  are display/provenance metadata only.
- Every current, low, high, and matrix case is an immutable
  `calculation_run`; no interpolation route or workbook-specific sensitivity
  table was added.
- The acceptance request audit observed zero labels, sheet names, cell
  addresses, or source coordinates in calculation POST bodies.

## Automated verification

### Backend non-PostgreSQL suite

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 \
  -m pytest -p no:cacheprovider -m 'not postgres' -q
```

Result: `492 passed, 5 deselected, 2354 warnings in 19.78s`.

The warnings are existing Pydantic protected-namespace warnings and openpyxl
`datetime.utcnow()` deprecations.

### Frontend suite

```bash
cd apps/ui
npm test
npm run build
```

Results:

- `68 passed, 0 failed`;
- Next.js compiled and type-checked all 12 pages;
- `/sensitivity`: `15.9 kB`, first load `221 kB`;
- the test runner uses an isolated `mktemp` directory, removes it on exit,
  and preserves compiler/test failure exit status.

The suite covers stale response rejection, GET-only restore, paginated
canonical discovery, partial/unavailable outputs, exact decimal control state,
same-run concurrent writers, verified rollback, calculation-page/workbench
serialization, same-baseline override invalidation, cross-model stale writers,
same-model late graphs, late baselines after newer overrides, and parallel
reload cleanup.

## Reproducible two-model acceptance

Run from the linked worktree:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 \
  scripts/acceptance/run_canonical_sensitivity_two_model.py
```

The command drives the real FastAPI, SQLAlchemy, workbook storage,
preparation, calculation, persistence, output projection, and sensitivity
paths against a temporary SQLite database. It rewrites the complete evidence
document at
`docs/reports/evidence/canonical-sensitivity-two-model.json`.

Observed totals:

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

### Model-specific identity and mapping evidence

| Model | Selected row driver source | Second driver source | Selected output source | Current value |
| --- | --- | --- | --- | --- |
| first | `Inputs!A1` | `Inputs!A2` | `Calc!B1` | `5` |
| second | `Inputs!A2` | `Inputs!A1` | `Calc!B2` | `54` |

The evidence document records the exact generated workbook, model, graph,
parameter, output, baseline-run, current-run, one-way-case, and matrix-case
UUIDs. It also asserts that the selected IDs and source mappings differ
between the two fixtures. The report intentionally does not copy those
per-run UUIDs because each isolated acceptance invocation creates a new
temporary fixture.

### One-way case results

| Model / driver | Low value | High value |
| --- | --- | --- |
| first / `Inputs!A1` | `4` | `7` |
| first / `Inputs!A2` | `4` | `7` |
| second / `Inputs!A2` | `45` | `63` |
| second / `Inputs!A1` | `48` | `60` |

The evidence JSON records all 18 matrix run IDs, axis values, output values,
all 28 GET reload checks, both typed cycle samples, and every audited request.
An identical sensitivity replay returned the same case IDs and created zero
new runs for each model.

## Reproducible browser fixture

Smoke test:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 \
  scripts/acceptance/serve_canonical_sensitivity_fixture.py --smoke-test
```

Observed: healthy API, `ready_with_warning`, three editable inputs over three
pages at `limit=1`, current projection reload, and sensitivity replay with zero
new runs.

Interactive preview:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 \
  scripts/acceptance/serve_canonical_sensitivity_fixture.py \
  --host 127.0.0.1 --port 18081 \
  --database /tmp/investiq-canonical-sensitivity-preview.db \
  --fixture-json /tmp/investiq-canonical-sensitivity-preview.json

cd apps/ui
API_PROXY_TARGET=http://127.0.0.1:18081 \
  npm run dev -- --hostname 127.0.0.1 --port 3001
```

Use `browser_setup.local_storage_entries` from the generated fixture JSON,
then open `http://127.0.0.1:3001/sensitivity`.

Final observed browser evidence:

- initial GET-only restore loaded canonical year `2030`, the persisted driver
  selections, scalar cards, explicit baseline/current projection, and the
  returned canonical time series;
- the persisted year restored with `step=0.008`, `valid=true`, and
  `stepMismatch=false`;
- one price change `3 → 3.12` issued exactly one sensitivity POST after the
  debounce and persisted revision
  `00998183-eba5-476e-b1f1-ccee32283f8b`, current run
  `93a00504-6567-519b-bd55-bfa740263090`;
- a page reload restored `3.12` and issued only readiness, input, and
  run-output GETs; the one-way and matrix analysis panels intentionally await
  the next user interaction rather than reconstructing cases with POSTs during
  bootstrap;
- a second tab changed `3.12 → 3.24`; the first tab reconciled through GETs
  only to revision `885e46fd-d7e5-4d0c-97b5-6c8784b2e456`, current run
  `6f52aa2b-8209-59de-ab3b-331ec77b2e1a`;
- a final price change to `3.36` populated the two-driver tornado and 5×5
  two-way matrix from persisted sensitivity cases;
- document client/scroll widths matched at 320, 640, and 1024 CSS-pixel
  viewports: `314/314`, `634/634`, and `1018/1018`.

Tracked visual evidence:

- [Desktop workbench after persisted sensitivity analysis](evidence/canonical-sensitivity-final-desktop-1716.png)
- [320 CSS-pixel mobile workbench after persisted sensitivity analysis](evidence/canonical-sensitivity-final-mobile-320.png)

## Review and boundaries

- Independent final frontend review found no remaining Critical, Important,
  or valid Minor findings after reproducing and then closing stale
  model/graph/run writers with operation-start compare-and-set guards,
  including explicit verification of cleanup and parallel reload paths.
- The acceptance databases are temporary SQLite, not PostgreSQL.
- The fixtures exercise real persisted calculation services, but not live
  workbook upload, extraction/LLM execution, or production data.
- The UI renders the values discovered for each model; it does not fabricate
  the five KPI cards or eight assumptions shown in the reference image.
- Circular and unsupported outputs remain unavailable by design; this slice
  does not broaden the formula-function registry.
- No merge or push was performed.
