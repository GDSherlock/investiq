# InvestIQ — Workbook‑Agent Architecture Validation

> **Historical snapshot (2026-07-13):** Azure client and API statements below describe
> the pre-migration baseline. The branch subsequently migrated application services to
> the Azure OpenAI v1 Responses API in commit `5b29eae`; the original analysis is kept
> here for provenance.

**Scope:** validate whether the proposed flow can run inside the *existing* backend:

> Uploaded Excel → local InvestIQ workbook tools → Azure OpenAI function calling →
> multi‑step exploration → LLM‑led open‑ended candidate discovery → deterministic
> validation → traceable persistence.

**Method:** direct inspection of the working tree (identical to `main`, verified by
empty `git diff main..HEAD`), runtime introspection of the workbook fixture and DB,
and a small **isolated proof of concept** (`experiments/workbook_agent_poc/`) that was
actually executed (mock mode). Nothing in production was modified.

**Verdict (see §16):** **Feasible with moderate backend changes.**

---

## A. Current repository diagnosis

### A.1 What the code actually is (README is only partly accurate)

The README claims LangGraph orchestration, an async job runner, and 8 agent workers.
Runtime reality:

| README claim | Reality in code | Evidence |
|---|---|---|
| "IOE LangGraph orchestrator" | Hand‑rolled `dataclass` state machine, **no langgraph dependency** | `apps/orchestrator/engine.py:82` docstring says "LangGraph‑style"; `requirements.txt` has no langgraph/langchain/semantic‑kernel |
| Orchestrator is used | **Dead code.** `OrchestrationEngine`/`register_agent` referenced nowhere outside `engine.py`; container `CMD ["python","-m","apps.orchestrator.engine"]` runs a module with no `__main__` → no‑op | grep across `apps/`,`libs/`,`tests/` returns nothing; `apps/orchestrator/Dockerfile:14` |
| "Async Job Runner" (M7) | **No async jobs.** No Celery/RQ/arq/`BackgroundTasks`/threading. `job_id`s are minted then work runs synchronously or in in‑memory dicts | `apps/api/app/routers/debt_analysis.py:14` `# In-memory job store`; `scenarios.py:738` |
| 8 agent workers | `BaseAgent` subclasses that are plain classes; only `ModelIngestAgent` is meaningful and it just calls the parser directly. `tools` is a decorative `list[str]` | `apps/agents/base.py:21`, `apps/agents/ingest/agent.py:32` |
| Function calling / tools | **None anywhere.** No `tools=`, `tool_calls`, `tool_choice`, `function_call` | grep across `apps/`,`libs/` |

### A.2 Concrete component inventory

| Concern | File / symbol | State |
|---|---|---|
| Excel upload | `apps/api/app/routers/models.py:32` `upload_model()` | Works, **synchronous** (parse in request) |
| File storage | `models.py:47‑52` → `UPLOAD_DIR/{uuid}_{filename}` | Works (2 files present in `uploads/`) |
| Workbook parsing | `libs/tools/excel_parser.py` `ExcelParser` | Works but **rigid template parser** + a bug (§A.3) |
| Parsed JSON | `ExcelParser.parse_all()` → `FinancialModel.parsed_json` (JSON column) | Works |
| Background jobs | — | **Missing** |
| Analysis status | — | **Missing** |
| Azure OpenAI | `apps/api/app/llm_service.py` (chat/report), `vector_service.py` (embeddings) | Works; `AzureOpenAI` + `chat.completions.create`, **no tools** |
| LLM orchestration | `apps/orchestrator/engine.py` | Exists but **unwired / dead** |
| Tool / function‑calling abstraction | — | **Missing** |
| Formula extraction | `ExcelParser.get_formulas(sheet)` `:257` | Partial (whole‑sheet only; no precedents/dependents/named ranges) |
| Assumption extraction | `_parse_assumptions()` + `libs/tools/assumption_mapper.py` | Template‑bound; regex **fixed lexicon** (`CATEGORY_PATTERNS`) |
| Output / series extraction | `_parse_returns()`, `_parse_time_series()` | Template‑bound to fixed rows/cols |
| DB persistence | `apps/api/app/models.py`, `database.py` | SQLAlchemy 2.0; SQLite dev / Postgres prod; JSON columns already used |
| Docker services | `docker-compose.yml` | api, ui, orchestrator(no‑op), postgres(pgvector), redis |
| Worker process | orchestrator container | **No‑op** |
| Env vars | `.env.example`, `.env` (Azure creds **present**) | OK |
| Tests / fixtures | `tests/test_tools.py`, `tests/test_calc_engine.py`, `Financial_Model_Data.xlsx` | Thin; one fixture |

