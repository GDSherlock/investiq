# Model Extraction Persistence Design

**Date:** 2026-07-15

**Status:** Proposed for review; no persistence implementation exists yet

**Branch:** `design/model-extraction-persistence`
**Base commit:** `1f59fa88e64502f56a919c5ab06959f57be80a92`

## 1. Executive Summary

**Proposed.** Persist each accepted `.xlsx` as one immutable, content-addressed `workbook_versions` row through a backend-owned `WorkbookStorage` interface; V1 uses a database adapter, while the service contract remains portable to Azure Blob or S3. Reuse that workbook row when SHA-256 matches, but create a new `model_versions` row for every Model Extraction execution. Persist canonical parameters, canonical financial series, and aligned series values in relational tables with backend-generated IDs and indexed workbook provenance. Parameters and series remain type-specific tables in V1 but share a `FinancialEntity`-compatible identity and read contract so they can later acquire a common relational supertype without changing stable IDs or consumers.

Keep `extraction_snapshot_json` and validation evidence on the model version strictly as audit and persistence-retry artifacts. They are not a canonical query model. Every downstream module, including future Calculation Rule Extraction, must consume only canonical relational tables through `ModelExtractionReadService`; the downstream read contract does not expose snapshot JSON.

This is the minimum architecture that satisfies the future upstream contract:

```json
{
  "model_version_id": "...",
  "workbook_version_id": "..."
}
```

A future backend task can use those IDs to reload the exact workbook bytes, canonical parameters, canonical series, every aligned value point, and exact source/formula metadata after the request and process have ended. V1 remains synchronous. It adds no queue, calculation-rule table, formula inventory, dependency table, calculation engine, vectorization, or frontend behavior.

The recommended persistence model has five tables:

1. `workbook_versions`
2. `model_versions`
3. `model_parameters`
4. `financial_series`
5. `financial_series_values`

The first item stores the immutable source artifact; the remaining four store one extraction execution and its canonical result. `model_versions` deliberately combines “extraction run” and “model version” for V1: one run produces at most one immutable canonical version. A separate `extraction_runs` entity is deferred until the product needs multiple attempts under one logical model version.

**Observed in code.** The current route is synchronous, has no database dependency, reads the full upload into memory, delegates to the workbook-validation adapter, and returns its response directly. The adapter writes a request-scoped temporary workbook, constructs `WorkbookToolset`, runs extraction, materializes financial series, validates the result, and returns JSON. The temporary directory is then removed.

Evidence:
- `apps/api/app/routers/models.py:upload_model`
- `apps/api/app/workbook_validation.py:run_workbook_validation`
- `tests/test_experimental_workbook_upload.py:test_experimental_route_has_no_database_or_auth_dependency`
- `tests/test_workbook_validation.py:test_temporary_workbook_is_removed_after_success_and_failure`

## 2. Scope

### In scope

**Proposed.** This design covers only:

- immutable uploaded workbook persistence and integrity checking;
- content-addressed workbook identity and filename metadata;
- one backend-owned Model Extraction/model version identity per execution;
- canonical assumption, parameter, selector, and formula-derived parameter persistence;
- canonical financial-series and aligned point persistence;
- period-cell and value-cell provenance;
- exact formula, formula-status, number-format, and data-type persistence where the current toolset exposes them;
- extraction, materialization, and validation lifecycle state;
- synchronous transaction and write orchestration;
- reload/query interfaces for later backend consumers;
- idempotent workbook ingest and persistence retry behavior;
- migration sequencing and SQLite/PostgreSQL compatibility;
- implementation tests.

### Out of scope

**Proposed.** The following are explicitly excluded:

- Calculation Rule Extraction implementation;
- formula inventory, formula dependency, grouped-rule, or AST tables;
- formula execution, Calculation Engine, scenarios, sensitivities, and Monte Carlo;
- async queues, background jobs, or distributed transactions;
- dead `apps/orchestrator` or `apps/agents` code;
- frontend changes;
- legacy analytics repair or migration into the new canonical model;
- vectorization, embeddings, and document chunking;
- unrelated refactoring;
- any code, migration, or API change in this design task.

## 3. Current-State Findings

### 3.1 Current request flow

```mermaid
flowchart LR
    A["POST /api/v1/models/upload"] --> B["Read UploadFile bytes"]
    B --> C["TemporaryDirectory / uploaded.xlsx"]
    C --> D["WorkbookToolset loads value and formula workbooks"]
    D --> E["run_loop and coverage gate"]
    E --> F["final_extraction submission"]
    F --> G["materialize_financial_series mutates final_extraction"]
    G --> H["validate_extraction"]
    H --> I["Synchronous WorkbookValidationResponse JSON"]
    I --> J["TemporaryDirectory removed"]
```

**Observed in code.** `upload_model` accepts `.xlsx` only, rejects empty input, does not inject a SQLAlchemy session or authenticated user, and maps workbook/Azure/validation exceptions to sanitized HTTP errors. It calls `run_workbook_validation(file_bytes, filename)` and returns the resulting dict.

Evidence:
- `apps/api/app/routers/models.py:upload_model`
- `tests/test_experimental_workbook_upload.py:test_unsupported_formats_return_structured_415_without_running_agent`
- `tests/test_experimental_workbook_upload.py:test_empty_xlsx_returns_structured_400_without_running_agent`
- `tests/test_experimental_workbook_upload.py:test_adapter_errors_map_to_sanitized_http_errors`

**Observed in code.** `run_workbook_validation` writes `uploaded.xlsx` beneath `tempfile.TemporaryDirectory`, constructs `WorkbookToolset` from that path, runs `run_loop`, calls `materialize_financial_series`, then calls `validate_extraction`. The response includes driver metadata, submitted/stop state, coverage, mutated `final_extraction`, validation and time-series summaries, detailed validation results, warnings, errors, and trace data. It performs no persistence.

Evidence:
- `apps/api/app/workbook_validation.py:run_workbook_validation`
- `apps/api/app/workbook_validation.py:_driver_meta`
- `apps/api/app/workbook_validation.py:_validation_summary`
- `apps/api/app/workbook_validation.py:_validation_warnings`

**Observed in tests.** Success and invalid-workbook paths both remove the request-scoped temporary directory. The endpoint contract test currently requires the exact response field set and proves that the route has neither `get_db` nor `get_current_user` as a dependency.

Evidence:
- `tests/test_workbook_validation.py:test_temporary_workbook_is_removed_after_success_and_failure`
- `tests/test_experimental_workbook_upload.py:test_success_returns_complete_raw_validation_contract`
- `tests/test_experimental_workbook_upload.py:test_experimental_route_has_no_database_or_auth_dependency`

### 3.2 Workbook identity and source facts

**Observed in code.** `WorkbookToolset` reads the source bytes, loads the workbook twice (`data_only=True` and `data_only=False`), and computes SHA-256 into `workbook_version`. Every cell fact includes sheet, normalized A1 cell, source reference, raw/cached value, exact formula, formula status, external/error flags, openpyxl data type, number format, and parse warnings. Missing or unreliable formula caches remain `None`; they are not coerced to zero.

Evidence:
- `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset.__init__`
- `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset.workbook_version`
- `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset._cell_fact`
- `experiments/workbook_agent_poc/tests/test_validator.py:test_honest_null_for_uncached_formula_not_zero`
- `experiments/workbook_agent_poc/tests/test_validator.py:test_external_ref_value_fabrication_rejected`

**Inferred.** The existing SHA-256 has the correct semantics for content identity, but it is only an in-memory hex string. No database model stores it, and the current response does not expose it as a stable backend ID.

Evidence:
- `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset.__init__`
- `apps/api/app/schemas.py:WorkbookValidationResponse`
- `apps/api/app/models.py:FinancialModel`

### 3.3 Extraction contract and candidate authority

**Observed in code.** The LLM submission schema contains `metadata`, `all_assumption_candidates`, `parameter_candidates`, `derived_value_candidates`, `output_candidates`, `financial_series_candidates`, `financial_series`, `scenario_structures`, `sensitivity_structures`, `unclassified_inputs`, and `review_candidates`. Candidate IDs and series IDs are supplied by the LLM. Candidate source references require sheet and cell. The schema requires only `all_assumption_candidates` and `output_candidates` at the top level.

Evidence:
- `experiments/workbook_agent_poc/extraction_contract.py:SUBMIT_RESULT_SCHEMA`
- `experiments/workbook_agent_poc/extraction_contract.py:_CANDIDATE`
- `experiments/workbook_agent_poc/extraction_contract.py:_FINANCIAL_SERIES`

**Observed in code.** `validate_extraction` deterministically validates candidates from assumption, parameter, derived, output, financial-series-candidate, unclassified, and review buckets. It does not validate the `metadata` bucket. Validation re-reads the cited workbook cell, compares submitted and actual values, reconciles submitted and backend-classified roles, and emits source, role, overall status, validated value, formula status, number format, data type, confidence, warnings, and review flags.

Evidence:
- `experiments/workbook_agent_poc/validator.py:validate_extraction`
- `experiments/workbook_agent_poc/validator.py:validate_candidate`
- `experiments/workbook_agent_poc/roles.py:structural_classification`
- `experiments/workbook_agent_poc/roles.py:reconcile`

**Observed in tests.** The validator rejects fabricated values, reclassifies a correct value submitted with an incompatible role, preserves honest nulls for unavailable formula caches, and rejects missing/bad source references.

Evidence:
- `experiments/workbook_agent_poc/tests/test_validator.py:test_fabricated_value_rejected`
- `experiments/workbook_agent_poc/tests/test_validator.py:test_correct_cell_wrong_role_reclassified`
- `experiments/workbook_agent_poc/tests/test_validator.py:test_missing_source_rejected`
- `experiments/workbook_agent_poc/tests/test_validator.py:test_bad_sheet_reference_rejected`

### 3.4 Backend-owned financial-series materialization

**Observed in code.** The LLM supplies compact series descriptors and complete period/value ranges. `FinancialSeriesMaterializer` is the source of truth for orientation, aligned period points, aligned value points, exact value-cell formulas, formula/cache status, number formats, data types, calculation type, warnings, materialization status, and validation status. `materialize_financial_series` replaces `final_extraction["financial_series"]` with canonical backend materialization while preserving submitted descriptors separately.

Evidence:
- `experiments/workbook_agent_poc/time_series.py:FinancialSeriesMaterializer.materialize`
- `experiments/workbook_agent_poc/time_series.py:FinancialSeriesMaterializer.materialize_collection`
- `experiments/workbook_agent_poc/time_series.py:materialize_financial_series`
- `experiments/workbook_agent_poc/extraction_contract.py:SYSTEM_PROMPT`

**Observed in tests.** Tests prove complete horizontal and vertical source order, backend-owned values instead of LLM arrays, period normalization, exact source cells, formula telemetry, duplicate handling, structured failures, and exclusion of scenario/sensitivity structures from time-series materialization.

Evidence:
- `experiments/workbook_agent_poc/tests/test_financial_series.py:test_descriptor_only_materializes_complete_horizontal_series`
- `experiments/workbook_agent_poc/tests/test_financial_series.py:test_vertical_series_materializes_in_source_order`
- `experiments/workbook_agent_poc/tests/test_financial_series.py:test_legacy_arrays_are_ignored_as_source_of_truth`
- `experiments/workbook_agent_poc/tests/test_financial_series.py:test_formula_series_remains_financial_and_uses_backend_telemetry`
- `experiments/workbook_agent_poc/tests/test_financial_series.py:test_scenario_and_sensitivity_structures_are_never_materialized`

### 3.5 Current database, sessions, serialization, and migrations

**Observed in code.** Local development defaults to SQLite at `./investiq.db`; setting `USE_SQLITE=false` selects the configured PostgreSQL URL. `SessionLocal` uses `autocommit=False` and `autoflush=False`. `get_db` opens and closes a session but does not commit or roll back automatically; routers own explicit commits.

Evidence:
- `apps/api/app/database.py:DATABASE_URL`
- `apps/api/app/database.py:SessionLocal`
- `apps/api/app/database.py:get_db`
- `apps/api/app/routers/models.py:_legacy_upload_model_for_rollback`

**Observed in code.** Existing ORM IDs are application-generated UUID strings. ORM models use generic SQLAlchemy `JSON` and `DateTime`; the raw PostgreSQL schema uses native UUID, JSONB, and TIMESTAMPTZ. This is an existing dialect/schema-definition mismatch that the new schema should not copy accidentally.

Evidence:
- `apps/api/app/models.py:generate_uuid`
- `apps/api/app/models.py:FinancialModel`
- `apps/api/app/models.py:ModelAssumption`
- `db/schema_v1.sql:CREATE TABLE financial_models`
- `db/schema_v1.sql:CREATE TABLE model_assumptions`

