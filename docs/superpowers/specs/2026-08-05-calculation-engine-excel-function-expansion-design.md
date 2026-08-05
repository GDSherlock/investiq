# Calculation Engine Excel Function Expansion Design

**Date:** 2026-08-05
**Status:** Approved approach; written specification awaiting review
**Selected approach:** Engine-only additive increment

## Objective

Add deterministic, Excel-compatible calculation support for the six function
families currently preventing the well-rounded project-finance workbook from
executing:

- `MOD`
- `OR`
- `YEAR`
- `MATCH`
- `XNPV`
- `XIRR`

The increment must make the functions executable through the existing typed
calculation pipeline without changing workbook extraction behavior. Existing
extraction results, formula evidence, canonical entities, semantic bindings,
and persisted v3 calculation artifacts remain unchanged.

## Current Evidence

For `PF_Well_Rounded_Project_Finance_Model.xlsx`, the current v3 compiler
classifies all unsupported formula calls into these six functions:

| Function | Unsupported formula cells |
|---|---:|
| `XIRR` | 58 |
| `XNPV` | 30 |
| `YEAR` | 21 |
| `MOD` | 15 |
| `OR` | 15 |
| `MATCH` | 1 |

The workbook was extracted and materialized successfully. Its UI gaps arise
primarily because unsupported roots block downstream calculation cells. In
particular, the 15 `MOD` cells feed maintenance capex and transitively block a
large portion of cash flow, debt, DSCR, and equity calculations. This is a
calculation-engine compatibility gap, not an extraction-completeness failure.

## Selected Architecture

Use the existing registry-to-compiler-to-evaluator path:

1. add six registry definitions with explicit arity and support metadata;
2. add six evaluator dispatch handlers and focused private helpers;
3. version the new registry and execution behavior as v4; and
4. add semantic, compiler, graph, and real-workbook regression tests.

The compiler already emits generic `function_call` IR and validates function
availability through the registry. Therefore the parser, compiler, IR schema,
dependency graph structure, and persistence schema do not require changes.

The implementation initially keeps the new pure helpers in the existing
evaluator module. A new abstraction or financial-functions module is not
introduced unless a concrete testability or size constraint appears during
implementation.

## Minimal-Change Boundary

### Permitted production changes

- `apps/api/app/calculation_rules/phase2_registry.py`
- `apps/api/app/calculation_rules/evaluator.py`
- `apps/api/app/calculation_rules/phase2_types.py`

Additional changes are limited to calculation-engine tests and this task's
documentation. If implementation evidence shows that another production file
is necessary, work pauses and the design is amended before that file is
changed.

### Explicitly unchanged

- workbook-agent prompts, structured-output contracts, retries, and token
  budgeting;
- workbook partitioning, chunking, extraction, validation, and review status;
- formula observation and source-cell evidence;
- canonical materialization and model semantic bindings;
- calculation IR and compiler syntax;
- database tables, migrations, and stored historical records;
- API response schemas, analysis presentation, and frontend rendering; and
- workbook source bytes or cached formula values.

The implementation must not make unavailable values appear available through
a cached-value fallback, UI default, zero substitution, or relaxed readiness
check.

## Versioning and Compatibility

The function registry and evaluator behavior form a new capability version:

- `PHASE2_FUNCTION_REGISTRY_VERSION`: `calc-functions-v4`
- `PHASE2_ENGINE_VERSION`: `calc-engine-v4`

The unchanged contracts retain their existing versions:

- `PHASE2_IR_VERSION`: `calc-ir-v2`
- `PHASE2_COMPILER_VERSION`: `formula-compiler-v3`
- `PHASE2_SEMANTICS_PROFILE`: `excel-compatible-kpi-v1`

Previously persisted v3 graphs and runs remain immutable and readable. A model
uses the new functions only after a new v4 graph is prepared and calculated
from its existing persisted workbook. Re-extraction is not required.

## Function Semantics

