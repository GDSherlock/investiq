# Fixed Sensitivity Workbench Design QA

## Evidence

- Reference: `/Users/kingjason/Downloads/localhost_3000_dashboard (1).png`
- Implementation: `docs/reports/evidence/fixed-sensitivity-final-desktop-1722.png`
- Side-by-side comparison: `docs/reports/evidence/fixed-sensitivity-final-comparison.png`
- Responsive captures:
  - `docs/reports/evidence/fixed-sensitivity-final-responsive-1024.png`
  - `docs/reports/evidence/fixed-sensitivity-final-responsive-640.png`
  - `docs/reports/evidence/fixed-sensitivity-final-responsive-320.png`

The browser viewport was 1722 × 1408. Browser chrome is excluded from the 1722 ×
1329 implementation capture. The 3444 × 2816 @2x reference was normalized to
1722 × 1408 and cropped to the implementation capture height for the combined
comparison.

## State and interaction

The final capture uses an isolated fixture with Project IRR, three model-derived
canonical assumptions, and an active persisted sensitivity analysis. Resetting
`First reporting year` moved the workbench through `Recalculating` to the
persisted result with exactly one sensitivity POST. The response contains real
one-way driver runs and 25 persisted top-impact matrix runs. The browser console
was clean.

## Visual comparison history

1. The initial implementation reached 1486 px document height because assumption
   cards and per-cell provenance details were too tall. Control and table density
   were reduced without changing the fixed information hierarchy.
2. The desktop document then fit the 1408 px viewport. Narrow-width root overflow
   was removed at the shell and document-element boundaries.
3. At 320 px, the active matrix still measured 597 px wide because screen-reader
   provenance was retained in normal table layout. Provenance moved to cell
   `title` and `aria-label`; the final document width is 314 px within the 314 px
   client width.
4. Final calculation-contract and diagnostic fixes did not materially change the
   active fixture visual because this fixture has no unavailable controlled-role
   output candidate.

## Required surfaces

- Typography: retained the application font stack, compact hierarchy, tabular
  numeric treatment, and readable unavailable-state detail.
- Spacing: fixed left rail, five-card KPI row, split analysis row, split
  comparison row, and current-assumptions footer follow the reference hierarchy.
- Color: preserved the dark navy shell, warm gold controls, green upside, and red
  downside encoding.
- Copy: assumption labels and units come from canonical model metadata; KPI labels
  remain the fixed platform contract.
- Assets: no decorative assets were introduced; the charts are rendered from
  persisted calculation results.
- Responsive: inspected at 1722, 1024, 640, and 320 px. No page-level horizontal
  overflow was present at any tested width.
- Accessibility: inputs retain labels, matrix cells expose run provenance through
  accessible names and titles, unavailable cards expose typed diagnostic detail,
  and color is not the sole carrier of tornado values.

## Intentional differences and limitations

- The fixture does not contain NPV, Payback, DSCR, or Equity Multiple roles, so
  those fixed cards correctly display `Unavailable`. Controlled-role diagnostic
  rendering is covered by automated tests, but the fixture has absent roles
  rather than unavailable candidates.
- The fixture/application shell does not provide the reference project's scenario
  and persona header metadata, so those controls were not fabricated.
- Persisted `run_id` provenance remains visible even though it is absent from the
  reference image; this is intentional for calculation auditability.

final result: passed

---

# Upload Historical Model Selector Design QA (Design 2)

## Reference and implementation

- Approved source: `/Users/kingjason/.codex/generated_images/019fc6dc-0cee-7f93-9e57-9a93882f7a9a/exec-1c9c3f4d-c66e-4c63-a7c8-78e8c609f4ed.png`
- Verified implementation: `/Users/kingjason/.codex/visualizations/2026/08/03/019fc6dc-0cee-7f93-9e57-9a93882f7a9a/design-2-final-verified.jpg`
- Side-by-side comparison: `/Users/kingjason/.codex/visualizations/2026/08/03/019fc6dc-0cee-7f93-9e57-9a93882f7a9a/design-2-comparison.jpg`
- Browser and viewport: Codex in-app browser, 1487 × 1058 CSS pixels
- Compared state: `Use existing model` selected, history dropdown open, latest model selected

## Visual review

- The approved two-option source switcher, gold selected state, centered heading, bordered history card, model field, expanded option list, primary action, and upload-return link all match the selected direction.
- The expanded list participates in card layout and does not cover the primary action.
- Card and form widths were adjusted against the combined source/implementation image; no cropped controls, horizontal overflow, or broken spacing remained.
- Deliberate data differences: the implementation renders the one real persisted model currently available, its canonical model identifier, timestamp, and baseline status instead of the three illustrative mock rows and invented version labels.
- Deliberate product-context difference: the existing security notice remains beneath the new card.

## Interaction and runtime review

- Source tabs switch between the existing upload flow and the historical-model flow.
- The newest real model is selected by default; opening the picker exposes an accessible listbox and selected option.
- `Continue to analysis` atomically restores workbook/model/graph/baseline identity, clears stale override and sensitivity state, and restores the existing preparation summary.
- A timestamp-bounded API log check after `Continue to analysis` showed only readiness/run GET requests; no upload, prepare, calculation, or sensitivity POST was issued.
- Browser console warnings/errors: none.

## Comparison history

1. Initial browser comparison found that the absolutely positioned list covered the primary action.
2. The list was moved into normal card flow, the approved content width was matched, and latest-model default selection was added.
3. The final combined comparison confirmed the approved hierarchy and interaction state with real persisted data.

final result: passed