**Observed in code.** FastAPI startup calls `Base.metadata.create_all`. Separately, Docker Compose mounts two raw SQL init scripts into a new PostgreSQL data directory. No Alembic configuration, migration environment, or migration dependency is present. `create_all` creates missing tables but cannot safely version or alter an existing production schema.

Evidence:
- `apps/api/app/main.py:lifespan`
- `docker-compose.yml:services.postgres.volumes`
- `db/schema_v1.sql`
- `db/schema_v2_vector.sql`
- `apps/api/requirements.txt`

**Observed in tests.** The current extraction/upload tests do not create a database, assert SQL constraints, or verify persistence/reload behavior. The current route test explicitly asserts the absence of a database dependency.

Evidence:
- `tests/test_experimental_workbook_upload.py:test_experimental_route_has_no_database_or_auth_dependency`
- `tests/test_workbook_validation.py:test_adapter_runs_real_tools_gate_and_validator`
- `tests/test_workbook_validation.py:test_financial_model_data_completes_geometric_coverage_without_rejection`

**Observed in code.** API serialization currently converts UUID and datetime values through a custom JSON response, while Pydantic response schemas coerce UUID-like values to strings.

Evidence:
- `apps/api/app/main.py:UUIDEncoder`
- `apps/api/app/main.py:UUIDJSONResponse`
- `apps/api/app/schemas.py:StrFromUUID`

### 3.6 Existing file and object storage

**Observed in code.** The unregistered legacy upload implementation writes files beneath `UPLOAD_DIR`, stores that path in `financial_models.file_path`, and writes parsed output to `financial_models.parsed_json`. Docker Compose mounts `UPLOAD_DIR=/app/uploads` to a named volume. The active experimental route bypasses this path entirely.

Evidence:
- `apps/api/app/routers/models.py:_legacy_upload_model_for_rollback`
- `apps/api/app/models.py:FinancialModel`
- `docker-compose.yml:services.api.environment`
- `docker-compose.yml:services.api.volumes`

**Observed in code.** Azure deployment scripts provision a Blob Storage account and `models` container, but the API image has no Azure Blob SDK dependency, the API application has no Blob client, and Container App environment variables do not inject storage credentials or a storage endpoint. The production Container App sets `/app/uploads` without mounting durable storage.

Evidence:
- `infra/deploy.sh:Azure Blob Storage (M10)`
- `infra/deploy.sh:Deploying Backend API Container App`
- `infra/deploy.ps1:Azure Blob Storage (M10)`
- `infra/deploy.ps1:Deploying Backend API`
- `apps/api/requirements.txt`

**Inferred.** The local Docker upload volume is durable for that Compose installation, but `/app/uploads` is not a reliable production persistence contract for a scalable Container App with multiple replicas. Blob infrastructure exists nominally, but application integration does not.

Evidence:
- `docker-compose.yml:services.api.volumes`
- `infra/deploy.sh:Deploying Backend API Container App`

## 4. Design Principles

1. **Proposed — immutable source.** A workbook version is identified by bytes, not filename, request, user, or LLM output.
2. **Proposed — backend authority.** Workbook facts, deterministic materialization, and deterministic validation outrank LLM-submitted values and roles.
3. **Proposed — relational canonical model.** Data that must be joined, indexed, reloaded, or referenced by later rules is relational. JSON is reserved for immutable source snapshots, telemetry, warnings, and heterogeneous scalar values.
4. **Proposed — canonical-only downstream consumption.** `extraction_snapshot_json` exists only for audit and same-model persistence retry. It is absent from downstream DTOs and must never be read by Calculation Rule Extraction or any other downstream module.
5. **Proposed — one FinancialEntity evolution seam.** Parameters and series keep focused V1 tables, but share a stable entity ID namespace, an explicit `entity_kind`, and a discriminated `FinancialEntity` read contract. The design must not force future consumers to depend on table-specific IDs.
6. **Proposed — storage port, adapter choice.** Workbook identity/catalog logic depends on `WorkbookStorage`, not on `LargeBinary`, a filesystem path, Azure Blob, or S3. Database BLOB is the V1 adapter, not the service contract.
7. **Proposed — stable backend IDs.** LLM IDs are aliases only. Backend IDs never depend on LLM naming.
8. **Proposed — no long database transaction around the LLM.** The model call runs between short transactions.
9. **Proposed — failure evidence without false readiness.** A failed execution remains auditable but cannot be loaded as a materialized canonical model.
10. **Proposed — retry without duplicate canonical rows.** Workbook ingest is content-idempotent; persistence retry is model-version-idempotent; a new extraction is a new model version.
11. **Proposed — synchronous compatibility.** The current request still completes synchronously and returns the current response plus committed IDs.
12. **Proposed — cross-dialect types.** SQLite development and PostgreSQL production share the same ORM semantics and constraints where both dialects support them.
13. **Proposed — YAGNI.** No formula-rule, dependency, AST, engine, async, vector, frontend, or legacy-analytics design enters this foundation.

## 5. Considered Approaches

| Approach | Complexity | Correctness and auditability | Retryability | Queryability / LLM coupling | Calculation Rule Extraction suitability | Migration cost | Decision |
|---|---:|---|---|---|---|---:|---|
| 1. Persist `final_extraction` JSON only | Low | Preserves a response-shaped snapshot but not an independently enforceable canonical model; source workbook is still lost unless separately added | Can replay JSON, but cannot revalidate against exact bytes | Poor relational lookup; tightly coupled to the evolving LLM/API schema | Insufficient: cannot reopen exact workbook and cell/formula lookup is JSON traversal | Low initially, high when normalized later | Reject |
| 2. Persist canonical relational entities but not workbook bytes | Medium | Canonical rows are queryable, but provenance cannot be independently re-read after request cleanup | Canonical insert retry is possible, extraction or validation replay is not trustworthy without source bytes | Good canonical queryability and lower LLM coupling | Insufficient: future extraction cannot reopen the exact workbook by ID | Medium plus later storage migration | Reject |
| 3. Persist immutable workbook through a storage port plus canonical relational entities and a noncanonical audit snapshot | Medium | Exact source, deterministic canonical rows, and validation evidence survive restart | Workbook dedupe and same-model persistence retry are deterministic; no LLM rerun is needed after snapshot commit | Strong relational queries; JSON snapshot is explicitly unavailable to downstream consumers | Meets the required two-ID upstream contract through canonical-only read interfaces | Medium once | Recommend |

**Proposed.** Approach 3 is the only approach that meets durability, auditability, reloadability, and future upstream requirements without designing any future calculation-rule schema. The additional complexity over Approach 2 is an immutable workbook-storage adapter plus a small catalog repository; it eliminates a much larger later migration and prevents source/canonical drift. The storage port prevents this V1 medium choice from becoming a domain dependency.

## 6. Recommended Architecture

### 6.1 Logical components

```mermaid
flowchart LR
    A["Upload router"] --> B["ModelExtractionPersistenceService"]
    B --> C["WorkbookVersionRepository"]
    B --> S["WorkbookStorage port"]
    S --> SA["DatabaseWorkbookStorage adapter (V1)"]
    B --> D["Current synchronous extraction pipeline"]
    D --> E["Backend materializer and validator"]
    B --> F["ModelExtractionRepository"]
    C --> G[("Application database")]
    SA --> G
    F --> G
    H["Future Calculation Rule Extraction"] --> I["ModelExtractionReadService"]
    I --> S
    I --> F
    B -. "audit / persistence retry only" .-> J["Snapshot access"]
    J --> F
```

**Proposed.** The router remains an HTTP adapter. A new backend service owns lifecycle and transaction orchestration. Repositories own database mapping, not extraction decisions. The current workbook-agent, materializer, and validator remain the domain producers. A storage port isolates workbook bytes from their V1 database adapter. The read service exposes typed canonical methods and enforces “materialized only” readiness; it has no snapshot method. Snapshot access is a private persistence/audit path and is not injected into future Calculation Rule Extraction.

### 6.2 Entity relationship diagram

```mermaid
erDiagram
    WORKBOOK_VERSIONS ||--o{ MODEL_VERSIONS : "source for"
    MODEL_VERSIONS ||--o{ MODEL_PARAMETERS : "contains"
    MODEL_VERSIONS ||--o{ FINANCIAL_SERIES : "contains"
    FINANCIAL_SERIES ||--o{ FINANCIAL_SERIES_VALUES : "contains"

    WORKBOOK_VERSIONS {
        uuid id PK
        char64 sha256 UK
        varchar original_filename
        varchar storage_type
        varchar storage_ref UK
        blob content_bytes "nullable outside DB adapter"
        bigint file_size
        timestamptz created_at
    }
    MODEL_VERSIONS {
        uuid id PK
        uuid workbook_version_id FK
        varchar upload_filename
        varchar status
        varchar validation_status
        boolean submitted
        json extraction_snapshot_json
        json validation_results_json
        timestamptz created_at
        timestamptz completed_at
    }
    MODEL_PARAMETERS {
        uuid id PK
        uuid model_version_id FK
        varchar entity_kind
        varchar llm_candidate_alias
        varchar validated_role
        json validated_value_json
        varchar source_sheet
        varchar source_cell
        text exact_formula
        varchar formula_status
        varchar validation_status
    }
    FINANCIAL_SERIES {
        uuid id PK
        uuid model_version_id FK
        varchar entity_kind
        varchar llm_series_alias
        varchar label
        varchar calculation_type
        varchar period_source_range
        varchar value_source_range
        varchar materialization_status
        varchar validation_status
    }
    FINANCIAL_SERIES_VALUES {
        uuid id PK
        uuid financial_series_id FK
        integer period_index
        json raw_period_label_json
        json value_json
        varchar period_source_cell
        varchar value_source_cell
        text exact_formula
        varchar formula_status
    }
```

### 6.3 `FinancialEntity` evolution seam

**Proposed.** Do not add a sixth `financial_entities` table in V1 merely to host four common columns. Do not leave parameters and series unrelated either. Use the middle option:

| Option | Trade-off | Decision |
|---|---|---|
| Add `financial_entities` supertype now | Strong relational unification, but adds shared-primary-key inheritance, more writes, and lifecycle decisions before a real cross-type consumer exists | Defer |
| Keep type-specific tables with a common identity/read contract | Preserves simple writes now and lets a future supertype reuse the same IDs and DTO contract | Recommend |
| Keep fully independent tables and APIs | Lowest immediate effort, but hard-codes table-specific references into future consumers and makes unification a breaking migration | Reject |

V1 therefore requires both canonical tables to carry the same core contract: globally unique backend `id`, `model_version_id`, checked `entity_kind`, human label, and typed provenance. `FinancialEntityRef(id, model_version_id, entity_kind, label)` is a domain DTO/protocol, not a V1 table. `list_financial_entities` and source-cell resolution return a discriminated union built from the two relational tables.

A future rule-oriented module can therefore consume `FinancialEntityRef` without treating `model_parameters` and `financial_series` as unrelated ID domains. If that module requires one database foreign key across both kinds, introduce the shared-primary-key `financial_entities` supertype first. This specification does not define that future rule schema or foreign key.

If real consumers later justify a relational supertype, add `financial_entities(id, model_version_id, entity_kind, label, ...)`, bulk-copy existing IDs and common fields, and turn each existing child PK into a PK/FK to that row. Stable IDs and the `FinancialEntityRef` consumer contract do not change. This is an explicit migration seam, not an implementation of future Calculation Rule Extraction.

### 6.4 Why no `extraction_runs` table in V1

**Proposed.** One `model_versions` row represents exactly one Model Extraction execution and at most one canonical result. A new extraction retry creates a new model version. A persistence-only retry reuses the same model version and its saved extraction snapshot. This preserves attempt history without a second identity layer. Add a separate run table only if a later requirement needs multiple extraction attempts to compete for or replace one logical model version.

### 6.5 Relationship to legacy `financial_models`

**Observed in code.** Legacy `FinancialModel` owns a file path, response-shaped `parsed_json`, health score, investment relationship, assumptions, scenarios, and document chunks. The active experimental extraction route does not create or use it.

Evidence:
- `apps/api/app/models.py:FinancialModel`
- `apps/api/app/models.py:ModelAssumption`
- `apps/api/app/routers/models.py:_legacy_upload_model_for_rollback`
- `tests/test_experimental_workbook_upload.py:test_experimental_route_has_no_database_or_auth_dependency`

**Proposed.** Do not reuse, extend, or foreign-key `financial_models` in V1. The ownership and lifecycle are disjoint, and reusing it would couple the new canonical model to `parsed_json`, investment creation, vectorization, and legacy file paths. If product ownership later needs a logical link, add an optional mapping after both sides have an explicit contract; do not make that mapping part of this foundation.

## 7. Component Boundaries