### A.3 Two invariant‑relevant defects in the current parser

1. **Zero‑coercion (blocker for the new invariants).**
   `excel_parser.py:143` — `values.append(cell.value if cell.value is not None else 0)`.
   Empty / missing‑cache cells become `0`. This directly violates *"missing formula
   cache values must never be coerced to zero."* The new tools must not reuse this path.
2. **Rigid template assumptions.** Sheet names are matched against a fixed alias table
   (`_SHEET_ALIASES`), and rows/columns are hard‑coded (e.g. cover label = col B, value =
   col D; assumptions start row 4; years on row 3). Any model that does not match the
   SLNG template is silently mis‑parsed. The new architecture must *discover* structure,
   not assume it.

> Note: `libs/calc_engine/*` already uses the correct "`None`, not 0" convention
> (`tests/test_calc_engine.py:104` zero‑debt‑service → `dscr is None`). The discipline
> exists in the codebase; the parser is the outlier.

### A.4 Workbook fixture reality (drives tool + test design)

`Financial_Model_Data.xlsx`: 11 sheets, **all visible**, **no named ranges**, 32 merged
ranges, **352 formula cells total** — but they are **not where you'd expect**:

| Sheet | non‑empty | formulas | Sheet | non‑empty | formulas |
|---|---|---|---|---|---|
| Cover | 75 | 0 | CashFlows | 94 | 39 |
| Assumptions | 329 | 7 | **Returns** | 117 | **0** |
| Revenue | 253 | 139 | **Sensitivity** | 147 | **0** |
| Capex | 276 | 60 | Checks | 45 | 13 |
| PnL | 253 | 34 | **Dashboard** | 22 | **0** |
| Debt_Schedule | 276 | 60 | | | |

**Key implication:** the *output* sheets (Returns, Sensitivity, Dashboard) are **hard‑coded
pasted values with zero formulas**, while the calc sheets are formula‑driven. A heuristic
like "an output must be a formula cell" would find **zero** outputs here. This is concrete
evidence for the requirement that discovery be evidence‑based and open‑ended, not rule‑fixed.

---

## B. Is "Option 1" feasible in the current architecture?

**Yes — feasible with moderate backend changes.** Every foundational capability already
exists; the missing pieces are *additive*, not a rewrite:

- ✅ `openai==2.44.0` installed → native `tools=[...]` function calling supported.
- ✅ Azure client construction pattern already in `llm_service.py` / `vector_service.py`
  (lazy singleton, env‑driven). Reuse verbatim.
- ✅ FastAPI + SQLAlchemy 2.0 + JSON columns already work on **both** SQLite and Postgres.
- ✅ Upload → disk → parse → `parsed_json` → DB row already works end‑to‑end.
- ✅ **PoC executed locally** proving the tool‑loop + deterministic validation + no‑fabrication
  invariants (§L). 10/10 invariant checks passed.
- ✅ Tool execution stays inside the backend; the model only ever receives tool *results*.
- ⚠️ Missing: async job/status, the function‑calling loop, *general* (non‑template) workbook
  tools, coverage tracking, new persistence tables, new read APIs.
- ⚠️ Must fix the zero‑coercion path and avoid the fixed‑lexicon gate.
- ⚠️ The dead orchestrator is a distraction but **does not block** — bypass it.

No agent framework (LangGraph/Semantic Kernel) is justified by the current code; a plain
`openai` SDK loop is simpler and sufficient.

---

## C. Existing components that can be reused

