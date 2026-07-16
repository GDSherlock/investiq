# Calculation Engine Backlog

This document is the concise backlog for calculation-engine capability expansion. The architectural target remains documented in `docs/superpowers/specs/2026-07-15-internal-excel-calculation-engine-target-design.md`; this backlog records implementation status and acceptance gates only.

## Current implemented scope

- Phase 1 preserves the complete workbook formula inventory, `calc-ir-v1` compilation, references/dependencies, deterministic graph construction, baseline execution, cached-value comparison, and persisted reload evidence.
- Phase 2 additively provides `calc-ir-v2`, the accepted `COUNT`, `COUNTA`, and comparison-only `COUNTIF` subset, immutable graph versions/SCC evidence, copied-formula grouping, typed canonical/cell overrides, dirty propagation, compatible-value reuse, deterministic calculation-run identity, and PostgreSQL persistence/reload.
- Existing functions and formula semantics remain deliberately closed and versioned. The current merge does not expand runtime function support.

## Future project-finance function pack

No function in this section is implemented by this cleanup.

1. Valuation and return functions: `NPV`, `XNPV`, `IRR`, `XIRR`.
2. Supporting dates: `YEARFRAC`, `EOMONTH`, `EDATE`.
3. Debt and financing functions: `PV`, `FV`, `PMT`, `IPMT`, `PPMT`, `RATE`, `NPER`.
4. Common supporting functions: `SUMIF`, `SUMIFS`, `INDEX`, `MATCH`, `XLOOKUP`, `IFERROR`, `ROUND`, `ROUNDUP`, `ROUNDDOWN`, `AND`, `OR`.
5. Project-finance helpers that are not native Excel functions, including debt-service and sculpting helpers, require separate versioned adapters and must not be presented as Excel compatibility.

## Required future `IRR` and `XIRR` acceptance

Future implementations must pin the numerical algorithm, initial-guess policy, iteration limit, convergence tolerance, and failure result so identical inputs remain deterministic across retries and supported platforms. Tests must cover:

- ordinary convergent cash-flow series and an explicit caller-supplied guess;
- multiple-root, no-root, all-positive/all-negative, zero-heavy, and near-singular inputs;
- non-convergence at the exact iteration bound and the approved Excel-compatible error code;
- `XIRR` date ordering, duplicate dates, invalid/missing dates, leap days, Excel serial-date conversion, and the approved day-count basis;
- blanks, text, booleans, errors, non-finite numbers, and length mismatches under the versioned coercion/error contract;
- a licensed or independently captured Excel reference corpus with both successful values and errors, checked at explicit absolute/relative tolerances without loosening the current engine tolerances;
- repeat-run identity and persistence tests proving that convergence details do not make results nondeterministic.

## Explicitly deferred general Excel compatibility

- Complete workbook- and sheet-scoped named-range/named-formula execution.
- Excel table structured-reference execution.
- Dynamic arrays, spills, implicit intersection, and array-formula compatibility.
- Iterative convergence for circular references; SCC detection remains evidence only.
- Broader Excel function, coercion, locale, wildcard, error, volatility, and external-workbook compatibility beyond the versioned registry.

Each future increment requires an additive registry/compiler version, focused Excel-compatibility fixtures, deterministic error behavior, migration review where persistence changes, and Phase 1/Phase 2 regression acceptance before activation.