| Component | Owns | Does not own |
|---|---|---|
| Upload router | format/empty checks, HTTP errors, response schema | transactions, ID generation, canonical mapping |
| `ModelExtractionPersistenceService` | lifecycle, short transaction boundaries, pipeline invocation, snapshot commit, canonical write orchestration | workbook parsing rules, SQL query details |
| `WorkbookVersionRepository` | workbook identity/catalog metadata, SHA dedupe, storage locator persistence | byte I/O, extraction/model status |
| `WorkbookStorage` port | immutable put/load/verify contract over opaque storage locations | workbook identity, model status, provider-specific policy |
| `DatabaseWorkbookStorage` adapter | V1 `LargeBinary` persistence through the port and caller-owned transaction | domain orchestration, Azure/S3 behavior |
| Current workbook-agent | exploration and LLM submission | canonical IDs, database state |
| Current backend materializer | canonical period/value axes and formula telemetry | storage and transactions |
| Current backend validator | source/role/value validation outcomes | storage and API serialization |
| `ModelExtractionRepository` | model version, parameters, series, values, idempotent writes | LLM invocation and workbook interpretation policy |
| `ModelExtractionReadService` | ready-state enforcement and typed canonical/`FinancialEntity` reload contract | snapshot JSON, Calculation Rule Extraction logic |
| Private snapshot access | authorized audit reads and persistence-only retry input | any downstream canonical query or Calculation Rule Extraction input |

**Proposed.** Repository methods receive a caller-owned SQLAlchemy session. The service opens/commits/rolls back transaction units. Repository methods use `flush` when IDs or constraints must be observed but never call `commit`. This is stricter than current route-level commit conventions and is required to make the canonical write atomic.

## 8. Data Ownership and Sources of Truth

| Artifact / field | Source of truth | Persistence rule |
|---|---|---|
| Workbook bytes, SHA-256, file size | Workbook ingest/backend | Immutable `workbook_versions` |
| Workbook storage medium/location | `WorkbookStorage` adapter selected by backend configuration | `storage_type` plus opaque `storage_ref`; never interpreted by downstream consumers |
| First-seen original filename | User upload metadata | Immutable metadata on workbook version |
| Filename for a particular execution | User upload metadata | `model_versions.upload_filename` |
| LLM candidate/series ID | LLM | Alias only; never PK/FK |
| Candidate label, category, canonical name, unit, scenario, period, reasoning, confidence | LLM unless independently available | Store as attributed submission metadata, never silently upgrade to backend fact |
| Raw and exact cached cell value | Workbook via `WorkbookToolset` | Backend fact; persist on canonical entity/value |
| Exact formula, formula status, number format, data type | Workbook via `WorkbookToolset` | Backend fact; persist relationally where available |
| Validated role/value/status/confidence | Deterministic validator | Canonical parameter authority |
| Series periods, values, source cells, orientation, calculation type, formula pattern | Deterministic materializer | Canonical series/value authority |
| Coverage and driver metadata | Runtime/driver | Model-version JSON telemetry |
| Validation summary/results | Deterministic validator/materializer | Filtered model-version audit JSON plus relational status on canonical rows; omit `dependency_evidence` from the durable projection |
| Extraction snapshot | Model Extraction persistence service | Audit and same-model persistence retry only; never a downstream input or canonical read DTO field |
| `metadata` candidates | LLM; currently not deterministically validated | Snapshot only in V1 |
| Validated output candidates that remain output-family | LLM plus validator | Snapshot/validation evidence only in V1; not canonical parameters |
| Scenario/sensitivity structures | LLM | Snapshot only; explicitly not materialized as series |
| Future formula inventory/dependencies/rules | Future Calculation Rule Extraction | Not present in this schema |

### 8.1 Canonical parameter eligibility

**Proposed.** Build a candidate pool from `all_assumption_candidates`, `parameter_candidates`, `derived_value_candidates`, `output_candidates`, `unclassified_inputs`, and `review_candidates`, matched to deterministic validation results. Persist one canonical `model_parameters` row only when:

1. the source reference resolves to a real workbook cell;
2. source validation is not `rejected`;
3. the backend `validated_role` family is assumption, derived, or selector;
4. canonicalization finds no unresolved conflict for the same source cell.

This makes `parameter_candidates` and `all_assumption_candidates` inputs to canonicalization rather than authoritative database categories. It also permits a misbucketed candidate to become canonical only when backend validation reclassifies it into an eligible family. A candidate validated as output or metadata remains in the extraction/validation snapshots and is not a parameter. Formula-derived values with unavailable caches remain canonical with `validated_value_json = null`, exact formula, and formula status.

**Observed in code.** Role families distinguish assumption, output, derived, metadata, selector, series, and external roles. Formula cells can be reclassified away from assumptions, and unavailable formula values remain null.

Evidence:
- `experiments/workbook_agent_poc/roles.py:family`
- `experiments/workbook_agent_poc/roles.py:reconcile`
- `experiments/workbook_agent_poc/validator.py:validate_candidate`

### 8.2 Duplicate candidate resolution

**Proposed.** Normalize source sheet names exactly as workbook titles and cells as uppercase A1 addresses. Group eligible candidates by `(model_version_id, source_sheet, source_cell)`. Prefer a non-rejected deterministic result; then prefer a more specific input bucket over the umbrella bucket. If two surviving candidates disagree on backend-validated role or validated value, fail canonical persistence with `CANONICAL_SOURCE_CONFLICT` rather than guessing. Preserve the selected LLM ID as `llm_candidate_alias`; every original submission remains in `extraction_snapshot_json`.

## 9. Persistence Data Model

### 9.1 Actual V1 tables

**Proposed.** V1 creates only the five tables shown in the ERD. It does not create a generic artifact table, polymorphic provenance table, extraction-attempt table, model parent table, `financial_entities` supertype table, output table, metadata table, formula table, dependency table, or audit-event table. The `FinancialEntity` seam is a shared identity/read contract in V1, with a documented no-ID-change path to a future supertype table.

### 9.2 Backend-generated ID strategy

**Proposed.** Generate IDs in the backend before insert:

- `workbook_versions.id`: UUIDv4 when a SHA-256 is first seen; reused thereafter.
- `model_versions.id`: UUIDv4 for each extraction execution.
- `model_parameters.id`: UUIDv5 under the model-version namespace from `financial_entity|parameter|source_sheet|source_cell`.
- `financial_series.id`: UUIDv5 under the model-version namespace from `financial_entity|financial_series|<normalized period/value ranges plus scenario/entity/unit/currency context>`.
- `financial_series_values.id`: UUIDv5 under the financial-series namespace from `period_index`.

The two entity keys share one model-version-scoped `FinancialEntityIdFactory` and an explicit kind prefix. This makes persistence-only retries generate the same IDs without trusting LLM IDs, prevents cross-type key collisions, and preserves IDs if a common `financial_entities` table is later added. UUIDv4 model IDs keep distinct extraction executions distinct even for identical workbook bytes.

### 9.3 Canonical JSON boundaries

**Proposed.** JSON is permitted for storage only in these bounded roles:

- the immutable extraction snapshot used for audit and persistence retry;
- driver, coverage, summary, and detailed validation evidence;
- heterogeneous scalar values (`raw_value_json`, `validated_value_json`, `raw_period_label_json`, `value_json`);
- aliases, warnings, and formula-pattern telemetry.

All JSON uses an explicit JSON-safe scalar codec: UUIDs become strings; dates and datetimes become ISO-8601 strings; numeric, string, boolean, and null values retain their JSON scalar types. This matches the current HTTP serializer and avoids relying on SQLAlchemy's JSON type to serialize Python date objects implicitly.

JSON is not permitted as the only storage for parameters, series, point order, source cells, exact formulas, statuses, or foreign-key relationships. `extraction_snapshot_json` and `validation_results_json` are never projected by `ModelExtractionReadService`; only the persistence retry path and an explicitly authorized audit path may read them. A downstream module may not parse them as a fallback when a canonical field is absent. No JSON containment index is required in V1.

## 10. Field-Level Schema Decisions

Classification values are **Required for V1**, **Optional for V1**, **Derived — do not store**, and **Deferred**. “Nullable” describes the SQL column, not whether the field is expected after a successful run.

### 10.1 `workbook_versions`

| Field | Type / nullable | Classification | Authority and rationale |
|---|---|---|---|
| `id` | UUID, not null, PK | Required for V1 | Backend UUIDv4; stable workbook identifier returned to consumers |
| `sha256` | CHAR(64), not null | Required for V1 | Backend digest of exact bytes; content identity and unique key |
| `original_filename` | VARCHAR(255), not null | Required for V1 | First accepted filename only; immutable metadata, not identity |
| `storage_type` | VARCHAR(32), not null | Required for V1 | Adapter discriminator; V1 writes `database`, with future adapters such as `azure_blob` or `s3` added deliberately |
| `storage_ref` | VARCHAR(512), not null | Required for V1 | Opaque content-addressed key such as `workbooks/sha256/<digest>.xlsx`; consumers must not parse it |
| `content_bytes` | LargeBinary, nullable | Required for V1 | Populated by `DatabaseWorkbookStorage`; nullable schema seam permits a verified future object-store migration without changing catalog identity |
| `file_size` | BigInteger, not null | Required for V1 | Backend byte length; integrity and operational guard |
| `created_at` | timezone-aware DateTime, not null | Required for V1 | Backend UTC first-seen timestamp |

### 10.2 `model_versions`

| Field | Type / nullable | Classification | Authority and rationale |
|---|---|---|---|
| `id` | UUID, not null, PK | Required for V1 | Backend UUIDv4 per extraction execution |
| `workbook_version_id` | UUID, not null, FK | Required for V1 | Exact immutable source workbook |
| `upload_filename` | VARCHAR(255), not null | Required for V1 | Filename supplied for this execution; preserves aliases without mutating workbook row |
| `status` | VARCHAR(32), not null | Required for V1 | Lifecycle state: `extracting`, `extracted`, `materialized`, `extraction_failed`, `persistence_failed` |
| `validation_status` | VARCHAR(32), not null | Required for V1 | Aggregate readiness: `not_run`, `validated`, `validated_with_warning`, `review_required`, `rejected` |
| `submitted` | Boolean, not null | Required for V1 | Backend loop result |
| `stop_reason` | VARCHAR(100), nullable | Optional for V1 | Backend loop stop reason; expected after pipeline attempt |
| `extraction_snapshot_json` | JSON, nullable | Required for V1 | Saved after successful pipeline; accessible only to audit and persistence retry, never canonical/downstream reads |
| `driver_meta_json` | JSON, nullable | Required for V1 | Driver API/deployment/token metadata currently returned |
| `coverage_json` | JSON, nullable | Required for V1 | Backend coverage evidence currently returned |
| `validation_summary_json` | JSON, nullable | Required for V1 | Candidate validation counts |
| `time_series_summary_json` | JSON, nullable | Required for V1 | Materialization counts and warnings |
| `validation_results_json` | JSON, nullable | Required for V1 | Detailed rejected/noncanonical evidence and persistence retry audit, filtered to exclude formula `dependency_evidence` |
| `error_code` | VARCHAR(100), nullable | Optional for V1 | Sanitized stable failure code, not raw exception text |
| `error_message` | Text, nullable | Optional for V1 | Sanitized operational message; secrets and workbook contents excluded |
| `created_at` | timezone-aware DateTime, not null | Required for V1 | Backend UTC row creation |
| `extracted_at` | timezone-aware DateTime, nullable | Required for V1 | Set when the snapshot transaction commits |
| `completed_at` | timezone-aware DateTime, nullable | Required for V1 | Set on materialized or terminal failure state |
| `runtime_seconds` | no column | Derived — do not store | Current response can retain monotonic runtime; wall-clock timestamps are persisted |
| `trace_json` | no column | Deferred | Detailed agent trace is not required for the minimum durable upstream contract |
| `legacy_financial_model_id` | no column | Deferred | No V1 ownership link to legacy analytics |

### 10.3 `model_parameters`