| Reusable | Where | How used in new flow |
|---|---|---|
| Azure OpenAI client pattern | `llm_service.py:13`, `vector_service.py:18` | Wrap in the function‑calling loop; add `tools=`,`tool_choice="auto"` |
| Upload + storage | `models.py:32` | Keep endpoint; enqueue an analysis job instead of doing everything inline |
| `FinancialModel` + `parsed_json` | `models.py:36` | Store the immutable workbook snapshot / `parsed_json` as the tools' backing store |
| `AuditLog` | `models.py:96` | Basis for append‑only `processing_events` |
| openpyxl double‑load (values + formulas) | `excel_parser.py:31‑37` | Exact mechanism the new tools use (PoC reuses it) |
| `AssumptionMapper` | `assumption_mapper.py` | Demote to an **optional** enrichment signal (category hint), never a gate |
| SQLAlchemy JSON columns + `create_all` | `database.py`, `models.py` | Add new tables the same way (auto‑created on startup) |
| calc_engine "None not 0" discipline | `libs/calc_engine/*` | The convention the parser should have followed |
| JWT auth dependency | `auth.py` `get_current_user` | Gate the new read APIs; scope by `model_id`/owner |

---

## D. Missing components that must be built

1. **Async analysis job + status** (`AnalysisJob` model, enqueue on upload/analyze,
   `GET .../status`). MVP can use FastAPI `BackgroundTasks`; scale later to a worker.
2. **Function‑calling loop** (backend‑owned): schema registry, dispatch, validation,
   iteration/timeout caps, event logging, error handling. (PoC: `agent_loop.py`.)
3. **General workbook tools** — structure‑agnostic, full evidence envelope, no zero‑coercion,
   bounded results. (PoC: `workbook_tools.py`.)
4. **Immutable workbook snapshot store** the tools read from (raw file + versioned JSON).
5. **Deterministic validator** (source/type/structural/semantic/conflict checks).
   (PoC: `validator.py`.)
6. **Importance scoring** from workbook structure + optional LLM signal (§8/§H/§I).
7. **New persistence tables** (§J) and **read APIs** (§K).
8. **Coverage tracker** derived from executed tool calls, not model claims (PoC: `Coverage`).
9. **Fixes:** remove zero‑coercion; make `category`/`canonical_name` optional; ensure the
   lexicon cannot restrict extraction; add file‑size/sheet‑count/range caps.

---

## E. Proposed local workbook tool interface

Design rules for **every** tool: read‑only; bound to one `model_id` → one loaded snapshot;
bounded output; structured `{"error":{code,message}}` on failure (never throw into the loop);
and every returned cell carries the full **evidence envelope**:

```
{ sheet_name, cell, source_reference:"Sheet!A1",
  raw_value, displayed_value, formula, formula_status, data_type,
  python_type, number_format, parse_warnings[] }
```
`formula_status ∈ {static_value, formula_with_cached_value, formula_no_cache}`.
`formula_no_cache` ⇒ `raw_value` stays **null** (never 0).

Recommended **minimal‑but‑sufficient** set (12 tools; some proposed ones merged):

| Tool | Purpose | Key inputs | Output | Max size | Maps to repo? |
|---|---|---|---|---|---|
| `list_sheets` | inventory: name/state/dims (incl. hidden) | — | sheet list | all sheets | ✅ `sheet_names`; PoC `list_sheets` |
| `get_workbook_metadata` | named ranges, external links, defined names, counts | — | metadata | small | ⚠️ new (openpyxl `defined_names`) |
| `inspect_sheet` | dims, formula count, merged ranges, bounded preview | sheet | summary | ≤ preview cap | ✅ PoC `inspect_sheet` |
| `read_range` | bounded range read, evidence envelopes | sheet,range | cells[] | **≤ 500 cells** | ✅ PoC `read_range` |
| `get_cell` | single cell, full envelope | sheet,cell | fact | 1 | ✅ PoC `get_cell` |
| `search_cells` | find labels/values (values or formulas) | query,opts | hits[] | **≤ 100 hits** | ✅ PoC `search_cells` |
| `get_formulas` | formula strings for a range | sheet,range | {coord:formula} | ≤ range cap | ✅ `get_formulas` (widen to range) |
| `get_precedents` / `get_dependents` | 1‑hop formula graph via token parse | sheet,cell | refs[] | bounded | ⚠️ new (regex over formula tokens; note cross‑sheet + `!`) |
| `get_region_summary` | shape of a block (numeric density, header row, types) | sheet,range | summary | small | ⚠️ new |
| `get_candidate_inputs` / `get_candidate_outputs` | heuristic *hints* (non‑formula numerics in input regions / high fan‑out formula cells) — **hints only, never authority** | sheet,opts | refs[] | bounded | ⚠️ new |
| `submit_extraction_result` | terminal; hand structured result to validator | result | ack | — | ✅ PoC `submit_extraction_result` |

