# Phase 1 Calculation Rule Extraction Acceptance Report

Date: 2026-07-16

## Environment

| Item | Evidence |
|---|---|
| Repository root / worktree | `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.claude/worktrees/calculation-rule-extraction-design` |
| Branch | `design/calculation-rule-extraction` |
| Commit | `8fa9342f80340059eeb0a73b36072524db79a6ca` |
| Initial working tree | Clean |
| Active runtime provenance | Compose `working_dir` and `config_files` both point to this linked worktree |
| Active database | PostgreSQL; `postgresql://investiq:***@postgres:5432/investiq` inside Compose (`localhost:5432` from the host) |
| Alembic current | `20260715_0003` |
| Alembic head | `20260715_0003` |

The active API container was healthy and used `USE_SQLITE=false`. The main checkout's legacy `investiq.db` was rejected as an acceptance source because it has no Model Extraction persistence tables. No upload endpoint or LLM Model Extraction call was made.

## Selected upstream model

| Item | Value |
|---|---|
| `model_version_id` | `e27371e8-b2e6-4e2a-bb0d-fa5eb473d819` |
| `workbook_version_id` | `fcfa55d3-f11e-46d5-862c-20f68e1addcf` |
| Filename | `Financial_Model_Data.xlsx` |
| Model status | `materialized` |
| Model validation status | `review_required` |
| Workbook SHA-256 | `2c5550be8f5c67f481fa0e859e323aa504b15225a3741278145a77586f21d96e` |
| Workbook bytes | 42,252 bytes; size and SHA-256 verified through `DatabaseWorkbookStorage` |
| Canonical parameters | 89 |
| Financial series | 13 |
| Financial series values | 260 |

The model and workbook were selected through canonical relational rows. Workbook bytes were loaded through `ModelExtractionReadService` and `DatabaseWorkbookStorage`. `extraction_snapshot_json`, API `final_extraction`, validation JSON, driver/coverage JSON, and LLM traces were not used.

## Pre-run state

This was a fresh deterministic Phase 1 run. All selected model/workbook scoped counts were zero before the first call:

| Table | Before first call |
|---|---:|
| `calculation_rule_extractions` | 0 |
| `workbook_formula_cells` | 0 |
| `executable_formula_rules` | 0 |
| `formula_references` | 0 |
| `formula_canonical_mappings` | 0 |
| `formula_execution_results` | 0 |

## Run result

The public service method `CalculationRuleExtractionService.extract_and_execute(model_version_id, workbook_version_id)` was called directly with the repository `SessionLocal`, `DatabaseWorkbookStorage`, and `ModelExtractionReadService`.

| Item | Value |
|---|---|
| Run ID | `a0a8dcf3-bab4-5d8d-9225-52f8f7792165` |
| Status | `completed_with_warning` |
| Inventory version | `formula-inventory-v1` |
| Compiler version | `formula-compiler-v1` |
| IR version | `calc-ir-v1` |
| Engine version | `calc-engine-v1` |
| Function registry | `function-registry-v1` |
| Semantics profile | `excel-subset-v1` |
| Formula total / parsed | 352 / 352 |
| Supported / unsupported | 351 / 1 |
| Executed / blocked / cycle / execution error | 351 / 0 / 0 / 0 |
| Matched / mismatched / not comparable | 349 / 0 / 2 |
| Warning codes | `unsupported_formula_cells`, `canonical_lineage_incomplete` |

The one non-executable cell was `Checks!D16`, `=COUNTIF(Debt_Schedule!H15:X15,"<1.25")`, with exact reason `unsupported_function:COUNTIF` and no executable IR. This is inside the frozen Phase 1 whitelist boundary.

## Formula inventory

Raw XLSX worksheet XML and a separate openpyxl formula-preserving scan both found exactly 352 explicit formula cells. Their complete address sets agreed with each other and the database.

| Sheet state | Sheets inspected | Formula cells |
|---|---:|---:|
| Visible | 11 | 352 |
| Hidden | 0 | 0 |
| Very hidden | 0 | 0 |

Per-sheet formula counts were: Cover 0, Assumptions 7, Revenue 139, Capex 60, PnL 34, Debt_Schedule 60, CashFlows 39, Returns 0, Sensitivity 0, Checks 13, Dashboard 0.