| Field | Type / nullable | Classification | Authority and rationale |
|---|---|---|---|
| `id` | UUID, not null, PK | Required for V1 | Backend deterministic UUIDv5; never LLM ID |
| `model_version_id` | UUID, not null, FK | Required for V1 | Canonical model owner |
| `entity_kind` | VARCHAR(32), not null | Required for V1 | Checked constant `parameter`; discriminates the shared `FinancialEntity` contract and future supertype migration |
| `llm_candidate_alias` | VARCHAR(255), nullable | Optional for V1 | LLM candidate ID retained as trace alias only |
| `source_bucket` | VARCHAR(64), not null | Required for V1 | Submitted bucket for audit; not canonical role |
| `label` | Text, not null | Required for V1 | Original submitted label, preserved verbatim |
| `category` | VARCHAR(100), nullable | Optional for V1 | LLM-attributed metadata |
| `canonical_name` | VARCHAR(255), nullable | Optional for V1 | LLM-attributed name; not backend authority |
| `submitted_role` | VARCHAR(64), not null | Required for V1 | LLM role, defaulting to explicit `unknown` when absent |
| `validated_role` | VARCHAR(64), not null | Required for V1 | Deterministic validator role; canonical authority |
| `raw_value_json` | JSON scalar, nullable | Required for V1 | LLM-submitted heterogeneous scalar retained for audit |
| `validated_value_json` | JSON scalar, nullable | Required for V1 | Workbook/validator value; null is meaningful for unavailable formulas |
| `unit` | VARCHAR(100), nullable | Optional for V1 | LLM metadata; future UI/query aid |
| `scenario` | VARCHAR(100), nullable | Optional for V1 | LLM metadata; not scenario-engine state |
| `period_json` | JSON scalar, nullable | Optional for V1 | Submitted parameter period; heterogeneous and not a series axis |
| `source_sheet` | VARCHAR(255), not null | Required for V1 | Exact workbook sheet title from backend fact |
| `source_cell` | VARCHAR(32), not null | Required for V1 | Backend-normalized uppercase A1 cell |
| `exact_formula` | Text, nullable | Required for V1 | Exact workbook formula when present; null for static cell |
| `formula_status` | VARCHAR(64), not null | Required for V1 | Backend status including `static_value` and unavailable states |
| `source_validation_status` | VARCHAR(32), not null | Required for V1 | Deterministic source validation result |
| `role_validation_status` | VARCHAR(32), not null | Required for V1 | Deterministic role reconciliation result |
| `validation_status` | VARCHAR(32), not null | Required for V1 | Overall deterministic result |
| `data_type` | VARCHAR(16), nullable | Required for V1 | Workbook/openpyxl cell type where available |
| `number_format` | Text, nullable | Required for V1 | Workbook number format where available |
| `llm_confidence` | Float, nullable | Optional for V1 | LLM-attributed confidence only |
| `validation_confidence` | Float, nullable | Required for V1 | Backend validator confidence |
| `reasoning_summary` | Text, nullable | Optional for V1 | LLM explanation; audit metadata only |
| `validation_warnings_json` | JSON array, nullable | Optional for V1 | Backend warnings without dependency graph persistence |
| `created_at` | timezone-aware DateTime, not null | Required for V1 | Backend UTC insertion timestamp |
| `displayed_value` | no column | Derived — do not store | Current toolset cannot reliably render it and returns unavailable |
| `dependency_evidence` | no column | Deferred | Formula-dependency persistence is explicitly out of scope |
| `rejected_claims` | no column | Derived — do not store | Retained in `validation_results_json`; rejected rows are not canonical parameters |

### 10.4 `financial_series`

| Field | Type / nullable | Classification | Authority and rationale |
|---|---|---|---|
| `id` | UUID, not null, PK | Required for V1 | Backend deterministic UUIDv5 from canonical source/context |
| `model_version_id` | UUID, not null, FK | Required for V1 | Canonical model owner |
| `entity_kind` | VARCHAR(32), not null | Required for V1 | Checked constant `financial_series`; discriminates the shared `FinancialEntity` contract and future supertype migration |
| `llm_series_alias` | VARCHAR(255), nullable | Optional for V1 | LLM series ID retained only as alias |
| `label` | Text, not null | Required for V1 | Submitted label retained on accepted canonical series |
| `category` | VARCHAR(100), nullable | Optional for V1 | LLM semantic metadata |
| `semantic_role` | VARCHAR(64), not null | Required for V1 | Fixed/checked as `financial_series` |
| `unit` | VARCHAR(100), nullable | Optional for V1 | LLM semantic metadata |
| `frequency` | VARCHAR(64), nullable | Optional for V1 | LLM semantic metadata |
| `orientation` | VARCHAR(16), not null | Required for V1 | Backend materializer: horizontal or vertical |
| `scenario` | VARCHAR(100), nullable | Optional for V1 | LLM semantic context, not scenario execution |
| `entity` | VARCHAR(255), nullable | Optional for V1 | LLM semantic context |
| `currency` | VARCHAR(32), nullable | Optional for V1 | LLM semantic context |
| `calculation_type` | VARCHAR(32), not null | Required for V1 | Backend materializer: formula, hardcoded, mixed, blank, unknown |
| `period_source_range` | Text, not null | Required for V1 | Backend-normalized qualified source range |
| `value_source_range` | Text, not null | Required for V1 | Backend-normalized qualified source range |
| `label_source_sheet` | VARCHAR(255), nullable | Optional for V1 | Parsed from valid label reference |
| `label_source_cell` | VARCHAR(32), nullable | Optional for V1 | Parsed from valid label reference |
| `materialization_status` | VARCHAR(32), not null | Required for V1 | Backend materializer status |
| `validation_status` | VARCHAR(32), not null | Required for V1 | Backend series validation status |
| `aliases_json` | JSON array, nullable | Optional for V1 | Backend deduplication label aliases |
| `formula_pattern_json` | JSON object, nullable | Optional for V1 | Series-level counts/consistency; per-point formulas remain relational |
| `warnings_json` | JSON array, nullable | Optional for V1 | Backend materialization warnings |
| `reasoning_summary` | Text, nullable | Optional for V1 | LLM explanation; not canonical fact |
| `llm_confidence` | Float, nullable | Optional for V1 | LLM confidence; not validation confidence |
| `created_at` | timezone-aware DateTime, not null | Required for V1 | Backend UTC insertion timestamp |
| `period_axis_json` | no column | Derived — do not store | Reconstructed from ordered value rows |
| `value_axis_json` | no column | Derived — do not store | Reconstructed from ordered value rows |
| failed/rejected series row | no row | Derived — do not store | Failure evidence remains in model-version validation JSON; only canonical accepted series are rows |

### 10.5 `financial_series_values`

| Field | Type / nullable | Classification | Authority and rationale |
|---|---|---|---|
| `id` | UUID, not null, PK | Required for V1 | Backend deterministic UUIDv5 from series ID and period index |
| `financial_series_id` | UUID, not null, FK | Required for V1 | Parent canonical series |
| `period_index` | Integer, not null | Required for V1 | Backend source order; stable aligned axis position |
| `raw_period_label_json` | JSON scalar, nullable | Required for V1 | Backend materialized raw period label; null is meaningful |
| `display_period_label` | Text, nullable | Required for V1 | Backend display normalization |
| `period_type` | VARCHAR(32), nullable | Optional for V1 | Safely recognized annual/quarterly/monthly/date/sequence type |
| `year` | Integer, nullable | Optional for V1 | Backend normalized component |
| `quarter` | Integer, nullable | Optional for V1 | Backend normalized component |
| `month` | Integer, nullable | Optional for V1 | Backend normalized component |
| `is_forecast` | Boolean, nullable | Optional for V1 | Backend normalized actual/forecast state |
| `value_json` | JSON scalar, nullable | Required for V1 | Backend workbook value; supports numeric, text marker, boolean, or null without opaque series JSON |
| `period_source_sheet` | VARCHAR(255), not null | Required for V1 | Parsed from backend period source cell |
| `period_source_cell` | VARCHAR(32), not null | Required for V1 | Uppercase A1 period cell |
| `value_source_sheet` | VARCHAR(255), not null | Required for V1 | Parsed from backend value source cell |
| `value_source_cell` | VARCHAR(32), not null | Required for V1 | Uppercase A1 value/formula cell |
| `exact_formula` | Text, nullable | Required for V1 | Exact backend formula at the value cell |
| `formula_status` | VARCHAR(64), not null | Required for V1 | Backend formula/cache/static status |
| `cached_value_available` | Boolean, not null | Required for V1 | Backend materializer fact |
| `cached_value_freshness` | VARCHAR(32), nullable | Required for V1 | Currently `unknown` for formula cells and null for static cells |
| `number_format` | Text, nullable | Required for V1 | Workbook value-cell number format |
| `data_type` | VARCHAR(16), nullable | Required for V1 | Workbook/openpyxl value-cell data type |
| `created_at` | timezone-aware DateTime, not null | Required for V1 | Backend UTC insertion timestamp |
| `calculation_type` | no column | Derived — do not store | Series-level property derived from point composition |
| formula dependencies / AST | no columns | Deferred | Explicitly owned by future Calculation Rule Extraction |

## 11. Constraints and Indexes

### 11.1 Keys, foreign keys, and cascade behavior

| Table | Constraint | Behavior and rationale |
|---|---|---|
| `workbook_versions` | PK `id` | Backend-generated stable workbook ID |
| `workbook_versions` | UNIQUE `sha256` | Identical bytes converge on one workbook version |
| `workbook_versions` | UNIQUE `(storage_type, storage_ref)` | One opaque location identifies at most one workbook artifact within an adapter |
| `workbook_versions` | CHECK `length(sha256) = 64` and `file_size > 0` | Reject malformed digest/empty persisted workbook; empty uploads are already rejected at HTTP boundary |
| `workbook_versions` | CHECK `storage_type <> 'database' OR content_bytes IS NOT NULL` | Database adapter rows must contain bytes; future object-store rows may keep the column null after verified migration |
| `model_versions` | PK `id` | One ID per extraction execution |
| `model_versions` | FK `workbook_version_id -> workbook_versions.id ON DELETE RESTRICT` | A source workbook cannot be deleted while any model version refers to it |
| `model_versions` | CHECK lifecycle/validation status values | Portable string checks are preferable to dialect-specific enums |
| `model_parameters` | PK `id` | Backend deterministic ID |
| `model_parameters` | FK `model_version_id -> model_versions.id ON DELETE CASCADE` | Deleting an explicitly deleted model version deletes its canonical children, not its workbook |
| `model_parameters` | CHECK `entity_kind = 'parameter'` | Enforces its branch of the shared `FinancialEntity` contract |
| `model_parameters` | UNIQUE `(model_version_id, source_sheet, source_cell)` | At most one canonical parameter-family entity per source cell in a model version |
| `financial_series` | PK `id` | Backend deterministic ID; retry uses the same source/context key |
| `financial_series` | FK `model_version_id -> model_versions.id ON DELETE CASCADE` | Canonical child lifecycle |
| `financial_series` | CHECK `entity_kind = 'financial_series'` | Enforces its branch of the shared `FinancialEntity` contract |
| `financial_series` | CHECK `semantic_role = 'financial_series'` | Prevent semantic drift |
| `financial_series_values` | PK `id` | Backend deterministic point ID |
| `financial_series_values` | FK `financial_series_id -> financial_series.id ON DELETE CASCADE` | Series deletion removes all aligned points |
| `financial_series_values` | UNIQUE `(financial_series_id, period_index)` | One aligned value per axis position |
| `financial_series_values` | UNIQUE `(financial_series_id, value_source_sheet, value_source_cell)` | A canonical series cannot repeat one value cell |
| `financial_series_values` | CHECK `period_index >= 0`, quarter 1–4, month 1–12 when non-null | Protect normalized period invariants |

**Proposed.** There is no cascade from `workbook_versions` to `model_versions`. Workbook bytes are the immutable audit source and should not disappear through a child cleanup operation. There is no current delete API for the new entities; if deletion is later required, it must be an explicit retention operation.

### 11.2 Indexes

| Index | Purpose |
|---|---|
| UNIQUE `workbook_versions(sha256)` | Content-addressed ingest and concurrency arbitration |
| UNIQUE `workbook_versions(storage_type, storage_ref)` | Adapter-local storage locator integrity |
| `model_versions(workbook_version_id, created_at)` | List executions for identical bytes |
| `model_versions(status, created_at)` | Operational stale/failure queries |
| `model_parameters(model_version_id, source_sheet, source_cell)` UNIQUE | Parameter source-cell resolution |
| `model_parameters(model_version_id, validated_role)` | Canonical role filtering |
| `financial_series(model_version_id, id)` | Model-to-series listing and source-cell join path |
| `financial_series(model_version_id, category)` | Optional category filtering without indexing JSON |
| `financial_series_values(financial_series_id, period_index)` UNIQUE | Ordered point reload |
| `financial_series_values(value_source_sheet, value_source_cell, financial_series_id)` | Value-cell provenance lookup followed by series/model join |
| `financial_series_values(period_source_sheet, period_source_cell, financial_series_id)` | Period provenance lookup and diagnostics |

No V1 index targets JSON. Current and future canonical lookup requirements are satisfied by relational columns.

### 11.3 Cell-level provenance decision

**Proposed.** Use indexed source columns plus one repository-side two-query lookup. Do not create a sixth provenance/binding table or a database view in V1.

For `resolve_entity_by_source_cell(model_version_id, sheet_name, cell_address)`:

1. normalize only the A1 address to uppercase; require the exact workbook sheet title;
2. query `model_parameters` by its unique model/sheet/cell key;
3. query `financial_series_values` by value sheet/cell joined to `financial_series.model_version_id`;
4. return a tagged result containing a common `FinancialEntityRef`; a series-value result also carries its point ID and period index;
5. return `None` when neither exists;
6. raise `AmbiguousSourceCellError` when both exist, rather than guessing.

Period cells remain queryable through their own indexed provenance fields but do not resolve as a canonical value entity. This avoids conflating a period header with the aligned financial-series value.

**Inferred.** A dedicated provenance table would make cross-entity uniqueness enforceable but would add polymorphic ownership, extra writes, and another source of truth before the repository has demonstrated a real collision. A view would still require dialect-specific deployment and would not enforce uniqueness. Indexed fields plus ambiguity detection and the shared `FinancialEntityRef` are therefore the smallest reliable V1 choice.

## 12. Workbook Storage Design

### 12.1 Option comparison

| Criterion | A. Database binary/blob | B. Persistent filesystem reference | C. Azure Blob/object reference |
|---|---|---|---|
| Current local compatibility | Excellent: existing SQLite/PostgreSQL SQLAlchemy path | Good in Docker Compose because `upload_data` exists | Requires emulator/account/client setup |
| Current production compatibility | Good: Azure PostgreSQL is already required | Poor: Container App config shows no durable `/app/uploads` mount and may run multiple replicas | Infrastructure account/container exists, but API client/config/identity wiring does not |
| Development/test simplicity | Highest; in-memory SQLite can round-trip bytes | Requires test directories, cleanup, permissions | Requires mocks/emulator/credentials |
| Durability/backup | Same backup and restore boundary as canonical rows | Depends on separately managed volume backup | Strong object durability and independent lifecycle |
| Atomicity | Workbook row and model-version row can share a transaction | Database reference can commit while file write/rename fails | Database reference and object put require compensation; no distributed transaction |
| New dependencies | None beyond SQLAlchemy | Persistent-volume deployment and file locking | Azure Storage SDK, configuration, identity/RBAC, network failure handling |
| File-size scaling | Suitable for bounded workbook sizes; large blobs increase DB backup/WAL cost | Good for large files | Best for large files and high volume |
| Content dedupe | UNIQUE SHA plus one row | Content-addressed path plus DB uniqueness | Content-addressed blob key plus DB uniqueness |
| Future migration | Copy bytes through a new adapter and switch the existing storage discriminator/reference | Move files to object store/database | Already the likely high-scale production medium, but still requires application wiring |

### 12.2 Required storage port

**Proposed.** All workbook byte I/O goes through a backend-owned port. Domain/application services depend on this contract, not on SQLAlchemy columns, filesystem paths, Azure SDK types, bucket/container names, or provider URIs:

```text
WorkbookStorageLocation(storage_type: str, storage_ref: str)

WorkbookStorage.location_for(storage_key: str) -> WorkbookStorageLocation

WorkbookStorage.store_if_absent(
    location: WorkbookStorageLocation,
    content_bytes: bytes,
    expected_sha256: str,
) -> None

WorkbookStorage.load(location: WorkbookStorageLocation) -> bytes

WorkbookStorage.verify(
    location: WorkbookStorageLocation,
    expected_sha256: str,
    expected_size: int,
) -> None
```

`storage_ref` is an opaque content-addressed key and contains no credentials. Only the configured adapter interprets it. `location_for` makes provider selection/configuration an adapter concern. `store_if_absent` must be immutable and idempotent for the same location/content; conflicting content at an existing location raises `WorkbookIntegrityError`. Delete is deliberately absent from the V1 port because retention/deletion policy is out of scope.

`WorkbookVersionRepository` owns workbook identity, SHA dedupe, filenames, timestamps, and the persisted storage location. It does not expose or read `content_bytes`. `DatabaseWorkbookStorage` is the only V1 adapter and may share the repository's caller-owned unit of work internally, but the port exposes no SQLAlchemy `Session`. Future `AzureBlobWorkbookStorage` or `S3WorkbookStorage` adapters implement the same contract without changing persistence orchestration or read-service consumers.

### 12.3 V1 adapter recommendation

**Proposed.** Choose Option A as the V1 adapter: `DatabaseWorkbookStorage` stores bytes in `workbook_versions.content_bytes` using SQLAlchemy `LargeBinary`, which maps to PostgreSQL BYTEA and SQLite BLOB. The catalog still records `storage_type='database'` and a content-addressed `storage_ref`. Add a configurable pre-LLM maximum upload size; the design recommendation is **25 MiB** until measured workbook distributions justify a different value.

Rationale:

- the current endpoint already buffers the entire workbook in memory, so bounded DB insertion does not introduce a new streaming regression;
- PostgreSQL is already a production dependency and SQLite is the local default;
- a single backup/restore boundary preserves source and canonical rows together;
- no file/object reference can be committed without the corresponding bytes;
- production filesystem durability is not configured;
- Blob infrastructure is provisioned but not wired into the API, so selecting it now expands deployment, credentials, SDK, and failure scope.

### 12.4 Identity, deduplication, and filenames

**Proposed.** `sha256` is the workbook content identity. `workbook_version_id` is the stable opaque backend ID for that content. Identical bytes reuse both values. Filename is metadata only:

- `workbook_versions.original_filename` is the first accepted filename and never changes;
- `model_versions.upload_filename` records the filename for each upload/extraction execution;
- a later upload with the same bytes and a different filename reuses the workbook row and creates a new model version with the later filename.

This avoids a filename-alias table while retaining per-execution audit context.

### 12.5 Insert concurrency and integrity

**Proposed.** The ingest service computes digest, size, and `storage_key = workbooks/sha256/<digest>.xlsx`, then obtains an opaque location from `WorkbookStorage.location_for`. `WorkbookVersionRepository` and the storage adapter coordinate insert-or-reuse inside the caller-owned T1 unit of work: the repository owns catalog fields; only `DatabaseWorkbookStorage` supplies/reads `content_bytes` before the new row is flushed. If the SHA unique constraint loses a concurrent race, the service reloads the winner and calls `WorkbookStorage.verify`. A size or digest mismatch raises `WorkbookIntegrityError`; neither adapter nor repository overwrites the existing immutable content.

`load_workbook_version` resolves the catalog location, calls `WorkbookStorage.load`, and returns a fresh immutable byte value after `WorkbookStorage.verify` establishes:

```text
len(loaded_bytes) == file_size
sha256(loaded_bytes) == sha256 column
```

With the V1 database adapter, the database backup contains both the artifact and the checksum needed to detect corruption.

### 12.6 Future object-store migration

**Proposed.** If measured workbook volume makes database blobs unsuitable, implement an Azure Blob or S3 adapter behind `WorkbookStorage`; copy each BLOB to its existing content-addressed `storage_ref`; verify digest and size through the new adapter; update `storage_type`; then null DB bytes only after reference verification. During migration, dual presence is allowed so verification can complete before cutover. The model/version/read-service interfaces and all stable IDs remain unchanged. Provider credentials, container/bucket names, retries, and orphan cleanup stay adapter/deployment concerns.

For a future nontransactional object adapter, `store_if_absent` must finish before the catalog commit; an adapter-specific coordinator may perform that idempotent put before opening the database transaction to avoid holding a connection during network I/O. A later catalog failure may leave an unreferenced content-addressed object, which can be safely detected and cleaned later; no distributed transaction is introduced. This compensation path is documented now but not implemented in V1.

## 13. Model Version Lifecycle

```mermaid
stateDiagram-v2
    [*] --> extracting: "T1 workbook/model row committed"
    extracting --> extracted: "pipeline snapshot committed"
    extracting --> extraction_failed: "LLM or local pipeline failure"
    extracted --> materialized: "canonical transaction committed"
    extracted --> persistence_failed: "canonical transaction rolled back"
    persistence_failed --> materialized: "persistence-only retry from snapshot"
    extraction_failed --> [*]
    materialized --> [*]
```

### 13.1 State semantics

| Status | Durable meaning | Canonical reload allowed? |
|---|---|---|
| `extracting` | Source and model identity committed; LLM/pipeline not durably captured | No |
| `extracted` | Extraction/validation snapshot committed; canonical relational write not yet committed | No |
| `materialized` | All accepted canonical parameters/series/values committed atomically | Yes |
| `extraction_failed` | Pipeline did not produce a persistable snapshot; sanitized failure evidence committed | No |
| `persistence_failed` | Snapshot exists but canonical write failed and rolled back | No; persistence retry allowed |

**Proposed.** `validation_status` is independent of lifecycle. A model can be `materialized` with `validated_with_warning` or `review_required` when accepted canonical entities exist alongside warnings/rejected candidates. This matches current synchronous behavior: series-scoped failures are structured results rather than necessarily failing the whole request.

Once `materialized`, the model version and all canonical children are immutable. A new extraction creates a new model version. The only retry transition that writes canonical rows in place is `persistence_failed -> materialized`, and it must derive the same child IDs from the already committed snapshot and workbook.

Aggregate validation mapping:

- `validated`: all persisted canonical rows are validated with no warnings;
- `validated_with_warning`: warnings exist but no reclassification, review, or rejected candidate/series;
- `review_required`: any reclassified/review/rejected candidate or failed/duplicate series exists while canonical persistence can still complete;
- `rejected`: the pipeline produced no trustworthy canonical result according to the implementation gate;
- `not_run`: extraction or validation did not complete.

**Open policy for approval.** The recommended future read service returns materialized models even when review is required, with status visible. Calculation Rule Extraction should decide whether its own task requires `validated`/`validated_with_warning` only; this design does not implement that gate.

## 14. Write and Transaction Flow

### 14.1 Proposed flow

```mermaid
flowchart TD
    A["1. Receive and validate .xlsx bytes"] --> B["2. Compute SHA-256 and prepare WorkbookToolset"]
    B --> C["T1: WorkbookStorage put/verify; insert/reuse catalog; create model_version=extracting; commit"]
    C --> D["3. Run current synchronous agent, materializer, validator outside DB transaction"]
    D -->|exception or submitted=false| E["T-fail: save failure telemetry; mark extraction_failed; commit"]
    D -->|submitted=true| F["T2: save extraction/validation snapshot; status=extracted; commit"]
    F --> G["4. Reopen durable bytes; build canonical rows with backend IDs"]
    G --> H["T3: insert parameters, series, values; status=materialized; commit"]
    H --> I["5. Return current response plus committed IDs"]
    G -->|write/constraint failure| J["T3 rollback all canonical rows"]
    J --> K["T-fail: mark persistence_failed; commit"]
```

### 14.2 Preparation before the first transaction

**Proposed.** Preserve current format/empty checks. Enforce the size limit. Compute SHA-256 from the exact received bytes and construct/validate a `WorkbookToolset` before persisting anything, so corrupt OOXML does not become a workbook version. The implementation may extract an internal “prepared workbook” function so the current toolset instance continues into the pipeline; this is an internal refactor, not an HTTP contract change.

**Observed in code.** `WorkbookToolset` supports `file_bytes` directly even though the current adapter passes a temporary path.

Evidence:
- `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset.__init__`
- `apps/api/app/workbook_validation.py:run_workbook_validation`

### 14.3 Transaction T1 — source and identity

**Proposed.** In one short transaction:

1. derive the opaque content-addressed storage key and call `WorkbookStorage.location_for`;
2. insert or reuse the `workbook_versions` catalog row by SHA-256 and persist its storage location;
3. call `WorkbookStorage.store_if_absent`/`verify` before the new catalog row is flushed or committed;
4. generate a new `model_version_id`;
5. insert `model_versions(status='extracting', validation_status='not_run', submitted=false)`;
6. commit.

This occurs before the LLM request so an extraction failure has a stable model ID and exact source. `DatabaseWorkbookStorage` participates in this transaction through its adapter-specific unit of work, preserving V1 atomicity without leaking SQLAlchemy into the port. No database transaction remains open during model calls.

### 14.4 Pipeline execution

**Proposed.** Run the existing exploration, coverage gate, financial-series materializer, and validator synchronously. Preserve current behavior and response contents. If the pipeline returns `submitted=false`, commit coverage/driver/stop/error evidence with `status='extraction_failed'` and do not enter canonical persistence. If it returns `submitted=true`, capture a deep, JSON-safe extraction snapshot; it includes the mutated canonical `financial_series`, preserved `financial_series_descriptors`, candidate buckets, and output/metadata candidates. Store filtered validation results in their separate model-version field. The snapshot is retry/audit input only: canonicalization may consume it within T3/retry, but no downstream service may query or parse it.

### 14.5 Transaction T2 — durable snapshot