Merge guidance: fold `get_merged_ranges` and `get_data_validations` into `inspect_sheet`;
fold `get_named_ranges` into `get_workbook_metadata`. That keeps the surface ~12 tools.
Return **both** raw cells (for validation) and summaries (for cheap navigation) depending on
the tool: `read_range`/`get_cell` → raw; `inspect_sheet`/`get_region_summary` → summary.

---

## F. Proposed Azure OpenAI function‑calling loop

Use **Azure OpenAI Chat Completions with `tools`** (already the API in use; SDK 2.44.0).
Do *not* adopt Responses API / Foundry Agents / LangChain — unjustified by the code.

Loop (backend‑owned; PoC `agent_loop.run_loop`):

1. Build request: system prompt (untrusted‑cell‑content warning) + `tools=TOOL_SCHEMAS` + `tool_choice="auto"`.
2. Receive tool call(s).
3. **Validate tool name + arguments** before executing.
4. Execute the local Python tool **inside the backend** (never in the model).
5. Serialize result to JSON, append as a `tool` message.
6. Repeat until `submit_extraction_result` or a cap.
7. **Iteration cap** (`MAX_ITERS=25`) + **wall‑clock deadline** (`DEADLINE_SECONDS=120`).
8. Persist every step to `processing_events` / `workbook_tool_calls`.
9. Malformed tool call → return structured error to the model (loop continues), record it.
10. Azure failure → retry with backoff (reuse the max‑2 retry idea from `engine.py`), then
    mark the job `failed` with detail; the loop is resumable from persisted messages.

`AzureDriver` in the PoC implements steps 1–6 with the real SDK; `MockModel` implements the
same interface offline. **The live round‑trip is gated behind `--live` and was not executed
in this session** (external call + cost); it therefore remains **unverified**.

---

## G. Proposed LLM exploration workflow

Bounded, multi‑step, never "dump the whole workbook":

1. `list_sheets` + `get_workbook_metadata` (inventory, incl. hidden/veryHidden, named ranges, external links).
2. `inspect_sheet` for **every** sheet (hidden included) → dims, formula density, merged headers, preview.
3. Classify likely sheet purpose from evidence (not from sheet name alone).
4. `read_range` in bounded chunks over interesting regions.
5. `get_formulas` / `get_precedents` / `get_dependents` to trace structure; `search_cells` for labels.
6. Search candidate outputs **openly** — do not rely only on IRR/NPV/DSCR strings (the fixture's
   outputs are label‑driven hard‑coded cells, §A.4).
7. Trace promising hard‑coded cells downstream via dependents.
8. Detect workbook‑native sensitivity tables / scenario columns from structure.
9. Discover open‑ended assumption / parameter / output / series candidates.
10. Synthesize; 11. `submit_extraction_result`; 12. declare uninspected regions.

**Coverage is computed by the backend from executed tool calls** (`Coverage` in PoC), never
trusted from the model: total vs inspected sheets, hidden sheets inspected, ranges read/skipped,
regions summarized, named ranges/formulas inspected, unresolved refs, external links,
tool‑call count, completion status, coverage warnings.

---

## H. Proposed LLM extraction schema

Top level: `workbook_summary, model_type_candidates, sheet_summaries,
all_assumption_candidates, parameter_candidates, output_candidates,
financial_series_candidates, unclassified_inputs, ambiguous_regions, review_candidates,
exploration_coverage, llm_warnings`.

Each **assumption candidate**:
```
candidate_id, original_label (never overwritten), candidate_type,
value, raw_value, displayed_value, unit, period, scenario,
source_references:[{sheet_name, cell|range}],   # REQUIRED, ≥1
formula_status, reasoning_summary, llm_confidence,
category?:null, canonical_name?:null,            # BOTH optional
related_output_candidates:[], evidence:[]
```
Hard constraints (enforced by the validator, not by trust):
- No candidate without a resolvable `source_references` entry.
- The model must **not** generate/estimate/interpolate/recalculate missing values.
- Unknown label + null category + null canonical_name is **valid** (PoC asserts this).

---

## I. Proposed rule‑based validation design

Validator re‑reads the workbook and returns
`{validation_status, validated_value, validation_confidence, validation_warnings,
rejected_claims, structural_evidence, dependency_evidence, importance_components,
review_required}`. Check families:

- **Source:** sheet exists; cell/range valid; `source_reference` parses; submitted value
  matches workbook (numeric `isclose`, else exact string); raw vs displayed not confused;
  `formula_status` correct; **missing cache stays null**; hidden‑sheet refs still traceable.
- **Candidate‑type:** hard‑coded input / formula / label / header / output formula / scenario
  selector / date‑period header / subtotal / duplicate display / unsupported‑ambiguous.
- **Structural:** label↔value adjacency; named‑range membership; input‑region evidence;
  data‑validation evidence; scenario‑column structure; sensitivity‑table usage;
  precedent/dependent evidence; downstream path to outputs; fan‑out; cross‑sheet usage.
- **Semantic (all non‑fatal):** category plausible‑but‑optional; canonical_name optional;
  original_label immutable; **lexicon mismatch must not invalidate**; PF concepts discovered
  from evidence, not a fixed list.
- **Conflict:** duplicate candidates; same cell → incompatible roles; same label → multiple
  values; same value across presentation + calc sheets; value mismatch; invalid unit inference;
  unsupported dependency claims.

PoC `validator.py` already implements Source + the semantic‑optional rules and the
missing‑cache rule; the rest are additive.

---

## J. Proposed persistence changes

Mechanism today: **no Alembic**; tables created by `Base.metadata.create_all` on startup
(`main.py:50`) **plus** raw SQL init scripts (`db/schema_v1.sql`, `schema_v2_vector.sql`)
mounted into the Postgres container. Adding SQLAlchemy models auto‑creates them in both
SQLite and Postgres. ⚠️ **Drift risk:** the raw SQL files are a second source of truth — either
keep them in sync or (recommended) introduce **Alembic** and stop hand‑maintaining SQL.

Reuse `financial_models`. Add (all `String` PK/UUID, `JSON` columns portable to both DBs,
timezone‑aware datetimes as already used):

| Table | Purpose | Key columns | FKs | Indexes | JSON | Status/Version |
|---|---|---|---|---|---|---|
| `analysis_jobs` | one agent run per analyze request | id, model_id, status, error_detail, started_at, finished_at | model_id→financial_models | (model_id), (status) | — | status: queued/running/succeeded/failed/cancelled |
| `processing_events` | append‑only debug log | id, job_id, seq, level, event_type, payload, ts | job_id | (job_id,seq) | payload | — |
| `workbook_snapshots` | immutable versioned workbook metadata/graph | id, model_id, version, sheets_json, formula_graph_json, created_at | model_id | (model_id,version) | sheets, graph | version |
| `workbook_tool_calls` | audit of each tool call | id, job_id, seq, tool_name, args_json, result_summary, ok, ts | job_id | (job_id,seq) | args | ok flag |
| `agent_runs` | LLM run metadata | id, job_id, model_deployment, iterations, tokens, coverage_json, final_extraction_json, status | job_id | (job_id) | coverage, extraction | status |
| `extracted_facts` | validated important facts | id, model_id, candidate_id, original_label, candidate_type, raw_value(JSON), unit, source_reference, formula_status, category?, canonical_name?, importance_json, validation_status | model_id | (model_id), (validation_status) | raw_value, importance | validation_status |
| `financial_series` + `financial_series_points` | validated time series | series: id, model_id, label, unit, source_range; points: series_id, period, raw_value(nullable) | model_id / series_id | (model_id), (series_id,period) | — | — |
| `validation_results` | per‑candidate validator output | id, fact_id/candidate_id, status, validated_value(JSON), warnings_json, rejected_claims_json, evidence_json, review_required | extracted_facts | (candidate_id) | several | status |
| `model_intelligence_snapshots` | versioned rollup for UI | id, model_id, version, summary_json | model_id | (model_id,version) | summary | version |

**Hybrid** (as requested): raw file stays on disk/blob; big/verbose artifacts (workbook
metadata, proposal, formula graph, intelligence) as **versioned JSON snapshots**; important
facts + validation + series as **relational rows**; `processing_events` append‑only.
SQLite/PG compatibility: use the generic `JSON` type (already proven), `String` UUIDs (already
the convention), and avoid PG‑only types except the existing `document_chunks.embedding`
(already handled via raw SQL / pgvector).

---

## K. Proposed API changes (minimal)

All under `/api/v1`, registered like existing routers in `main.py`. Gate with
`get_current_user` and scope every response by `model_id` ownership.

