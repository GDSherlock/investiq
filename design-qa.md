# Monte Carlo Layout Design QA

- Source visual truth: `/var/folders/g8/s6phb4wx17z2csq6lmzm8wsm0000gn/T/TemporaryItems/NSIRD_screencaptureui_2wIVpq/Screenshot 2026-08-05 at 14.13.20.png`
- Latest alignment reference: `/var/folders/g8/s6phb4wx17z2csq6lmzm8wsm0000gn/T/TemporaryItems/NSIRD_screencaptureui_tKeghP/Screenshot 2026-08-05 at 14.45.06.png`
- Normalized source: `/tmp/monte-carlo-reference-normalized.png`
- Implementation screenshot: `/tmp/monte-carlo-layout-aligned.png`
- Mobile screenshot: `/tmp/monte-carlo-layout-mobile.png`
- Desktop viewport: requested `1920 x 1291`; captured page pixels `1914 x 1287`
- Mobile viewport: requested `390 x 844`; captured page pixels `384 x 831`
- Source pixels: `2560 x 1722`, normalized to `1920 x 1292` for comparison
- State: persisted baseline model with 30 stochastic inputs and completed Project IRR Monte Carlo result
- Density normalization: source was reduced to 75%; implementation was compared at browser CSS-pixel density

## Full-view comparison

The implementation reproduces the approved three-column composition while preserving the existing InvestIQ navigation shell. At desktop size, the sidebar starts at `x=13` with width `336`; the work area starts at `x=373`. The input column is `490` pixels wide, and the result area uses aligned `402` and `603` pixel tracks.

The Target output and Correlation matrix cards share `y=235`, `height=160`, and `bottom=395`. Project IRR and Project IRR distribution share `y=411`, `height=464`, and `bottom=875`. Sensitivity ranking spans both result tracks from `x=879` to `x=1901`. The stochastic-input card and Sensitivity ranking now both end at `y=1312` (`0px` delta). The input list occupies the remaining `921px` inside its card and ends `17px` above the outer border, matching the card padding.

## Focused-region comparison

- Fonts and typography: existing InvestIQ font stack, weights, uppercase labels, and gold emphasis were retained. Heading and KPI scale follow the source hierarchy.
- Spacing and layout rhythm: the 24-pixel outer gutter, 16-pixel card gaps, shared result-track boundaries, and bounded input/ranking scroll areas match the reference structure.
- Colors and tokens: existing `d-*`, gold, muted, border, success, warning, and error tokens were reused; no parallel palette was introduced.
- Image and chart fidelity: no new raster assets were required. The histogram continues to render persisted bins, so its exact bar silhouette correctly follows real data rather than the illustrative source distribution.
- Copy and content: layout labels match the approved design. Persisted values, diagnostic status, and canonical input order remain source-backed.

## Interaction checks

- Search filters the stochastic list to matching turbine inputs.
- With only two filtered input cards, the scroll region remains `921px` high and the outer card remains `1077px` high, so the content area never collapses or leaves an unfilled lower section.
- Clearing the search restores the full canonical list.
- Open full matrix displays an accessible dialog with the Correlation matrix title and Reset identity action.
- Apply correlations closes the dialog.
- Desktop console returned no warnings or errors.
- Mobile check found no document-level horizontal overflow (`scrollWidth=384`, `clientWidth=384`). The stochastic card remains `652px` high with a `496px` independently scrollable list instead of inheriting the desktop sibling-height technique.

## Comparison history

1. Initial implementation was constrained by the application-wide `1600px` maximum width. This narrowed the reference proportions. Fixed with a Monte Carlo-only large-screen breakout, a `336px` sidebar, a `490px` input track, and aligned `402px / 603px` result tracks.
2. After widening, the stochastic-input card stopped short of the Sensitivity ranking bottom. Fixed by making the desktop grid stretch its children and using a zero intrinsic height plus `min-height: 100%` so the right result column determines the shared row height.
3. The first desktop-only constraint collapsed the list on narrow screens. Fixed with a bounded mobile card height and applying sibling-height alignment only at the `xl` breakpoint.

## Accepted differences

- The existing InvestIQ global navigation remains above the page; it is product-shell infrastructure outside this page-layout change.
- Sidebar KPI precision and histogram shape use persisted application data rather than copying illustrative mock values.
- Correlation status says `Symmetric draft` instead of claiming `Valid` before matrix validation.

No actionable P0, P1, or P2 visual findings remain.

final result: passed
