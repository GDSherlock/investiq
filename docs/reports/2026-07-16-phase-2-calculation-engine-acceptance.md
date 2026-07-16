# Phase 2 Internal Calculation Engine — Test and Acceptance Report

**Decision:** PASS for the scoped Phase 2 core and the chained live-upload acceptance described below.

**Not a claim of full target-state completion:** named/table expression execution, grouped-rule dependency projection, broader Excel function families, volatile/dynamic/external references, iterative calculation, an optional differential oracle, and a public calculation API remain deferred or policy-gated.

## 1. Acceptance identity

| Item | Evidence |
|---|---|
| Date | 2026-07-16 13:58:40 +08 |
| Worktree | `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.claude/worktrees/calculation-rule-extraction-design` |
| Branch | `design/calculation-rule-extraction` |
| Base HEAD | `00037ad23b3ceaefeb05a32c9aedda46748b7619` |
| Python | `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3` |
| Runtime API container | `calculation-rule-extraction-design-api-1` |
| PostgreSQL container | `calculation-rule-extraction-design-postgres-1` |
| Alembic head | `20260716_0004` |
| Real workbook | `Financial_Model_Data.xlsx` |
| Workbook SHA-256 | `2c5550be8f5c67f481fa0e859e323aa504b15225a3741278145a77586f21d96e` |

Docker Compose provenance was verified from the live container label:

```text
working_dir=/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.claude/worktrees/calculation-rule-extraction-design
config_file=/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.claude/worktrees/calculation-rule-extraction-design/docker-compose.yml
```

The host/container SHA-256 values matched for the upload router, workbook-validation adapter, Phase 2 service, and `20260716_0004` migration. This proves the live test used the requested worktree rather than the main checkout.

## 2. Implemented Phase 2 core

The accepted increment is additive to Phase 1:

- versioned `calc-ir-v2`, `formula-compiler-v2`, `calc-engine-v2`, `calc-functions-v2`, and `excel-compatible-v2` contracts;
- a registry that retains Phase 1 functions and additively supports `COUNT`, `COUNTA`, and the accepted `COUNTIF` comparison subset;
- immutable graph versions, complete SCC/component classification, topological layers, dirty propagation, and compatible-value reuse;
- deterministic copied-formula grouping with exact member evidence and unreviewed technical labels;
- typed canonical-parameter and explicit-cell overrides, with formula text and formula-cell overrides rejected;
- eight additive SQLAlchemy/Alembic tables for named-expression, graph, grouping, and calculation-run state;
- internal `compile_workbook` and `calculate_model` service contracts;
- sanitized failure persistence, deterministic run identities, and retry idempotency.

Phase 1 remains the default for existing callers. The v1 envelope, registry behavior, UUID inputs, six Phase 1 table meanings, status values, and previous tests were not replaced.

## 3. TDD and local verification

### 3.1 Baseline

Before Phase 2 implementation:

```text
342 passed, 4 skipped
```

### 3.2 RED → GREEN evidence

| Task | Initial RED | Focused GREEN |
|---|---|---|
| v2 IR/registry/evaluator | 4 failures: Phase 2 registry/contracts absent | 71 selected compiler/evaluator tests passed |
| graph/SCC/dirty propagation | 5 failures: Phase 2 graph absent | 11 graph and Phase 1 graph tests passed |
| business-rule grouping | 3 failures: grouping module absent | 3 grouping tests passed |
| persistence/migration | 2 failures and 2 errors: tables/migration absent | 21 selected schema tests passed, 2 environment skips |
| service/run orchestration | 6 collection errors: service absent | 13 service tests passed, 1 environment skip |
| real workbook `COUNTIF` | `Checks!D16` was 17 instead of cached 15 | focused regression and real-workbook test both passed |

The real-workbook defect came from coercing two blank cells to zero for numeric `COUNTIF("<1.25")`. The fix ignores blank range cells for numeric criteria, consistent with Microsoft’s documented `COUNTIF` behavior that blanks and text values in the range are ignored for numeric counting: <https://support.microsoft.com/en-US/Excel/get-started/use-the-countif-function-in-microsoft-excel>.

### 3.3 Phase 2 focused suite

Command:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q \
  tests/test_calculation_engine_v2_compiler.py \
  tests/test_calculation_engine_v2_graph.py \
  tests/test_calculation_engine_v2_grouping.py \
  tests/test_calculation_engine_v2_persistence_schema.py \
  tests/test_calculation_engine_v2_service.py