| Endpoint | Exists? | Notes | PoC‑required? |
|---|---|---|---|
| `POST /models/upload` | ✅ `models.py:32` | keep; stop doing full analysis inline — create a job | needed |
| `POST /models/{id}/analyze` | ❌ | enqueue analysis job → `{job_id,status}` | needed |
| `GET /models/{id}/status` | ❌ | job status + progress + failure detail | needed |
| `GET /models/{id}/agent-run` | ❌ | agent_run metadata + coverage | later |
| `GET /models/{id}/tool-calls` | ❌ | paginated tool‑call trace | later |
| `GET /models/{id}/intelligence` | ❌ | latest intelligence snapshot | later |
| `GET /models/{id}/facts` | ~ partial `GET /models/{id}/assumptions` `:181` | replace with validated `extracted_facts` (paginated) | needed |
| `GET /models/{id}/series` | ❌ | validated series + points (paginated) | later |
| `GET /models/{id}/workbook-context` | ~ `GET /models/{id}` returns `parsed_json` | expose snapshot, not raw parse | later |
| `GET /models/{id}/formula-graph` | ❌ | from `workbook_snapshots.formula_graph_json` | later |
| `GET /models/{id}/validation` | ❌ | validation_results (paginated) | needed |

Pagination for `facts`/`series`/`tool-calls` (`limit`/`offset`). Errors: 400 bad range/args,
404 unknown model/sheet, 409 job already running, 422 invalid submit payload, 502 Azure failure.

---

## L. Proof‑of‑concept result (EXECUTED — mock **and** live Azure)

Location: `experiments/workbook_agent_poc/` (isolated; imports nothing from `apps/`; not wired
to upload).

### L.1 Mock mode (deterministic, offline) — 10/10 invariants passed
Run: `.venv_mac/bin/python3 experiments/workbook_agent_poc/run_poc.py`

- Multi‑step tool loop: `list_sheets → inspect_sheet → read_range(B5:F10) → get_cell(D6) →
  get_cell(D10) → submit_extraction_result`; backend executed each tool; coverage tracked.
- Evidence envelope correct: `D10` returned `formula='=D9-D6+1'`, `formula_status=formula_with_cached_value`, cached `20`.
- Valid candidates → **accepted**; fabricated value `9999` at `D6` → **rejected** (actual `2025`
  reported back); bad sheet ref → **rejected**; missing `source_references` → **rejected**.
- Missing formula cache (synthetic `S!B2 = =B1*2`, uncalculated) → `raw_value=None`,
  `formula_status=formula_no_cache`; fabricating `20` → **rejected**; honest `null` →
  `validated_null`, `validated_value=None` (**not coerced to 0**).
- Unknown `category`/`canonical_name` preserved on a valid candidate.

The mock mode is the source of the **rejection** guarantees (a live model won't reliably
fabricate on demand): it proves the validator kills bad candidates.

### L.2 Live Azure OpenAI — VERIFIED
Run: `.venv_mac/bin/python3 experiments/workbook_agent_poc/run_poc.py --live`
(deployment `gpt-5.2`, api‑version `2024-12-01-preview`, real creds from `.env`).

- ✅ **Azure emits tool calls.** The model drove the loop itself:
  `list_sheets → inspect_sheet(Assumptions) → read_range(Assumptions!B3:G74) →
  submit_extraction_result`. Backend executed every tool; results returned as `tool` messages.
- ✅ **Multiple sequential tool calls** and a clean terminal submit.
- ✅ **Structured extraction:** the model submitted **63 assumption candidates**, each with an
  exact `source_references:[{sheet_name, cell}]` and the `raw_value` it read.
- ✅ **Deterministic validation against ground truth: 63/63 validated** — e.g.
  `Financial close year=2025 @ Assumptions!D6`, `Total project life=20 @ D10` (a formula cell,
  `=D9-D6+1`), `Capex incl. contingency=918.0000000000001 @ D14` (raw float preserved, not
  rounded). No fabrication occurred; the validator would have caught it if it had.
- ✅ **Bounded context:** largest single tool result was 328 cells (`read_range` cap 500); the
  whole workbook was never serialized into one prompt.
- ✅ **Coverage is backend‑tracked, not model‑claimed:** the loop recorded
  `inspected_sheets=['Assumptions']` — only **1 of 11** sheets was actually inspected. This is
  the key control: regardless of any claim the model might make, the backend log shows coverage
  was partial (see L.3).