### `MOD(number, divisor)`

- require exactly two scalar arguments;
- coerce arguments through the existing numeric coercion boundary;
- calculate `number - divisor * FLOOR(number / divisor)` so the result has the
  divisor's sign, including negative-input combinations;
- return `#DIV/0!` for a zero divisor;
- propagate typed upstream errors; and
- return `#VALUE!` for values that cannot be numerically coerced.

### `OR(logical1, ...)`

- require at least one argument and preserve the registry's bounded maximum;
- flatten range arguments using the same deterministic path as existing
  aggregation and logical functions;
- short-circuit only after argument evaluation has produced safe typed values;
- use the existing `AND` truth-value/coercion conventions so this increment
  does not silently change established logical semantics;
- ignore blanks and text found inside referenced ranges;
- propagate typed errors encountered before a decisive result under the
  engine's current argument-evaluation contract; and
- return `#VALUE!` when no logical or numeric value can be evaluated.

### `YEAR(serial_number)`

- require one scalar date or numeric serial;
- use the workbook's persisted 1900 or 1904 date system;
- convert through the existing date-serial boundary rather than the host
  machine's timezone or locale;
- preserve Excel's 1900 leap-year compatibility at the year level;
- return `#NUM!` for an out-of-range serial and `#VALUE!` for an invalid value;
  and
- return an integer year without changing the source cell's date formatting.

Locale-dependent free-form date-string parsing is outside this increment.

### `MATCH(lookup_value, lookup_array, [match_type])`

- accept one-dimensional row or column ranges only;
- default `match_type` to `1`;
- support exact (`0`), ascending approximate (`1`), and descending approximate
  (`-1`) modes;
- return a one-based position;
- preserve numeric, text, Boolean, blank, and typed-error distinctions through
  existing scalar normalization;
- perform case-insensitive text matching consistent with Excel;
- support `*`, `?`, and `~` wildcard escaping for text in exact mode;
- return `#N/A` when no qualifying item exists;
- return `#VALUE!` for a multi-area or genuinely two-dimensional lookup array
  and for an invalid match type; and
- do not silently sort or reshape the input range.

Approximate-mode correctness assumes the workbook supplies values in the order
required by Excel. The evaluator does not reorder or certify the input.

### `XNPV(rate, values, dates)`

- require three arguments and equal-length one-dimensional values/date ranges;
- require at least one paired value and date;
- use the first supplied date as the discount origin;
- reject a date earlier than the first date with `#NUM!`;
- truncate date serials to whole days consistently with Excel date arithmetic;
- calculate each contribution using a 365-day year:

  `value / (1 + rate) ^ ((date - first_date) / 365)`;

- return `#NUM!` when the rate or exponent domain has no real finite result;
- return `#VALUE!` for invalid dates or non-numeric cash-flow values; and
- propagate typed upstream errors without using workbook cached results.

### `XIRR(values, dates, [guess])`

- require equal-length one-dimensional values/date ranges;
- require at least one positive and one negative cash flow;
- default `guess` to `0.1` and honor a supplied finite guess;
- share XNPV's date validation and 365-day exponent definition;
- first use bounded Newton iteration from the supplied guess;
- use a deterministic bracketed fallback when Newton cannot safely progress;
- keep the solution domain above `-1`;
- enforce fixed iteration and convergence limits;
- return `#NUM!` when no valid root converges instead of returning the guess or
  a partial iterate; and
- return a dimensionless decimal result without percentage formatting.

The solver must be deterministic for identical typed inputs. Multiple-root
cases remain guess-sensitive, matching the purpose of Excel's optional guess.

## Error and Data-Flow Rules

All six functions consume already-evaluated `ScalarValue` or range values and
return the engine's existing typed result shape. They do not read cells, files,
canonical entities, cached formula results, or database records directly.

Common rules:

- an upstream Excel error remains an Excel error;
- unsupported, blocked, missing, blank, and numeric zero remain distinct;
- non-finite host values are rejected rather than persisted;
- range traversal order follows workbook coordinates;
- calculations are timezone-independent and locale-independent; and
- no function may mutate the execution context or workbook catalog.

## Testing Strategy

Implementation follows RED to GREEN in this order:

1. `MOD`
2. `OR`
3. `YEAR`
4. `MATCH`
5. `XNPV`
6. `XIRR`

Each step first adds a failing semantic test, verifies the expected failure,
implements the smallest handler, and reruns the focused test before proceeding.

### Registry and compiler tests

- every function is registered with the intended arity, range acceptance,
  laziness, volatility, implementation version, and conformance version;
- valid calls compile to existing `function_call` IR;
- invalid arity remains a compile diagnostic;
- unknown functions remain unsupported; and
- no parser or IR snapshot changes occur.

### Evaluator semantic tests

- normal scalar and range results;
- blank, text, Boolean, and typed-error behavior;
- positive and negative `MOD` combinations and zero divisor;
- decisive and empty `OR` inputs;
- 1900 and 1904 `YEAR` date systems and invalid serials;
- all `MATCH` modes, row/column shape, wildcard escaping, no-match, and invalid
  shape/type cases;
- irregular-date `XNPV`, mismatched dimensions, invalid dates, and invalid rate
  domains; and
- `XIRR` default/supplied guesses, convergence, no-solution, mixed-sign
  validation, and deterministic repeatability.

### Regression tests

- all existing calculation-engine focused tests remain green;
- existing v3 identifiers in persisted fixtures remain readable;
- unrelated functions retain their current values and error behavior;
- extraction-focused tests remain green without modified expectations; and
- the backend suite is run after focused tests pass.

## Real-Workbook Acceptance

Use the exact supplied workbook as a read-only integration fixture or local
input. Acceptance requires:

1. the six target function counts compile as supported under v4;
2. no target function remains classified as unsupported;
3. downstream graph nodes previously blocked solely by these functions become
   executable;
4. calculated values are compared with workbook cached values using an
   explicit numeric tolerance and discrepancies are reported, not hidden;
5. the maintenance-capex path at `Operations!B19:P19` and the dependent path at
   `Operations!B40:P40` are exercised;
6. the financing path at `Financing!B8:P14` is exercised; and
7. the summary outputs at `Summary!B14:B20` are exercised.

The acceptance run is initially in-memory and does not update the live database
or current UI model. Rebuilding a runtime container or preparing/calculating a
new persisted v4 run is a separate operational step after code verification.

## Known Separate Issue

The observed DSCR presentation binding mismatch is outside this design. Adding
formula support may make its underlying cells executable, but a UI slot that
requests a different canonical semantic role can remain unavailable. That
binding must be diagnosed and approved independently rather than folded into
this engine change.

## Risks and Controls

- **Date-system drift:** cover both workbook date systems and avoid locale/date
  parsing.
- **Financial solver instability:** use finite bounds, deterministic fallback,
  and explicit no-convergence errors.
- **Approximate MATCH ambiguity:** preserve input ordering and document Excel's
  sorted-input assumption.
- **Regression to extraction:** enforce the permitted-file boundary and run
  extraction regression tests without changing their expectations.
- **Historical-run corruption:** introduce v4 identifiers and never rewrite v3
  artifacts.
- **False UI completion:** require genuine v4 graph execution; do not weaken
  `Unavailable` handling.

## Completion Criteria

This increment is complete only when:

- all six functions are registered and evaluated with the specified semantics;
- focused RED-to-GREEN evidence exists for every function;
- focused and full backend tests pass, or unrelated baseline failures are
  explicitly identified with evidence;
- the exact workbook has no remaining unsupported calls from the six target
  functions;
- workbook acceptance discrepancies are documented;
- the production diff stays inside the permitted engine-only boundary; and
- no extraction, persistence-schema, semantic-binding, API, or UI behavior was
  changed.
