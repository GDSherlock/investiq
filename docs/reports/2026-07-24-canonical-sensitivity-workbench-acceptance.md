# Canonical Sensitivity Workbench Acceptance

## Outcome

PASS for the minimum canonical sensitivity workbench slice on
`audit/canonical-output-sensitivity-readiness`.

The implementation range is `851f363..0f2c115`. It reuses persisted,
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
| Reload and cross-tab activity could mix stale model/run state or silently lose a workbench update. | Bootstrap and reconciliation are GET-only. A shared Web Lock serializes calculation-page and sensitivity-page storage writers; a revisioned compare-and-write transaction verifies commit or rollback and exposes failures. |
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

- `61 passed, 0 failed`;
- Next.js compiled and type-checked all 12 pages;
- `/sensitivity`: `17.8 kB`, first load `220 kB`;
- the test runner uses an isolated `mktemp` directory and removes it on exit.

The suite covers stale response rejection, GET-only restore, paginated
canonical discovery, partial/unavailable outputs, exact decimal control state,
same-run concurrent writers, verified rollback, calculation-page/workbench
serialization, and same-baseline override invalidation.

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

### Exact model identities

| Model | Workbook / model / graph | Canonical drivers | Selected output | Baseline / current | Current value |
| --- | --- | --- | --- | --- | --- |
| first | `0c91ff79-059d-4e1e-a09f-2e1cdc9651ea` / `a54630a4-3678-4763-83f1-e02d725237b1` / `5165b498-6a61-5acc-baea-3b469704d06a` | `844af7b8-55ea-5f39-aea8-ffb868d50ac1`, `77035ff8-b61d-54e2-beca-f8402921d09d` | `fa60eae1-7d91-52ec-9da6-5e7511cb8421` | `8662b07b-49db-5d7c-bee5-f6581f3bc29d` / `3aadc199-dc22-5fa2-aed8-39f506a1902a` | `5` |
| second | `80449463-afc3-4437-b65a-84b9db18ecff` / `dd792d12-723d-4f72-8615-8a1fb9c65d0b` / `e42fb513-9f0e-58fa-824f-9143621c519a` | `c82a92f3-3ae5-5582-9dd9-18c744d0e435`, `4c7b7810-29c4-5147-856d-6fa2991cdb04` | `a34d8508-cf1d-5cfa-9fab-f458482a1381` | `16b4abc9-84e5-556f-a5e8-fa09e6e82c90` / `f19868ef-c393-5016-805e-1163272adf67` | `54` |

The selected parameter and output IDs, source mappings, workbook IDs, model
IDs, and graph IDs differ between the two fixtures.

### Exact one-way cases

| Model / driver | Low run → value | High run → value |
| --- | --- | --- |
| first / `844af7b8-55ea-5f39-aea8-ffb868d50ac1` | `7ff412b9-cf5f-51d8-84f7-104e22aa7c23` → `4` | `44f20b8d-e177-5cec-98f7-41bd148b13b9` → `7` |
| first / `77035ff8-b61d-54e2-beca-f8402921d09d` | `4282252c-9979-5792-b477-e1bfd33f2aff` → `4` | `6d5c1fe7-013a-598c-a372-bfb909e24df2` → `7` |
| second / `c82a92f3-3ae5-5582-9dd9-18c744d0e435` | `ae033910-c863-5755-813d-634cc34c56d3` → `45` | `03bb022b-32bf-5792-b6ab-5220a6841ae2` → `63` |
| second / `4c7b7810-29c4-5147-856d-6fa2991cdb04` | `8713aead-248f-5a72-8b5d-4508bdbd2f8b` → `48` | `d53cb522-cdc4-5bd5-a562-3be54cee8632` → `60` |

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

- initial GET-only restore loaded canonical year `2030`, two tornado drivers,
  the scalar cards, explicit baseline/current table, 3×3 two-way matrix, and
  the returned canonical time series;
- the persisted year restored with `step=0.008`, `valid=true`, and
  `stepMismatch=false`;
- one price change `3 → 3.12` issued exactly one sensitivity POST after the
  debounce and persisted revision
  `00998183-eba5-476e-b1f1-ccee32283f8b`, current run
  `93a00504-6567-519b-bd55-bfa740263090`;
- a page reload restored `3.12` and issued only readiness, input, and
  run-output GETs;
- a second tab changed `3.12 → 3.24`; the first tab reconciled through GETs
  only to revision `885e46fd-d7e5-4d0c-97b5-6c8784b2e456`, current run
  `6f52aa2b-8209-59de-ab3b-331ec77b2e1a`;
- document client/scroll widths matched at 320, 640, and 1024 CSS-pixel
  viewports: `314/314`, `634/634`, and `1018/1018`.

## Review and boundaries

- Independent final frontend review found no remaining Critical, Important,
  or valid Minor findings after the shared-lock baseline invalidation fix.
- The acceptance databases are temporary SQLite, not PostgreSQL.
- The fixtures exercise real persisted calculation services, but not live
  workbook upload, extraction/LLM execution, or production data.
- The UI renders the values discovered for each model; it does not fabricate
  the five KPI cards or eight assumptions shown in the reference image.
- Circular and unsupported outputs remain unavailable by design; this slice
  does not broaden the formula-function registry.
- No merge or push was performed.