`workbook_formula_cells = actual workbook formula count = 352`. Address, exact-formula, sheet position/state, data type, and number-format comparisons found zero mismatches. Representative `Assumptions!D10` retained `=D9-D6+1`, cached value `20`, cache status `available`, freshness `recalculation_required`, kind `scalar`, data type `f`, and number format `#,##0`. Missing cached values were never coerced to zero.

## Compiler and calc-ir-v1

| Parse status | Support status | Count |
|---|---|---:|
| `parsed` | `supported` | 351 |
| `parsed` | `unsupported` | 1 |

All 351 supported formulas were parsed and had valid non-null `calc-ir-v1`. The unsupported COUNTIF row retained its exact source and reason and had null IR. There were no external references in this real workbook; focused compiler tests separately proved external references remain evidence-only and never executable/internalized.

Representative persisted IR:

- Arithmetic and range aggregation: `Revenue!J14 =SUM(J8:J11)+J12`, with `function_call(SUM)` over a four-cell `range_reference`, then `binary_operation(add)`.
- Cross-sheet reference: `Checks!E10 =PnL!E7+PnL!E13+Capex!E19`.
- Comparison and IF: `Revenue!L16 =IF(L6=0,0,L14/L6)`, with `comparison(equal)` inside lazy `function_call(IF)`.
- Unsupported function: `Checks!D16 =COUNTIF(...)`, parsed/evidence-retaining, unsupported, null IR.
- Postfix percent: no formula in the real persisted workbook used postfix `%`; focused compiler/evaluator tests covered `=-2^2%` and `=50%` and passed.

For the real IF, static dependencies were `L6`, `L14`, and `L6`. The selected false branch's runtime trace was `L6`, `L14`, and `L6`; the unselected true branch was a literal and therefore added no executed input. Focused lazy-branch tests additionally executed `IF(TRUE,1,1/0)` and `IF(FALSE,1/0,2)` successfully, proving the unselected error branch is not evaluated.

## References and graph behavior

| Reference evidence | Count |
|---|---:|
| Total | 715 |
| Resolved internal | 715 |
| External | 0 |
| Unresolved | 0 |
| Cell | 672 |
| Range | 43 |

All 43 bounded ranges had database row/column cardinalities equal to the cardinality derived from their exact A1 bounds; none was silently truncated. Examples include `Revenue!T8:T11` (4), `Capex!R7:R13` (7), `Debt_Schedule!H15:X15` (17), and `Debt_Schedule!E6:X6` (20).

Persisted evidence reconstructs edges as precedent to dependent, for example `Revenue!T12 -> Revenue!T14`, `Capex!N14 -> Capex!N19`, and cross-sheet `PnL!E7 -> Checks!E10`. No external reference was classified as internal. The real workbook had no cycles and no unsupported-dependent cells; all 351 supported cells executed independently of the unsupported COUNTIF. Focused graph/service tests passed for deterministic cycles, external references, unsupported-dependency blocking, independent supported subgraphs, complete range expansion, and edge-budget rejection without truncation.

## Execution validation

| Execution status | Validation status | Count |
|---|---|---:|
| `executed` | `matched` | 349 |
| `executed` | `not_comparable` | 2 |
| `not_executable` | `execution_error` | 1 |

There were zero mismatches. Every one of the 349 comparable executed formulas has calculated value, cached value, absolute error, relative error, validation status, and cache freshness in `docs/reports/2026-07-16-phase-1-calculation-rule-acceptance-evidence.json`. All 349 matched with absolute and relative error `0.0`.

The two non-comparable rows were:

- `Checks!D10 =CashFlows!E9`: calculated blank versus cached numeric zero.
- `Checks!D13 =Debt_Schedule!X8`: calculated blank versus cached numeric zero.

The unsupported `Checks!D16` had no calculated value and retained cached numeric `15` as evidence. All cached values in this workbook were marked `recalculation_required`; therefore matching is strong validation evidence, not proof of complete current-version Excel compatibility.

## Canonical mappings

| Role | Status | Entity kind | Count |
|---|---|---|---:|
| input | mapped | financial_series | 410 |
| input | mapped | parameter | 42 |
| input | unmapped | — | 255 |
| input | ambiguous | — | 8 |
| output | mapped | financial_series | 113 |
| output | mapped | parameter | 8 |
| output | unmapped | — | 224 |
| output | ambiguous | — | 7 |