**Proposed.** Persist the extraction snapshot, driver metadata, coverage, summaries, detailed validation results (excluding `dependency_evidence`), submitted flag, stop reason, aggregate validation status, and `extracted_at`; set lifecycle to `extracted`; commit. This transaction is intentionally separate from canonical rows so a later persistence retry can reuse the exact extraction result without another LLM call. Excluding dependency evidence preserves validation outcomes without creating an accidental formula-dependency persistence contract.

If T2 itself fails, retry T2 within the request while the in-memory result exists. If the process ends before T2 commits, mark or later reconcile the model version as failed; a later extraction retry creates a new model version because no durable snapshot exists.

### 14.6 Transaction T3 — canonical relational write

**Proposed.** Resolve workbook storage location through `WorkbookVersionRepository`, reload and integrity-check bytes through `WorkbookStorage`, then build parameter and series/value rows outside the transaction or before the first flush. In one transaction:

1. lock/read the model version and require `status in {'extracted', 'persistence_failed'}`;
2. insert deterministic-ID `model_parameters` with `entity_kind='parameter'`;
3. insert deterministic-ID `financial_series` with `entity_kind='financial_series'`;
4. insert all `financial_series_values`;
5. verify expected inserted counts and source conflicts;
6. set `status='materialized'`, validation status, and `completed_at`;
7. commit.

Any exception rolls back all child rows and the status update. A new short transaction records `persistence_failed` and a sanitized error code. There is never a partially committed canonical model.

### 14.7 Partial series failures and warnings

**Proposed.** Persist accepted `final_extraction.financial_series` rows and their values. Do not insert rejected/failed series as canonical rows. Preserve every failure in `validation_results_json`, set aggregate `validation_status='review_required'`, and still allow lifecycle `materialized` if the canonical write is internally consistent. Warnings alone do not roll back data.

### 14.8 Stale `extracting` rows

**Proposed.** V1 needs no worker or queue. A synchronous request marks failures on handled exceptions. On service startup or an operator-triggered repository method, rows left `extracting` beyond the configured request deadline can be marked `extraction_failed` with `STALE_EXTRACTION`; rows left `extracted` remain eligible for explicit persistence retry. This is bounded state reconciliation, not distributed orchestration.

## 15. Reload and Query Contract

### 15.1 Ownership

**Proposed.** `ModelExtractionReadService` is the only upstream interface exposed to future Calculation Rule Extraction. It returns typed domain DTOs assembled solely from canonical relational tables, not SQLAlchemy entities, the original API response JSON, `extraction_snapshot_json`, or `validation_results_json`. V1 does not add a public reload HTTP endpoint.

The persistence service may use a private `load_extraction_snapshot_for_retry(model_version_id)` repository method only while recovering `extracted`/`persistence_failed` states. An authorized audit path may read the raw snapshot separately. Neither method is part of `ModelExtractionReadService`, and neither may be injected into downstream modules.

### 15.2 Interfaces

```text
load_workbook_version(workbook_version_id: UUID) -> WorkbookVersionData
load_model_version(model_version_id: UUID, require_materialized: bool = True) -> ModelVersionData
list_financial_entities(model_version_id: UUID) -> list[FinancialEntity]
list_parameters(model_version_id: UUID) -> list[CanonicalParameter]
list_financial_series(model_version_id: UUID) -> list[CanonicalFinancialSeries]
list_financial_series_values(model_version_id: UUID, financial_series_id: UUID | None = None)
    -> list[CanonicalFinancialSeriesValue]
resolve_entity_by_source_cell(
    model_version_id: UUID,
    sheet_name: str,
    cell_address: str,
) -> SourceResolvedEntity | None
```

`WorkbookVersionData` contains ID, SHA-256, first-seen filename, file size, created timestamp, and bytes loaded/verified through `WorkbookStorage`; it does not expose `storage_ref`. `ModelVersionData` contains both IDs, lifecycle/validation status, upload filename, submitted/stop metadata, and timestamps. It contains no extraction snapshot, driver/coverage/summary JSON, or detailed validation JSON. Canonical series values are returned ordered by `(financial_series_id, period_index)`.

`FinancialEntity` is a discriminated union with the common reference contract:

```text
FinancialEntityRef(
    id: UUID,
    model_version_id: UUID,
    entity_kind: Literal["parameter", "financial_series"],
    label: str,
)

FinancialEntity = CanonicalParameter | CanonicalFinancialSeries
```

Type-specific DTOs retain their relational fields. Consumers can reference the common ID/kind without losing type-safe parameter or series detail. No DTO field contains a table name or snapshot location.

`SourceResolvedEntity` is a tagged union:

```text
ParameterResolution(entity=FinancialEntityRef(entity_kind="parameter", ...), parameter=...)
FinancialSeriesValueResolution(
    entity=FinancialEntityRef(entity_kind="financial_series", ...),
    series=...,
    value=...,
)
```

### 15.3 Failure behavior

| Condition | Failure |
|---|---|
| Unknown workbook ID | `WorkbookVersionNotFound` |
| Workbook size/hash mismatch | `WorkbookIntegrityError` |
| Unknown model ID | `ModelVersionNotFound` |
| Model ID belongs to another workbook than caller expects | `ModelWorkbookMismatch` |
| Model lifecycle is not `materialized` and readiness is required | `ModelVersionNotReady(status=...)` |
| Series ID does not belong to model | `FinancialSeriesNotFound` |
| Cell address malformed | `InvalidCellAddress` |
| No canonical mapping | Return `None`; never infer or fuzzy-match |
| Parameter and series value both map to the same source | `AmbiguousSourceCellError` |

### 15.4 Required upstream check

**Proposed.** A future caller given both IDs must first call `load_model_version`, verify its `workbook_version_id` equals the supplied workbook ID, and then load the workbook. It must obtain parameters, series, and values only through canonical read methods. Reading `extraction_snapshot_json` directly or using it to fill a missing canonical field is a contract violation. This prevents both source mismatch and accidental dependence on transient LLM schema.

## 16. Idempotency and Retry Behaviour

### 16.1 Same bytes uploaded twice

**Proposed.** Reuse `workbook_version_id`; always create a new `model_version_id`. Extraction can vary by model deployment, prompt, runtime, and workbook-agent behavior, so reusing a previous model version would hide an execution and make audit history ambiguous. Do not reject duplicates.

### 16.2 Persistence-only retry

**Proposed.** Reuse the same model version when `status='persistence_failed'` and `extraction_snapshot_json` exists. Reload the exact workbook, rebuild deterministic child IDs, and rerun T3. Do not call the LLM. Atomic rollback ensures no committed partial children; deterministic IDs and unique constraints protect against duplicate inserts. If the model is already `materialized`, return its existing IDs as an idempotent no-op.

### 16.3 Extraction retry

**Proposed.** A new LLM/pipeline attempt always creates a new model version linked to the same workbook version. Failed rows remain immutable evidence; do not update them into a different execution. There is no separate attempt table in V1.

### 16.4 Retry matrix

| Existing state | Requested action | Result |
|---|---|---|
| No workbook row | Upload bytes | Insert workbook + new model version |
| Same SHA exists | Upload bytes | Reuse workbook + new model version |
| `extracting` in active request | Duplicate persistence call | Reject/serialize as in-progress |
| `extraction_failed` | Persistence retry | Reject; no durable snapshot; start a new extraction/model version |
| `extracted` | Canonical persistence | Execute T3 |
| `persistence_failed` + snapshot | Canonical persistence retry | Execute T3 without LLM |
| `materialized` | Same persistence request | No-op and return existing IDs |

## 17. API Impact

### 17.1 Minimal response change required during implementation

**Proposed.** Retain the existing synchronous response and add exactly two nullable top-level string fields:

```json
{
  "workbook_version_id": "...",
  "model_version_id": "...",
  "endpoint_mode": "experimental_workbook_agent_validation",
  "final_extraction": {},
  "validation_results": []
}
```

Populate both fields only after T3 commits `materialized`; return both as `null` on the current structured `submitted=false` response. Do not expose an upstream-ready ID pair for an uncommitted canonical model. Update `WorkbookValidationResponse` and the exact-field contract test. Preserve current structured 400/415/422/500/502/503 behavior; add a sanitized persistence error mapping as needed.

Declare both response fields as `str | None`. The successful upstream contract requires two non-null values; partial pairs are invalid.

**Observed in tests.** The current success contract asserts exact field equality, so adding IDs requires an intentional test/schema update rather than an unannounced extra response field.

Evidence:
- `apps/api/app/schemas.py:WorkbookValidationResponse`
- `tests/test_experimental_workbook_upload.py:REQUIRED_RESPONSE_FIELDS`
- `tests/test_experimental_workbook_upload.py:test_success_returns_complete_raw_validation_contract`

### 17.2 Router dependencies

**Proposed.** Add `db: Session = Depends(get_db)` to the active route or inject a session factory into the persistence service. Do not add authentication merely as part of persistence; the current experiment is unauthenticated and auth policy is outside scope. Remove neither the legacy rollback function nor unrelated endpoints in this implementation.

### 17.3 Reload API decision

**Proposed.** Expose internal repository/read-service methods only in V1. A public GET endpoint would require authorization, response pagination, retention semantics, and an external contract not needed by the immediate backend-to-backend Calculation Rule Extraction consumer.

## 18. Migration Strategy

### 18.1 Current tooling assessment

**Observed in code.** The repository relies on both startup `Base.metadata.create_all` and raw PostgreSQL initialization scripts. There is no schema-version runner for an existing database. Azure deployment creates the PostgreSQL server/extension but does not execute the repository table scripts against an existing database; application startup is therefore the effective missing-table mechanism.

Evidence:
- `apps/api/app/main.py:lifespan`
- `docker-compose.yml:services.postgres.volumes`
- `infra/deploy.sh:Azure Database for PostgreSQL`
- `apps/api/requirements.txt`

**Proposed.** `create_all` is acceptable for isolated ephemeral SQLite test databases and fresh local convenience. It is not acceptable as the production migration authority because it neither records schema version nor alters existing tables/constraints safely.

### 18.2 Recommended migration mechanism

**Proposed.** Introduce Alembic as the first production-safe migration mechanism and use SQLAlchemy metadata as the schema source. Establish a baseline for existing tables without recreating them, then create one additive migration containing only the five new tables, constraints, and indexes. Do not alter or backfill `financial_models`.

Use portable SQLAlchemy types:

- `Uuid(as_uuid=False)` for backend-generated IDs, native UUID on PostgreSQL and portable storage on SQLite;
- `LargeBinary` for the V1 database storage adapter, isolated behind `WorkbookStorage`;
- `String` storage discriminator/reference columns so the catalog is not bound to BLOB access;
- generic `JSON` for cross-dialect snapshots/scalars, with no JSON-specific indexes;
- `DateTime(timezone=True)` for UTC timestamps;
- `String` plus named `CheckConstraint` for statuses rather than PostgreSQL enum types.

Run the same migration in SQLite migration tests and PostgreSQL integration tests. Keep raw `schema_v1.sql`/`schema_v2_vector.sql` untouched for legacy/bootstrap compatibility during this task family; once Alembic is adopted operationally, document it as the authoritative forward migration path.

### 18.3 Implementation sequence

1. Add migration tooling/baseline and the additive five-table migration.
2. Add focused ORM models in `apps/api/app/model_extraction_models.py` and ensure metadata imports them before startup/test schema creation.
3. Define `WorkbookStorage` and `WorkbookStorageLocation` without provider or ORM types; add shared adapter contract tests.
4. Add `DatabaseWorkbookStorage` plus `WorkbookVersionRepository` with SHA uniqueness, opaque storage location, byte integrity, and reload tests.
5. Add the common `FinancialEntityRef`/discriminated DTO contract and `FinancialEntityIdFactory` before the type-specific repositories.
6. Add `ModelExtractionRepository` and internal DTO mapping for model, parameter, series, and point writes/reads; keep snapshot reads private to audit/retry.
7. Add `ModelExtractionPersistenceService` and explicit T1/T2/T3 transaction tests.
8. Add canonical-only `ModelExtractionReadService`, `list_financial_entities`, and source-cell lookup.
9. Integrate the service at the active upload adapter, retaining current pipeline behavior.
10. Add the two response IDs and update exact API contract tests.
11. Run SQLite and PostgreSQL integration suites plus all existing workbook-agent/upload regressions.

### 18.4 No legacy data migration

**Proposed.** Do not backfill from `financial_models.parsed_json`, legacy upload files, assumptions, scenarios, or document chunks. Their schema and parser output do not provide the exact current workbook-agent/materializer contract, and a speculative conversion would violate clear ownership.

## 19. Error Handling