```

Result:

```text
24 passed, 1 skipped in 1.23s
```

The skip is the PostgreSQL test when `TEST_POSTGRES_URL` is not supplied to this local-suite command; it was executed separately against an isolated database.

### 3.4 Full repository regression

Command:

```bash
/Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -q
```

Result:

```text
366 passed, 5 skipped in 8.50s
```

All five skips are explicitly PostgreSQL-gated tests. There were no test failures. Existing warnings are primarily openpyxl UTC deprecations and pre-existing Pydantic protected-namespace warnings.

### 3.5 SQLite migration cycle

`test_alembic_upgrades_downgrades_and_reupgrades_sqlite` proved:

1. empty SQLite upgrade to `20260716_0004`;
2. all eight Phase 2 tables present;
3. downgrade to `20260715_0003` removes only the Phase 2 tables while Phase 1 remains;
4. re-upgrade recreates the Phase 2 schema.

### 3.6 Isolated PostgreSQL verification

Database: `investiq_phase2_test_0716`.

Command:

```bash
TEST_POSTGRES_URL=postgresql://investiq:***@localhost:5432/investiq_phase2_test_0716 \
  /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 \
  -m pytest -q -m postgres
```

Result:

```text
5 passed, 366 deselected in 1.95s
```

This covers Alembic upgrade on PostgreSQL, binary workbook persistence, rollback behavior, the Phase 1 calculation service, and a Phase 2 graph/run/value persistence round trip. The pre-existing PostgreSQL cleanup fixtures were updated to drop the eight additive Phase 2 tables before replaying Alembic.

The isolated acceptance database was removed after verification; a final `pg_database` query returned zero matching databases.

### 3.7 Static and diff checks

```text
python -m compileall: PASS
git diff --check: PASS
main checkout: unchanged by this task; its pre-existing untracked report remains untouched
```

## 4. Real-workbook deterministic calculation acceptance

The repository workbook contains 352 formula cells. Phase 2 compiled and executed it without raw Python formula evaluation or network retrieval:

| Metric | Result |
|---|---:|
| Formula inventory | 352 |
| `calc-ir-v2` supported | 352 |
| Executed | 352 |
| Unsupported | 0 |
| Cycles | 0 |
| Blocked | 0 |
| Execution errors | 0 |
| Graph nodes | 352 |
| Graph edges | 946 |
| `Checks!D16` | 15 |

`Checks!D16` is the workbook `COUNTIF` acceptance cell. Its expected cached value and Phase 2 typed result both equal 15.

## 5. Live model-upload and Azure Responses acceptance

### 5.1 Boundary being tested

The live workflow was intentionally chained as:

```text
POST /api/v1/models/upload
  -> Azure Responses workbook-agent extraction
  -> deterministic validation and canonical persistence
  -> returned model_version_id
  -> InternalCalculationEngineService.calculate_model(model_version_id)
```

The Azure call validates the upload/extraction boundary. Phase 2 calculation itself is deterministic and does not call Azure. The upload route does not yet automatically invoke Phase 2 or expose calculation results; the final calculation step was invoked through the internal service in the same API container.

The user explicitly authorized this live call, which sent workbook content to the configured Azure OpenAI endpoint. Endpoint and API-key values are not recorded in this report.

### 5.2 Upload request

```bash
curl --max-time 900 \
  -F file=@Financial_Model_Data.xlsx \
  http://127.0.0.1:8000/api/v1/models/upload