### L.3 What the live run taught us (honest gaps)
1. **First live attempt returned 0 candidates.** Root cause: the `submit_extraction_result`
   tool schema was an unconstrained `{"type":"object"}`, so the model had no shape to fill.
   **Fix applied:** give the terminal tool a concrete JSON schema (candidate object with required
   `source_references` + `raw_value`, optional `category`/`canonical_name`) and strengthen the
   system prompt. Re‑run → 63 validated candidates. *Lesson for production: constrain the submit
   schema; do not rely on prose alone.*
2. **The model under‑explored** (1 sheet). It read the Assumptions sheet and stopped. Production
   must therefore drive coverage from the backend — e.g. refuse to finalize until every sheet is
   `inspect`ed, or feed the coverage record back and prompt for the gaps. **The backend, not the
   model, owns completion.** This validates the §G/§5 requirement to track and enforce coverage.

**Conclusion:** the full principle is now empirically demonstrated end‑to‑end with a real Azure
model — *explore via tools → open‑ended candidate discovery → deterministic verification of every
claim → traceable, backend‑tracked coverage.* Nothing about the Azure integration is now unverified
for this deployment.

---

## M. Risks and unresolved questions

1. **Formula cache dependence.** openpyxl `data_only=True` only returns a cached value if Excel
   saved one. Workbooks last edited by tools (or "formula‑only") yield `None` everywhere →
   correctly null under our rules, but analysis quality drops. Consider a headless recalc
   (LibreOffice) as an optional pre‑step; do **not** silently fabricate.
2. **Precedents/dependents** require formula‑token parsing (incl. cross‑sheet `Sheet!A1`,
   ranges, absolute `$`). Non‑trivial; scope 1‑hop first.
3. ~~Deployment `gpt-5.2` tool‑calling unverified~~ — **RESOLVED** (§L.2): it emits tool calls
   and follows the constrained submit schema. New risk: the model **under‑explores** (stopped
   after 1 sheet); backend must own completion/coverage, not the model.
4. **No job infra** → must add; MVP via `BackgroundTasks`, but multi‑worker/cancel needs Redis
   or a real queue later.
5. **Schema drift** between ORM `create_all` and raw SQL init files (§J).
6. **Prompt injection from cell content** — workbook text is untrusted; must be framed as data.
7. **Cost/latency** of many tool calls per model; enforce caps + caching.
8. **Fixed lexicon** (`AssumptionMapper`) must be demoted to a hint, or it will bias/limit discovery.

---

## N. Phased implementation plan

Each task: goal · files affected · new files · dependencies · expected output · acceptance ·
verification.

### Phase 0 — Fixtures & guardrails (½ day)
- **Goal:** unblock testing of general (non‑template) workbooks; encode invariants as tests.
- **Affected:** `tests/`. **New:** `tests/fixtures/*.xlsx` (hidden sheet, merged headers, named
  range, formula‑no‑cache, scenario columns, duplicate labels, malformed), `tests/test_invariants.py`.
- **Deps:** none. **Output:** failing‑then‑passing invariant tests + fixtures.
- **Acceptance:** tests assert "no value without source", "missing cache≠0", "unknown label kept".
- **Verify:** `.venv_mac/bin/python3 -m pytest tests/ -q`.

### Phase 1 — Workbook tools + validator as a library (2–3 days)
- **Goal:** productionize the PoC tools/validator (no zero‑coercion, bounded, evidence envelope).
- **Affected:** none in prod. **New:** `libs/workbook/tools.py`, `libs/workbook/validator.py`,
  `libs/workbook/graph.py` (precedents/dependents).
- **Deps:** Phase 0. **Output:** importable toolset + validator with unit tests.
- **Acceptance:** all §I Source/type/semantic checks pass on fixtures; `read_range` enforces ≤500 cells.
- **Verify:** `pytest tests/test_workbook_tools.py tests/test_validator.py -q`.

### Phase 2 — Function‑calling loop + mock (2 days)
- **Goal:** backend‑owned loop with caps, event logging, mock + Azure drivers.
- **Affected:** none in prod. **New:** `libs/workbook/agent_loop.py` (promote PoC).
- **Deps:** Phase 1. **Output:** loop runs end‑to‑end on fixtures with mock model.
- **Acceptance:** iteration/timeout caps enforced; malformed calls returned as errors, not crashes.
- **Verify:** `pytest tests/test_agent_loop.py -q`.

