# Model Extraction Loading Experience Implementation Plan

> **Historical source plan:** This document records the original
> `Frontend_revamp` implementation at `9aef468`. After its merge into the
> canonical calculation branch, the integrated upload flow preserves canonical
> model/workbook IDs and also performs calculation preparation. Its original
> frontend-only and legacy-response constraints are not the current contract.

> **For agentic workers:** Execute inline with strict RED-to-GREEN verification. Keep the approved upload-page scope and do not modify backend code, ESLint configuration, dependencies, or the existing application shell.

**Goal:** Replace the home-page upload form with the approved dark navy-and-gold extraction loading experience while its one existing upload request is pending.

**Architecture:** Keep `uploadModel(file)` as the sole backend request. A pure elapsed-time progress module owns stage selection and the 92% pending cap; a small upload-attempt controller owns success, failure, and cleanup sequencing; focused presentational components render the approved loading state. The home page retains file selection, ID persistence, backend response handling, errors, retry, and its current same-page result view.

**Tech Stack:** Next.js 14, React 18, TypeScript, Tailwind CSS, browser `requestAnimationFrame`, Node's built-in test runner, and the repository's existing pytest suite.

## Global constraints

- Branch/worktree: `Frontend_revamp` at `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj-frontend-revamp`, based on `79fb5efd29ea8508437f7ce289cfa5d5aeedb077`.
- Exactly one call to `uploadModel(file)` per attempt; no polling, SSE, WebSocket, status endpoint, or backend changes.
- Pending progress is browser-only, monotonic, and capped at 92%; success animates to 100% in 750 ms and briefly shows completion.
- The loading view always says `Your model` and never renders the selected filename.
- Failure immediately stops progress, returns to the upload form, shows the original normalized error, and allows retry.
- Do not add a cancel action, animation dependency, test dependency, ESLint configuration, lint script, or dependency change.
- Preserve the existing shell, local-storage keys, backend response object, and same-page result rendering.

## File map

- Create `apps/ui/src/lib/extractionProgress.ts`: stage metadata, exact elapsed-time curve, stage selection, monotonic progress driver, visibility throttling, completion animation, and cleanup.
- Create `apps/ui/src/lib/uploadAttempt.ts`: one-call upload orchestration and success/failure/cleanup callbacks.
- Modify `apps/ui/src/lib/api.ts`: preserve the single upload fetch while surfacing real backend detail through the normalized error.
- Create `apps/ui/src/components/extraction/ExtractionStageStepper.tsx`: responsive five-stage semantic stepper.
- Create `apps/ui/src/components/extraction/WorkbookTransformation.tsx`: workbook-to-structured-model illustration using the repository's existing lightweight inline-SVG convention.
- Create `apps/ui/src/components/extraction/ProcessingActivityList.tsx`: four accessible processing activities with completed/current/future states.
- Create `apps/ui/src/components/extraction/ExtractionLoadingExperience.tsx`: heading, composed two-column panel, progressbar, live status, and information panel.
- Modify `apps/ui/src/app/page.tsx`: start one upload attempt, show loading only while pending/completing/completed, persist the real response IDs, restore the existing form/error/result behavior, and clean up on unmount.
- Modify `apps/ui/src/app/globals.css`: restrained scan/data-flow/stage transitions plus `prefers-reduced-motion` overrides.
- Modify `apps/ui/package.json`: add only a frontend test script; do not change dependencies or lint.
- Create `apps/ui/tests/load-typescript.cjs`: test-only TypeScript/TSX loader using the already installed `typescript` package.
- Create `apps/ui/tests/extractionProgress.test.cjs`: timing boundaries, cap, monotonicity, stages, success completion, visibility behavior, and frame cleanup.
- Create `apps/ui/tests/uploadAttempt.test.cjs`: exactly-one request, pending lifecycle, real result pass-through, real failure pass-through, and cleanup.
- Create `apps/ui/tests/loadingExperience.test.cjs`: render the real component to static markup and assert stage copy, semantic progress, fixed model label, filename exclusion, and completed state.
- Create `tests/test_frontend_extraction_loading_contracts.py`: verify root-page integration, no backend pressure mechanisms, reduced-motion CSS, no cancel label, no API or dependency drift, and required component boundaries.

## RED-to-GREEN sequence

1. Add the Node behavior tests and pytest integration contracts; run them and verify failures are caused by missing production modules/components/integration.
2. Implement the pure progress module; rerun its focused tests to GREEN.
3. Implement the upload-attempt controller; rerun its focused tests to GREEN.
4. Implement the presentational loading components and CSS; rerun rendering and contract tests to GREEN.
5. Integrate `page.tsx`; rerun all new frontend tests and the full repository pytest suite.
6. Run `npx tsc --noEmit`, `npm run build`, and `npm run lint`; record lint's unchanged interactive-setup failure without modifying tooling.
7. Run the local app, exercise pending/success/failure with one intercepted upload request, compare screenshots against the supplied 1600×1000 design, and verify 1440×900, 1024×768, and a narrow viewport.
8. Run `git diff --check`, inspect status/diff for frontend-only scope and generated artifacts, then commit as `feat(frontend): add extraction loading experience`.