```

Transport result:

| Metric | Result |
|---|---:|
| HTTP status | 200 |
| Curl elapsed | 600.115 seconds |
| API runtime | 599.62 seconds |
| Response size | 1,222,714 bytes |
| Endpoint mode | `experimental_workbook_agent_validation` |
| Azure API | `responses` |
| Deployment | `gpt-5.4-mini` |
| Submitted | true |
| Stop reason | `submitted` |
| Errors | 0 |

Persisted identities:

```text
workbook_version_id=71be6b39-8aea-46b5-befa-bb8dc246a850
model_version_id=d5a5f7ec-d7e8-4a9c-86dc-19474c9661c7
model_status=materialized
validation_status=review_required
```

### 5.3 Azure extraction and coverage

| Metric | Result |
|---|---:|
| Prompt tokens | 2,390,753 |
| Completion tokens | 19,421 |
| Sheets inspected / total | 11 / 11 |
| Fully observed sheets | 11 |
| Logical model tool calls | 26 |
| Internal chunk fetches | 71 |
| Driver observations | 97 |
| Observed bytes | 683,194 |
| Coverage rejections | 0 |
| Duplicate range requests | 0 |
| Submit attempts | 1 |
| Trace events | 97 |
| `trace_truncated` | true |

All sheets were fully observed despite `trace_truncated=true`; the latter is response trace-retention metadata and is retained as a warning rather than treated as complete trace evidence.

Extraction/validation result:

| Metric | Result |
|---|---:|
| Candidate count | 190 |
| Validated | 145 |
| Validated with warning | 41 |
| Reclassified | 3 |
| Review required | 1 |
| Rejected | 0 |
| Response warnings | 117 |
| Canonical parameters persisted | 66 |
| Financial series persisted | 41 |
| Financial-series values persisted | 819 |

Bucket counts in the submitted extraction were: 57 parameter candidates, 6 derived values, 24 outputs, 62 all-assumption candidates, and no unclassified or review-bucket inputs.

### 5.4 Live Phase 2 cold run on the uploaded model

```text
calculation_run_id=3487b679-1173-50fb-9201-6c34050bebbe
graph_version_id=c3d80cfa-aa17-51db-b820-b805269ca200
status=completed
```

| Contract/metric | Result |
|---|---|
| IR | `calc-ir-v2` |
| Compiler | `formula-compiler-v2` |
| Engine | `calc-engine-v2` |
| Registry | `calc-functions-v2` |
| Semantics | `excel-compatible-v2` |
| Formula total/supported/executed | 352 / 352 / 352 |
| Unsupported/cycle/blocked/error | 0 / 0 / 0 / 0 |
| Grouped calculation rules | 17 |
| Warnings | none |
| `Checks!D16` | executed, numeric 15 |

### 5.5 Live typed-override incremental run

Override:

```text
canonical parameter: 6f2f4295-f5eb-5333-bf84-ee91fc734b86
label: Total base capex
source: Assumptions!D12
value: 850 -> 900
```

Result:

```text
base_run_id=3487b679-1173-50fb-9201-6c34050bebbe
calculation_run_id=618681f3-2254-58de-9a6e-513130f70fb8
status=completed
dirty/executed=4
reused=348
```

Exactly four persisted values changed:

| Cell | Baseline | Override |
|---|---:|---:|
| `Assumptions!D14` | 918.00000000000011 | 972.00000000000011 |
| `Assumptions!D52` | 596.70000000000005 | 631.80000000000007 |
| `Assumptions!D53` | 321.30000000000001 | 340.20000000000005 |
| `Checks!D7` | 850 | 900 |

`Checks!D16` was independent of this override and was reused with value 15. Repeating the identical request returned the same calculation run ID and the same 4/348 calculated/reused split.

### 5.6 Live PostgreSQL artifact evidence

For this uploaded model/workbook:

```text
graph versions=1
graph components=352
grouped rules=17
group members=331
calculation runs=2
calculation run values=704
```

All eight Phase 2 tables exist at Alembic head. Current total rows are:

| Table | Rows |
|---|---:|
| `workbook_named_expressions` | 0 |
| `calculation_graph_versions` | 1 |
| `calculation_graph_components` | 352 |
| `grouped_calculation_rules` | 17 |
| `calculation_rule_members` | 331 |
| `calculation_rule_dependencies` | 0 |
| `calculation_runs` | 2 |
| `calculation_run_values` | 704 |

The zero-row named-expression and grouped-dependency tables accurately reflect deferred execution/projection work; their presence must not be read as implemented runtime coverage.

## 6. Findings and residual risks

1. **Azure upload is slow and costly.** This workbook required about ten minutes and 2.39 million prompt tokens. The upload endpoint is synchronous, so it is not yet suitable for latency-sensitive production use without async job orchestration, budgets, and operational telemetry.
2. **Azure extraction is nondeterministic.** Two prior live runs of the same workbook in this worktree database produced 68 and 112 candidates; the accepted run produced 190. Phase 2 calculation results remain deterministic because workbook-cell formulas, not Azure candidate prose, are execution truth.
3. **Canonical review is still required.** The live model materialized successfully but has `validation_status=review_required`, 41 validated-with-warning candidates, one review-required result, and 117 flattened warnings.
4. **Trace retention is incomplete.** Coverage is complete, but the response reported `trace_truncated=true`; this run is not evidence of full production trace retention.
5. **`COUNTIF` is a gated subset.** Numeric/text comparisons used by the repository workbook are supported. Wildcards and locale-sensitive behavior explicitly return `#VALUE!` rather than guessing.
6. **No automatic calculation endpoint yet.** The internal service accepted the returned model ID, but upload does not automatically create a Phase 2 run and there is no public Phase 2 calculate route in this increment.
7. **Deferred target features remain off.** Named/table references, business dependency projection, volatile/dynamic/external functions, iterative cycles, What-If Data Tables, full function-family breadth, and an optional test-only oracle were not enabled.

## 7. Acceptance conclusion

The scoped Phase 2 core passes local, SQLite, isolated PostgreSQL, repository-workbook, live-upload, real-Azure, canonical-persistence, cold-calculation, incremental-recalculation, and idempotency checks. Phase 1 regressions remain green, the real workbook executes 352/352 formulas, and the typed override recomputes only its four dependents while reusing 348 independent values.

**Final decision: PASS**, with the explicit deferred items and production-readiness risks in Section 6.