Examples:

- Parameter output: `Assumptions!D18 =D15+D16+D17` mapped to parameter `dbb6b61e-9c50-5f3f-86ab-589e4959b4df`.
- Financial-series-value output: `Revenue!J14 =SUM(J8:J11)+J12` mapped to series `82c77076-8daf-5177-b766-ee7b88de7179`, value `09e5cac5-ff27-5a8a-bff2-c6917402a292`.
- Canonical input: an input to `Debt_Schedule!G17 =G15-G16` mapped to series/value `f3a6a0e7-6fc0-5f74-870b-a0232fdcf7fc` / `0da87f76-cb65-5d8a-a041-2910d6fa7721`.
- Unmapped helper: output `Debt_Schedule!G17` was unmapped yet executed successfully.
- Ambiguity: `Capex!C14 =SUM(C7:C13)` and six adjacent outputs were ambiguous but executed; eight input occurrences were also ambiguous.

The mapping rate was `573 / 1067 = 53.701968%`. Incomplete or ambiguous canonical mapping did not gate compilation or execution, as required.

## Six-table evidence

| Table | Scoped count | Representative record |
|---|---:|---|
| `calculation_rule_extractions` | 1 | `a0a8dcf3-bab4-5d8d-9225-52f8f7792165`, `completed_with_warning` |
| `workbook_formula_cells` | 352 | `Assumptions!D10`, `=D9-D6+1`, cached 20 |
| `executable_formula_rules` | 352 | `bff846ea-81ac-5bfb-b7f0-a42820d7036d`, `Revenue!J14`, parsed/supported `calc-ir-v1` |
| `formula_references` | 715 | `Revenue!M6`, cell/internal/resolved |
| `formula_canonical_mappings` | 1067 | `0549526f-989d-53c6-aee2-a24f999f78f6`, input/unmapped with `canonical_mapping_missing` |
| `formula_execution_results` | 352 | `b1c42e7f-67c2-5688-9dbb-bd4ad4014f42`, executed/matched, calculated = cached `9.7830688040000009` |

Required relationships all held:

```text
workbook_formula_cells = actual workbook formula count = 352
executable_formula_rules = workbook_formula_cells = 352
formula_execution_results = one terminal result per formula cell = 352
```

## Idempotency

The exact same default-config request was run twice.

| Evidence | First call | Second call |
|---|---|---|
| Run ID | `a0a8dcf3-bab4-5d8d-9225-52f8f7792165` | same |
| Formula inventory | 352 | 352 |
| Compiled rules | 352 | 352 |
| References | 715 | 715 |
| Mappings | 1067 | 1067 |
| Execution results | 352 | 352 |

The DTOs were equivalent, the deterministic run ID was reused, and every scoped count was unchanged.

The active database contained no second real materialized model for the selected workbook, so the real same-workbook/different-model case was correctly reported as unavailable. An isolated PostgreSQL acceptance test created a second synthetic model for the same immutable workbook and proved shared inventory/rules/references were reused while run/mapping/result rows remained model-scoped.

## Failure isolation

An isolated SQLite acceptance file exercised missing model, missing workbook read contract, model/workbook mismatch, non-materialized model, corrupt workbook bytes, parser/system exception, persistence exception, sanitized failed-run persistence, rollback, reusable session, and retry. Result: `5 passed, 22 warnings`.

The tests proved:

- failures before run creation leave no Phase 1 run;
- parser and persistence failures persist a sanitized `failed` run where required;
- no partial mapping/result rows are exposed after a persistence failure;
- the SQLAlchemy session remains reusable;
- an independent retry reuses the deterministic run ID and succeeds;
- canonical Model Extraction table counts and selected canonical ID fingerprints remain unchanged.

The real active-database run also left the materialized status and parameter/series/value ID fingerprints unchanged.

## PostgreSQL

Isolated database: `postgresql://investiq:***@localhost:5432/investiq_phase1_test` through `TEST_POSTGRES_URL`.

Final clean sequence:

```text
python /tmp/run_phase1_postgres_tests.py
  -> 2 passed, 22 warnings

python /tmp/run_model_extraction_postgres_tests.py
  -> 3 passed, 10 warnings
```