| Failure point | Durable state | HTTP/internal behavior | Retry |
|---|---|---|---|
| Unsupported/empty/oversize upload | No rows | Structured 400/413/415; no LLM | Correct input and resubmit |
| Corrupt OOXML during preparation | No rows | Existing structured 422 | Correct input and resubmit |
| Concurrent same-SHA insert | Reuse winner workbook row | Transparent unless integrity mismatch | Continue with new model version |
| Workbook hash/size mismatch | Existing row unchanged | `WorkbookIntegrityError`, 500 sanitized | Operator investigation; never overwrite |
| Azure configuration/Responses failure | Workbook + `extraction_failed` model | Preserve existing 503/502 mapping and sanitized code | New extraction/model version |
| Coverage/incomplete submission | Workbook + `extraction_failed` model with telemetry | Preserve `AGENT_INCOMPLETE` evidence and current structured response; IDs remain null; do not mark materialized | New extraction/model version |
| Snapshot write failure | Model remains `extracting`, then failure record if possible | Sanitized persistence failure | Retry T2 in-process; otherwise new extraction |
| Candidate source conflict | Snapshot retained, canonical transaction rolled back, `persistence_failed` | `CANONICAL_SOURCE_CONFLICT` | Fix canonicalization/data or retry same model version after code correction |
| Canonical insert/constraint failure | No canonical children committed; `persistence_failed` | Sanitized 500 | Retry same model version from snapshot |
| Some series rejected | Accepted canonical rows committed; validation `review_required` | Current response includes failures and committed IDs | No automatic rerun |
| Validation warnings | Canonical rows committed; warning status | Current response plus IDs | No retry required |
| Reload of nonmaterialized model | Existing failure/in-progress evidence retained | `ModelVersionNotReady` | Retry persistence or extraction according to state |

**Proposed.** Raw database exceptions, Azure secrets, workbook cell contents, and formulas must not enter HTTP error messages. Detailed structured validation evidence belongs in persisted snapshots and authorized internal logs, not sanitized error strings.

## 20. Testing Strategy

Test names follow the repository's current flat `tests/test_*.py` convention. PostgreSQL-marked tests may use the existing Docker service or a CI service; SQLite tests remain the fast default.

### 20.1 Schema and migration tests — `tests/test_model_extraction_persistence_schema.py`

- `test_migration_creates_model_extraction_tables_on_sqlite`
- `test_migration_creates_model_extraction_tables_on_postgres`
- `test_workbook_sha256_is_unique`
- `test_workbook_storage_location_is_unique_per_adapter`
- `test_database_storage_requires_content_bytes`
- `test_model_version_requires_existing_workbook_version`
- `test_model_parameter_requires_existing_model_version`
- `test_financial_series_value_requires_existing_series`
- `test_model_parameter_source_cell_is_unique_within_model_version`
- `test_financial_series_period_index_is_unique_within_series`
- `test_deleting_model_version_cascades_canonical_children_but_not_workbook`
- `test_deleting_referenced_workbook_version_is_restricted`
- `test_status_check_constraints_reject_unknown_values`
- `test_parameter_entity_kind_is_checked`
- `test_financial_series_entity_kind_is_checked`

### 20.2 Workbook storage and repository tests — `tests/test_workbook_storage.py`, `tests/test_workbook_version_repository.py`

- `test_workbook_storage_contract_is_provider_agnostic`
- `test_database_adapter_round_trips_bytes_through_storage_port`
- `test_storage_ref_is_opaque_to_repository_and_read_service`
- `test_create_workbook_version_persists_exact_bytes_and_sha256`
- `test_identical_bytes_reuse_workbook_version_id`
- `test_identical_bytes_with_different_filename_preserve_first_filename`
- `test_concurrent_identical_inserts_converge_on_one_workbook_version`
- `test_load_workbook_version_survives_session_and_service_restart`
- `test_load_workbook_version_rejects_size_mismatch`
- `test_load_workbook_version_rejects_sha256_mismatch`
- `test_oversize_workbook_is_rejected_before_llm_and_database_write`
- `test_storage_adapter_conflicting_content_at_same_key_raises_integrity_error`

### 20.3 Canonical persistence tests — `tests/test_model_extraction_persistence.py`

- `test_successful_pipeline_persists_materialized_model_and_ids`
- `test_parameter_candidates_persist_only_backend_eligible_roles`
- `test_formula_derived_parameter_persists_null_value_exact_formula_and_status`
- `test_metadata_candidates_remain_snapshot_only`
- `test_validated_output_candidates_remain_snapshot_only`
- `test_duplicate_candidate_buckets_create_one_parameter_per_source_cell`
- `test_conflicting_candidates_for_one_source_cell_roll_back_canonical_write`
- `test_financial_series_and_all_aligned_values_persist_in_source_order`
- `test_every_series_value_persists_period_value_source_cells_formula_and_format`
- `test_failed_series_remains_validation_evidence_but_not_canonical_series`
- `test_partial_canonical_write_rolls_back_parameters_series_and_values`
- `test_persistence_failure_marks_model_version_without_false_materialized_state`
- `test_backend_generated_ids_ignore_llm_candidate_and_series_ids`
- `test_parameter_and_series_use_shared_financial_entity_id_factory`
- `test_persistence_retry_reuses_deterministic_child_ids_without_llm_rerun`

### 20.4 Lifecycle/idempotency tests — `tests/test_model_extraction_lifecycle.py`

- `test_workbook_and_extracting_model_commit_before_llm_execution`
- `test_extraction_failure_retains_workbook_and_marks_model_failed`
- `test_snapshot_commits_before_canonical_persistence`
- `test_same_bytes_new_extraction_creates_new_model_version`
- `test_persistence_retry_uses_same_model_version_and_snapshot`
- `test_extraction_retry_creates_new_model_version`
- `test_already_materialized_persistence_retry_is_noop`
- `test_stale_extracting_model_is_reconciled_to_failed`

### 20.5 Reload/provenance tests — `tests/test_model_extraction_reload.py`

- `test_reload_model_after_new_session_returns_same_parameters`
- `test_reload_model_after_new_session_returns_same_series_and_values`
- `test_list_financial_entities_returns_discriminated_parameter_and_series_dtos`
- `test_financial_entity_ids_remain_stable_across_type_specific_reload`
- `test_list_financial_series_values_orders_by_series_and_period_index`
- `test_reload_rejects_model_and_workbook_id_mismatch`
- `test_nonmaterialized_model_is_not_reloadable_as_canonical`
- `test_resolve_entity_by_source_cell_returns_parameter`
- `test_resolve_entity_by_source_cell_returns_financial_series_value`
- `test_resolve_entity_by_source_cell_returns_none_for_unmapped_cell`
- `test_resolve_entity_by_source_cell_rejects_invalid_a1_address`
- `test_resolve_entity_by_source_cell_raises_on_cross_type_collision`
- `test_model_read_dtos_do_not_expose_snapshot_telemetry_summary_or_validation_json`
- `test_canonical_read_service_never_falls_back_to_snapshot_json`

### 20.6 API and regression tests

Update `tests/test_experimental_workbook_upload.py`:

- `test_success_returns_committed_workbook_and_model_version_ids`
- `test_response_ids_are_null_when_pipeline_is_not_materialized`
- `test_http_persistence_failure_does_not_return_a_success_response`
- retain existing format, empty, corrupt, Azure, sanitization, and OpenAPI tests.

Update/retain `tests/test_workbook_validation.py`:

- `test_adapter_runs_real_tools_gate_and_validator`
- `test_incomplete_run_returns_evidence_and_structured_error`
- `test_financial_model_data_completes_geometric_coverage_without_rejection`
- `test_legacy_complete_series_are_materialized_and_summary_is_nonzero`
- `test_temporary_workbook_is_removed_after_success_and_failure`

Retain `experiments/workbook_agent_poc/tests/test_financial_series.py` and `test_validator.py` unchanged except where an internal outcome adapter must be tested. Persistence must not alter pre-persistence extraction or materialization behavior.

### 20.7 Completion verification

Implementation is not complete until:

1. the focused persistence/migration tests pass on SQLite;
2. the same schema/transaction integration tests pass on PostgreSQL;
3. the current focused workbook-agent/upload suite still passes;
4. a restart simulation closes all sessions, creates a new repository/service, reloads bytes and canonical rows, and verifies source/formula metadata;
5. a forced mid-write exception proves all canonical children roll back;
6. no test uses the HTTP response JSON as the canonical reload source;
7. a storage contract suite passes through `DatabaseWorkbookStorage` without application services reading `content_bytes` directly;
8. canonical read DTOs expose the shared `FinancialEntity` contract but no snapshot/audit fields;
9. deleting or corrupting a canonical row causes an explicit read failure rather than reconstruction from snapshot JSON.

## 21. Deferred Items

**Deferred.** The following are not required for the first persistence implementation:

- object-store/file-system storage adapter implementations; the port and storage reference columns are V1 requirements;
- public reload/list HTTP endpoints;
- model parent/entity separate from model version;
- relational `financial_entities` supertype table; the compatible identity/read seam is V1, the table is deferred until justified by a cross-type consumer;
- multiple extraction attempts beneath one model version;
- authenticated ownership/tenant columns and retention/deletion APIs;
- candidate/output/metadata relational tables beyond canonical parameters;
- provenance binding table or database view;
- full agent trace persistence;
- formula inventory, dependencies, rules, AST, or execution;
- scenario/sensitivity structures;
- vectorization/document chunks;
- legacy `financial_models` linkage or backfill;
- queues, jobs, or automatic retries;
- workbook diffing across versions.

## 22. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Database blobs increase backup/WAL size | Operational cost and slower backup | 25 MiB V1 cap, monitor total bytes, content dedupe, documented object-store migration path |
| V1 BLOB details leak into orchestration | Azure Blob/S3 migration requires service rewrite | Require `WorkbookStorage` port, opaque location DTO, adapter contract tests, and no direct `content_bytes` access outside database adapter |
| SQLite/PostgreSQL behavior diverges | Local tests pass while production fails | Portable types/checks, named constraints, run integration tests on both dialects |
| Existing `create_all`/raw SQL drift continues | Production schema version unclear | Introduce Alembic baseline; do not treat `create_all` as production migration |
| LLM schema evolves | Snapshot shape changes | Treat snapshot as versioned audit/retry artifact; canonical rows and repositories are consumer contract |
| Downstream code treats snapshot as canonical fallback | Calculation Rule Extraction silently couples to transient LLM schema | Exclude snapshot fields/methods from `ModelExtractionReadService`, enforce canonical-only DTO tests, and fail on missing canonical rows |
| Parameters and series evolve as unrelated models | Future formula-reference consumers need breaking table-specific contracts | Shared entity ID factory, checked `entity_kind`, `FinancialEntityRef`, and no-ID-change supertype migration path |
| Candidate buckets duplicate/conflict | Duplicate or incorrect parameters | Unique source-cell constraint, deterministic canonicalization, conflict failure instead of guessing |
| Cross-table source-cell collision | Ambiguous future formula reference | Two-query lookup detects and raises; add provenance table only if real collision semantics emerge |
| Exact formula lost for parameters | Future rule extraction cannot audit | Re-read durable workbook source during canonicalization and store `exact_formula`/status |
| Partial series failures look successful | Future consumer assumes completeness | Separate lifecycle and validation status; preserve detailed failures; read DTO exposes readiness |
| LLM call occurs inside DB transaction | Long locks and pool pressure | Commit T1 before LLM and use short T2/T3 transactions |
| Snapshot commit succeeds but canonical write fails | Durable noncanonical state | `extracted`/`persistence_failed` states, atomic T3 rollback, persistence-only retry |
| Identical bytes uploaded concurrently | Duplicate workbook rows | Unique SHA constraint plus savepoint/reload winner |
| Process crash leaves in-progress state | Stale nonterminal rows | Deadline-based synchronous reconciliation; never treat nonmaterialized state as ready |
| Filename differs for identical content | Audit metadata ambiguity | First filename on workbook plus per-model upload filename |

## 23. Open Decisions

**Approved on 2026-07-15.** Review approved the V1 direction—database workbook storage, Alembic, materialized-with-review behavior, the two committed response IDs, and retained audit/retry snapshots—subject to three binding conditions now incorporated throughout this specification:

1. parameter and series persistence must preserve a common `FinancialEntity` evolution seam;
2. workbook bytes must be accessed through `WorkbookStorage`, with database BLOB as an adapter rather than a hard-coded service dependency;
3. snapshots are audit/retry-only and forbidden as downstream input, including for Calculation Rule Extraction.

The remaining operational decisions are not architecture blockers for implementation planning:

1. **Snapshot retention duration and deletion authorization.** No automatic deletion is introduced in V1; operations/security owners must define retention before a delete workflow is designed.
2. **Object-store migration trigger.** Measure workbook size distribution, database growth, WAL, and backup duration before choosing a threshold or Azure Blob/S3 provider.
3. **Future supertype trigger.** Add a relational `financial_entities` table only when a real cross-type reference/query requires it; the stable IDs and DTO contract are already fixed.