### Phase 3 — Persistence (2 days)
- **Goal:** add tables from §J (+ optional Alembic).
- **Affected:** `apps/api/app/models.py`, `database.py`; optionally retire/sync `db/*.sql`.
- **New:** `apps/api/app/models_extraction.py` (or extend `models.py`), optional `alembic/`.
- **Deps:** none. **Output:** tables auto‑created on startup in SQLite + PG.
- **Acceptance:** `create_all` produces new tables; round‑trip a fact + validation row.
- **Verify:** boot API, inspect `sqlite_master`; `pytest tests/test_models.py -q`.

### Phase 4 — Analyze job + status API (2 days)
- **Goal:** `POST /models/{id}/analyze` enqueues a job; `GET /status` reports progress; wire the
  loop to persist events/facts. Keep upload endpoint but move analysis off the request path.
- **Affected:** `apps/api/app/routers/models.py`, `main.py`, `schemas.py`.
- **New:** `apps/api/app/routers/analysis.py`, `apps/api/app/services/analysis_service.py`.
- **Deps:** Phases 1–3. **Output:** async analysis with observable status.
- **Acceptance:** upload → analyze → status transitions queued→running→succeeded; events persisted.
- **Verify:** `curl` upload+analyze+status against `uvicorn`; `pytest tests/test_analysis_api.py -q`.

### Phase 5 — Read APIs + importance (2 days)
- **Goal:** `facts`/`series`/`validation`/`agent-run`/`tool-calls` endpoints; importance scoring.
- **Affected:** `routers/analysis.py`, `schemas.py`. **New:** `libs/workbook/importance.py`.
- **Deps:** Phase 4. **Output:** paginated validated facts with importance components + evidence.
- **Acceptance:** importance preserves component breakdown; not lexicon‑gated.
- **Verify:** `pytest tests/test_facts_api.py tests/test_importance.py -q`.

### Phase 6 — Live Azure validation (½ day, approval‑gated)
- **Goal:** confirm the round‑trip with the real deployment.
- **Affected:** none. **Deps:** Phase 2 + user approval + creds.
- **Output:** trace of real tool calls + validated candidates.
- **Acceptance:** ≥1 real tool call executed; submitted candidates validated; unverified items closed.
- **Verify:** `.venv_mac/bin/python3 experiments/workbook_agent_poc/run_poc.py --live`.

---

## O. Recommended first implementation task

**Phase 0 + the parser‑invariant fix.** Concretely:

1. Add `tests/fixtures/formula_no_cache.xlsx`, `hidden_sheet.xlsx`, `unknown_label.xlsx`.
2. Add `tests/test_invariants.py` asserting: missing formula cache stays `None` (not 0);
   every extracted fact has a valid source reference; unknown labels are preserved; category
   optional.
3. Fix `libs/tools/excel_parser.py:143` to stop coercing `None`→`0` (or route the new tools
   through `libs/workbook/tools.py` and leave the legacy parser for the untouched UI paths).

- **Why first:** it is low‑risk, encodes the non‑negotiable invariants as executable tests,
  fixes the one active correctness bug that contradicts the whole design, and creates the
  fixtures every later phase needs.
- **Acceptance:** `pytest tests/ -q` green; a test proves `data_only` `None` is not turned into 0.
- **Verify:** `.venv_mac/bin/python3 -m pytest tests/ -q`.

---

## Decision (per §16)

**✅ Feasible with moderate backend changes.**

The stack fits (openai 2.44.0 tool calling, FastAPI, SQLAlchemy JSON on SQLite+PG, openpyxl),
the upload/storage/parse/persist spine already works, the Azure client pattern is reusable, and
an executed local PoC proves the tool‑loop + deterministic validation + no‑fabrication core.
The required work is additive — async job/status, the function‑calling loop, general workbook
tools, new tables, and read APIs — plus two fixes (zero‑coercion; demote the fixed lexicon).
No agent framework and no architectural rewrite are warranted. The live‑Azure round‑trip is now
**verified** (§L.2): the real `gpt-5.2` deployment explored the fixture via tools and produced 63
candidates, all 63 confirmed by the deterministic validator against the workbook.