This covered migration to `20260715_0003`, service execution, persistence/reload, idempotency, same-workbook reuse, failure rollback, session reuse, retry, PostgreSQL BYTEA round-trip, SHA dedupe, and Model Extraction canonical rollback.

The first Model Extraction PostgreSQL regression run found a test-isolation defect: `test_postgres_t3_failure_rolls_back_every_canonical_child` removed Model Extraction tables and `alembic_version` but left Phase 1 tables before replaying Alembic, causing `DuplicateTable`. The narrow test-only fix added the six Phase 1 tables to that isolated cleanup list. RED: `1 failed, 2 passed`; GREEN: `3 passed` and the final clean sequence above passed. No production code changed.

## Automated test suite

Interpreter for every command below: `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3`.

| Layer and exact command | Result |
|---|---|
| `.venv_mac/bin/python3 -m pytest -q tests/test_calculation_rule_inventory.py tests/test_calculation_rule_compiler.py tests/test_calculation_rule_graph.py tests/test_calculation_rule_evaluator.py` | 80 passed |
| `.venv_mac/bin/python3 -m pytest -q tests/test_calculation_rule_service.py` | 7 passed, 1 skipped |
| `.venv_mac/bin/python3 -m pytest -q tests/test_calculation_rule_persistence_schema.py` | 8 passed |
| `.venv_mac/bin/python3 -m pytest -q tests/test_workbook_storage.py tests/test_model_extraction_persistence.py tests/test_model_extraction_reload.py tests/test_model_extraction_persistence_schema.py tests/test_model_extraction_lifecycle.py tests/test_experimental_workbook_upload.py` | 72 passed, 3 skipped |
| `.venv_mac/bin/python3 -m pytest -q /tmp/test_phase1_acceptance_failures.py` | 5 passed |
| `.venv_mac/bin/python3 -m pytest -q` | 342 passed, 4 skipped |

All four default-suite skips require an explicit isolated `TEST_POSTGRES_URL`: one Phase 1 service test, two Model Extraction PostgreSQL schema/storage tests, and one Model Extraction PostgreSQL rollback test. All four were rerun against the isolated PostgreSQL test database and passed. Openpyxl `datetime.utcnow()` deprecation warnings and two unrelated Pydantic protected-namespace warnings were reported separately and did not fail tests.

## Restart and prohibited-reader verification

The target API container was restarted. Its `/health` endpoint returned healthy, then a fresh in-container SQLAlchemy session loaded run `a0a8dcf3-bab4-5d8d-9225-52f8f7792165`, status `completed_with_warning`, with 352 cells through `CalculationRuleRepository`. No Model Extraction or formula compilation was rerun.

A boundary scan of `apps/api/app/calculation_rules/**` and `ModelExtractionReadService` found no access to `extraction_snapshot_json`, API `final_extraction`, `validation_results_json`, `driver_meta_json`, or `coverage_json`. Canonical fields named `llm_candidate_alias`, `llm_series_alias`, and `llm_confidence` are relational DTO fields, not LLM traces.

## Remaining limitations

- Only one real persisted financial workbook/model was available; no second real materialized model existed for the same workbook.
- The real workbook contained no hidden/very-hidden formulas, external references, cycles, or postfix-percent formulas. Focused automated tests covered each behavior.
- `COUNTIF` remains unsupported by the intentionally frozen Phase 1 whitelist; the whitelist was not expanded.
- All cached values were marked `recalculation_required`; 349 exact matches are validation evidence, not proof of full current Excel compatibility.
- Two executed blank-versus-cached-zero formulas were not comparable; there were no mismatches.
- Canonical mapping was incomplete and included 15 ambiguous occurrences, but this did not impede execution.
- The default full suite skips four PostgreSQL tests when `TEST_POSTGRES_URL` is absent; all four passed when explicitly run against the isolated PostgreSQL database.

## Decision

The active real workbook satisfied formula inventory, compiler/IR, reference resolution, execution, persistence, idempotency, restart/reload, and Model Extraction isolation requirements. The listed limitations are non-blocking corpus/policy limitations, not correctness or persistence defects.

PASS — Phase 1 is independently accepted and ready for later orchestration integration.