None of these decisions requires designing Calculation Rule Extraction itself.

## 24. Implementation Readiness Checklist

- [x] Reviewers approve DB binary workbook storage and the initial file-size cap, behind `WorkbookStorage`.
- [x] Reviewers approve new `model_versions` ownership rather than legacy `financial_models` reuse.
- [x] Reviewers approve one model version per extraction execution and no separate run table.
- [x] Reviewers approve five-table scope with no provenance/formula-rule tables.
- [x] Reviewers require and approve a common `FinancialEntity` identity/read seam while retaining focused V1 tables.
- [x] Reviewers approve deterministic backend child IDs and LLM alias-only treatment.
- [x] Reviewers approve candidate eligibility and same-cell conflict behavior.
- [x] Reviewers approve accepted-series-only relational rows with rejected evidence in JSON.
- [x] Reviewers approve T1/T2/T3 short transaction boundaries and snapshot-before-canonical retry design.
- [x] Reviewers require canonical-only downstream reads and prohibit snapshot consumption by Calculation Rule Extraction.
- [x] Reviewers approve internal read-service interfaces and no public reload endpoint.
- [x] Reviewers approve Alembic as the forward migration authority.
- [ ] SQLite and PostgreSQL migration/test environments are available to the implementer.
- [x] Design review approves the two additive response fields and commit-before-return rule.
- [ ] No Calculation Rule Extraction, frontend, vector, legacy, async, or engine work is bundled into implementation.

### Recommended First Implementation Task

**Proposed.** Implement the approved schema and abstraction foundation only:

1. bootstrap Alembic against the existing schema without altering legacy tables;
2. add ORM models and one additive migration for all five approved tables, including storage locator fields and both checked `entity_kind` fields;
3. define `WorkbookStorage`, `WorkbookStorageLocation`, `FinancialEntityRef`, and `FinancialEntityIdFactory` without provider or Calculation Rule concepts;
4. implement only `DatabaseWorkbookStorage`, the minimal `WorkbookVersionRepository` catalog coordination it requires, and cross-dialect contract tests, proving that callers can put/load/verify immutable bytes without direct BLOB access;
5. add SQLite and PostgreSQL tests for SHA/storage-location uniqueness, all foreign keys, source/period uniqueness, entity/status constraints, LargeBinary round-trip, and cascade/restriction behavior;
6. do not add extraction repositories/services, integrate the upload endpoint, call the LLM, expose snapshot reads, or change the response in this first task.

This is the smallest independently reviewable task that proves both the complete approved schema and the two critical evolution seams before write orchestration begins.

## 25. Repository Evidence Appendix

### API and lifecycle

- **Observed in code:** active synchronous upload and error mapping — `apps/api/app/routers/models.py:upload_model`.
- **Observed in code:** temporary storage, toolset construction, extraction, materialization, validation, and response assembly — `apps/api/app/workbook_validation.py:run_workbook_validation`.
- **Observed in tests:** exact response contract and no DB/auth dependency — `tests/test_experimental_workbook_upload.py:test_success_returns_complete_raw_validation_contract`, `tests/test_experimental_workbook_upload.py:test_experimental_route_has_no_database_or_auth_dependency`.
- **Observed in tests:** temporary storage cleanup — `tests/test_workbook_validation.py:test_temporary_workbook_is_removed_after_success_and_failure`.

### Workbook facts and identity

- **Observed in code:** SHA-256 and dual workbook loading — `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset.__init__`.
- **Observed in code:** full cell evidence envelope and exact formula status — `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset._cell_fact`.
- **Observed in code:** workbook-version binding in range chunks — `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset.read_range`.
- **Observed in code:** coverage verifies workbook-version binding — `experiments/workbook_agent_poc/coverage_gate.py:CoverageTracker._validate_binding`.

### Extraction, materialization, and validation

- **Observed in code:** LLM candidate/series schema — `experiments/workbook_agent_poc/extraction_contract.py:SUBMIT_RESULT_SCHEMA`.
- **Observed in code:** backend candidate source/role validation — `experiments/workbook_agent_poc/validator.py:validate_candidate`, `experiments/workbook_agent_poc/validator.py:validate_extraction`.
- **Observed in code:** backend role families and reconciliation — `experiments/workbook_agent_poc/roles.py:family`, `experiments/workbook_agent_poc/roles.py:reconcile`.
- **Observed in code:** canonical series/point construction — `experiments/workbook_agent_poc/time_series.py:FinancialSeriesMaterializer.materialize`.
- **Observed in code:** accepted-series collection, dedupe, statuses, and summaries — `experiments/workbook_agent_poc/time_series.py:FinancialSeriesMaterializer.materialize_collection`.
- **Observed in code:** mutation of final extraction to canonical series — `experiments/workbook_agent_poc/time_series.py:materialize_financial_series`.
- **Observed in tests:** complete source/value provenance and canonical status — `experiments/workbook_agent_poc/tests/test_financial_series.py:test_descriptor_only_materializes_complete_horizontal_series`.
- **Observed in tests:** backend values override LLM arrays — `experiments/workbook_agent_poc/tests/test_financial_series.py:test_legacy_arrays_are_ignored_as_source_of_truth`.
- **Observed in tests:** exact formula/cache telemetry — `experiments/workbook_agent_poc/tests/test_financial_series.py:test_formula_series_remains_financial_and_uses_backend_telemetry`.
- **Observed in tests:** real upload adapter produces canonical financial-series output — `tests/test_workbook_validation.py:test_financial_model_data_completes_geometric_coverage_without_rejection`.

### Database and deployment

- **Observed in code:** SQLite default/PostgreSQL configuration and session lifecycle — `apps/api/app/database.py:get_db`.
- **Observed in code:** startup `create_all` — `apps/api/app/main.py:lifespan`.
- **Observed in code:** legacy response-blob/file-path model — `apps/api/app/models.py:FinancialModel`.
- **Observed in code:** application-generated UUID string convention — `apps/api/app/models.py:generate_uuid`.
- **Observed in code:** PostgreSQL UUID/JSONB schema — `db/schema_v1.sql:CREATE TABLE financial_models`, `db/schema_v1.sql:CREATE TABLE model_assumptions`.
- **Observed in code:** local persistent upload volume and PostgreSQL init scripts — `docker-compose.yml:services.api.volumes`, `docker-compose.yml:services.postgres.volumes`.
- **Observed in code:** Azure Blob account/container provisioning — `infra/deploy.sh:Azure Blob Storage (M10)`, `infra/deploy.ps1:Azure Blob Storage (M10)`.
- **Observed in code:** production API has `/app/uploads` but no persistent mount/storage settings — `infra/deploy.sh:Deploying Backend API Container App`, `infra/deploy.ps1:Deploying Backend API`.
- **Observed in code:** no Azure Blob SDK dependency — `apps/api/requirements.txt`.

### Final Decision Table

| Decision | Recommendation | Rationale | Confidence | Evidence |
|---|---|---|---:|---|
| Workbook storage medium | `DatabaseWorkbookStorage` using `LargeBinary` for V1, behind `WorkbookStorage` | Database is the only currently wired durable medium across SQLite/PostgreSQL, while the port and opaque locator prevent hard-coding it | 0.95 | `apps/api/app/database.py:DATABASE_URL`; `docker-compose.yml:services.api.volumes`; `infra/deploy.sh:Deploying Backend API Container App`; `apps/api/requirements.txt` |
| Workbook storage abstraction | Required `WorkbookStorage` put/load/verify port plus `storage_type`/opaque `storage_ref` | Azure Blob or S3 can replace the adapter without changing model/extraction/read-service contracts | 0.99 | **Proposed**, informed by existing but unwired Blob provisioning in `infra/deploy.sh:Azure Blob Storage (M10)` |
| Workbook deduplication policy | Reuse workbook by UNIQUE SHA-256; verify size/hash; filename is metadata | Exact bytes define version; prevents duplicate blob cost without hiding executions | 0.97 | `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset.__init__` |
| Model identity entity | New `model_versions`; one row per extraction execution | Clean ownership and direct upstream ID | 0.96 | `apps/api/app/routers/models.py:upload_model`; `tests/test_experimental_workbook_upload.py:test_experimental_route_has_no_database_or_auth_dependency` |
| Relationship to legacy `financial_models` | None in V1; no reuse, FK, or backfill | Legacy owns file path/`parsed_json`/analytics concerns not present in current extraction | 0.97 | `apps/api/app/models.py:FinancialModel`; `apps/api/app/routers/models.py:_legacy_upload_model_for_rollback` |
| Canonical parameter storage | Relational `model_parameters` for backend-validated assumption/derived/selector families, participating in the shared `FinancialEntity` contract | Supports stable references and avoids trusting candidate buckets without isolating parameters from series evolution | 0.97 | `experiments/workbook_agent_poc/validator.py:validate_candidate`; `experiments/workbook_agent_poc/roles.py:family` |
| Canonical series storage | Relational `financial_series` with normalized metadata/ranges/status, participating in the shared `FinancialEntity` contract | Backend materializer establishes canonical series while common identity/read semantics preserve future unification | 0.99 | `experiments/workbook_agent_poc/time_series.py:FinancialSeriesMaterializer.materialize` |
| Individual value storage | One `financial_series_values` row per aligned point | Preserves order, period/value provenance, exact formula and cache status | 0.99 | `experiments/workbook_agent_poc/time_series.py:FinancialSeriesMaterializer.materialize`; `experiments/workbook_agent_poc/tests/test_financial_series.py:test_descriptor_only_materializes_complete_horizontal_series` |
| FinancialEntity evolution seam | Shared entity ID factory, checked `entity_kind`, and discriminated `FinancialEntityRef`; no supertype table in V1 | Avoids independent consumer contracts and permits a later shared-PK supertype without changing IDs | 0.98 | **Proposed**, grounded in the two current canonical shapes from `experiments/workbook_agent_poc/validator.py:validate_candidate` and `experiments/workbook_agent_poc/time_series.py:FinancialSeriesMaterializer.materialize` |
| Stable ID strategy | UUIDv4 for workbook/model; one backend UUIDv5 `FinancialEntityIdFactory` for parameter/series; deterministic UUIDv5 values; LLM IDs aliases only | Distinct executions, deterministic retry, cross-type namespace, and no-ID-change supertype migration | 0.97 | `apps/api/app/models.py:generate_uuid`; `experiments/workbook_agent_poc/extraction_contract.py:_CANDIDATE`; `experiments/workbook_agent_poc/extraction_contract.py:_FINANCIAL_SERIES` |
| Cell provenance lookup | Indexed parameter/value source columns plus `FinancialEntityRef` union and ambiguity error | Smallest reliable solution; avoids premature polymorphic table/view while giving callers a common entity reference | 0.93 | `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset._cell_fact`; `experiments/workbook_agent_poc/tests/test_financial_series.py:test_descriptor_only_materializes_complete_horizontal_series` |
| Transaction boundaries | T1 storage port/catalog/identity, LLM outside transaction, T2 audit/retry snapshot, T3 atomic canonical rows | Preserves failure evidence and retry payload without long/distributed transaction | 0.96 | `apps/api/app/workbook_validation.py:run_workbook_validation`; `apps/api/app/database.py:get_db` |
| Retry policy | Same workbook/new model for new extraction; same model/private snapshot for persistence retry | Auditable attempts and no unnecessary LLM rerun without exposing snapshots to downstream consumers | 0.98 | `experiments/workbook_agent_poc/agent_loop.py:run_loop`; `experiments/workbook_agent_poc/time_series.py:materialize_financial_series` |
| Snapshot consumer contract | Audit and same-model persistence retry only; excluded from `ModelExtractionReadService` and all downstream DTOs | Prevents downstream coupling to transient LLM/API schema and makes relational rows the enforceable canonical source | 1.00 | **Approved/Proposed**, consistent with backend-owned canonical materialization in `experiments/workbook_agent_poc/time_series.py:materialize_financial_series` |
| Minimal API changes | Retain response; add a nullable ID pair populated together only after materialized commit; internal reload service only | Preserves synchronous consumer behavior and avoids public API redesign | 0.96 | `apps/api/app/schemas.py:WorkbookValidationResponse`; `tests/test_experimental_workbook_upload.py:test_success_returns_complete_raw_validation_contract` |
| Calculation Rule Extraction upstream contract | Require matching materialized IDs; load exact bytes through `WorkbookStorage` and entities only through canonical relational read methods | Guarantees exact bytes and canonical entities after restart while explicitly forbidding snapshot dependence | 1.00 | `experiments/workbook_agent_poc/workbook_tools.py:WorkbookToolset.workbook_version`; `tests/test_workbook_validation.py:test_temporary_workbook_is_removed_after_success_and_failure` |
