# Model Extraction Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current synchronous Model Extraction upload durable, reloadable, auditable, and addressable by committed `workbook_version_id` and `model_version_id` values.

**Architecture:** Add five canonical SQLAlchemy tables and Alembic migrations, isolate immutable workbook bytes behind a `WorkbookStorage` port with a database adapter, persist backend-generated `FinancialEntity`-compatible parameters and series, and expose a canonical-only internal read service. A transaction orchestration service performs T1 workbook/model identity, T2 audit/retry snapshot, and T3 atomic canonical persistence around the unchanged synchronous workbook-agent pipeline.

**Tech Stack:** Python 3.12, FastAPI 0.115, Pydantic 2.7, SQLAlchemy 2.0.30, Alembic 1.13.1, SQLite, PostgreSQL 16, openpyxl 3.1.2, pytest.

## Global Constraints

- Work only in `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.claude/worktrees/model-extraction-persistence-design` on `design/model-extraction-persistence`.
- Use `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3` for Python and pytest commands.
- Follow strict RED -> GREEN: no production function, model, route behavior, or migration implementation before its focused test fails for the expected missing behavior.
- Do not make live Azure calls; API and service integration tests use deterministic validation runners.
- Do not implement Calculation Rule Extraction, formula inventory/dependencies, calculation rules, ASTs, formula execution, Calculation Engine, scenario/sensitivity execution, queues, frontend work, vectorization, document chunking, or legacy analytics repair.
- Keep five V1 tables only: `workbook_versions`, `model_versions`, `model_parameters`, `financial_series`, `financial_series_values`.
- Keep `model_parameters` and `financial_series` type-specific while sharing `FinancialEntityIdFactory`, checked `entity_kind`, `FinancialEntityRef`, and a discriminated canonical read contract.
- All workbook byte access goes through `WorkbookStorage`; only `DatabaseWorkbookStorage` may read or write `content_bytes`.
- `extraction_snapshot_json` and `validation_results_json` are private audit/persistence-retry artifacts. `ModelExtractionReadService` must expose neither them nor driver, coverage, or summary JSON, and must never reconstruct missing canonical rows from JSON.
- The existing synchronous response remains intact except for nullable `workbook_version_id` and `model_version_id`, populated together only after T3 commits `materialized`.
- Preserve current workbook-agent materialization and validation behavior before persistence.
- Use explicit-path staging, `git diff --cached --check`, and one task-scoped commit after each task is green.

---

## File Structure

### New backend modules

- `apps/api/app/model_extraction_models.py` — the five ORM tables, named constraints, relationships, and portable field types.
- `apps/api/app/model_extraction_types.py` — stable IDs, `FinancialEntityRef`, DTOs, JSON-safe conversion, and typed persistence/read errors.
- `apps/api/app/workbook_storage.py` — `WorkbookStorage` protocol, `WorkbookStorageLocation`, and `DatabaseWorkbookStorage`.
- `apps/api/app/model_extraction_repository.py` — workbook catalog, model lifecycle, canonical write/query operations, and private snapshot access.
- `apps/api/app/model_extraction_read_service.py` — materialized-only canonical DTO loaders and source-cell resolution.
- `apps/api/app/model_extraction_service.py` — T1/T2/T3 orchestration and deterministic candidate/series canonicalization.

### Migration files

- `apps/api/alembic.ini` — Alembic configuration rooted beneath `apps/api`.
- `apps/api/alembic/env.py` — obtains the repository database URL and imports all metadata.
- `apps/api/alembic/script.py.mako` — standard revision template.
- `apps/api/alembic/versions/20260715_0001_existing_schema_baseline.py` — no-op baseline for existing legacy schema ownership.
- `apps/api/alembic/versions/20260715_0002_model_extraction_persistence.py` — additive five-table schema.

### Tests

- `tests/model_extraction_test_support.py` — isolated SQLite engine/session helpers, deterministic payload builders, and model import setup.
- `tests/test_model_extraction_persistence_schema.py` — metadata, migration, FK, uniqueness, checks, and cascade behavior.
- `tests/test_workbook_storage.py` — provider-neutral storage contract, SHA dedupe, immutable bytes, and integrity failures.
- `tests/test_model_extraction_persistence.py` — parameter/series/value canonical writes and rollback behavior.
- `tests/test_model_extraction_lifecycle.py` — T1/T2/T3 transitions, retries, failures, and idempotency.
- `tests/test_model_extraction_reload.py` — canonical-only reload, `FinancialEntity` union, exact workbook bytes, and provenance lookup.
- `tests/test_experimental_workbook_upload.py` — additive ID contract, database dependency, persistence error sanitization, and current error regressions.

---

### Task 1: Portable Schema and Alembic Foundation

**Files:**
- Create: `apps/api/app/model_extraction_models.py`
- Create: `apps/api/alembic.ini`
- Create: `apps/api/alembic/env.py`
- Create: `apps/api/alembic/script.py.mako`
- Create: `apps/api/alembic/versions/20260715_0001_existing_schema_baseline.py`
- Create: `apps/api/alembic/versions/20260715_0002_model_extraction_persistence.py`
- Create: `tests/model_extraction_test_support.py`
- Create: `tests/test_model_extraction_persistence_schema.py`
- Modify: `apps/api/requirements.txt`
- Modify: `apps/api/app/database.py`
- Modify: `apps/api/app/main.py`

**Interfaces:**
- Produces: ORM classes `WorkbookVersion`, `ModelVersion`, `ModelParameter`, `FinancialSeries`, `FinancialSeriesValue`.
- Produces: `create_sqlite_session_factory() -> tuple[Engine, sessionmaker[Session]]` for focused tests.
- Produces: Alembic head `20260715_0002` that creates only the five persistence tables.
- Produces: SQLite connections with `PRAGMA foreign_keys=ON`.

- [ ] **Step 1: Add RED schema tests**

  Add tests that import the five new ORM classes, call `Base.metadata.create_all()` on isolated SQLite, and assert:

  ```python
  assert {
      "workbook_versions",
      "model_versions",
      "model_parameters",
      "financial_series",
      "financial_series_values",
  } <= set(inspect(engine).get_table_names())
  ```

  Add focused tests named:

  ```text
  test_metadata_creates_all_model_extraction_tables
  test_workbook_sha256_is_unique
  test_database_storage_requires_content_bytes
  test_model_version_requires_existing_workbook
  test_parameter_entity_kind_is_checked
  test_financial_series_entity_kind_is_checked
  test_period_index_is_unique_within_series
  test_deleting_model_version_cascades_children_but_not_workbook
  test_alembic_upgrades_empty_sqlite_database_to_persistence_head
  ```

- [ ] **Step 2: Verify RED**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_model_extraction_persistence_schema.py -q
  ```

  Expected: collection fails because `model_extraction_models` and the Alembic configuration do not exist.

- [ ] **Step 3: Add the migration dependency and portable ORM models**

  Pin `alembic==1.13.1` in `apps/api/requirements.txt`. Define the exact field matrix from design Section 10 with:

  ```python
  from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float
  from sqlalchemy import ForeignKey, Integer, JSON, LargeBinary, String, Text
  from sqlalchemy import UniqueConstraint, Uuid
  ```

  Use `Uuid(as_uuid=False)` for IDs, `DateTime(timezone=True)`, generic `JSON`, and named constraints. Required invariants:

  ```text
  uq_workbook_versions_sha256
  uq_workbook_versions_storage_location
  ck_workbook_versions_sha_length
  ck_workbook_versions_positive_size
  ck_workbook_versions_database_has_bytes
  ck_model_versions_status
  ck_model_versions_validation_status
  ck_model_parameters_entity_kind
  uq_model_parameters_source_cell
  ck_financial_series_entity_kind
  ck_financial_series_semantic_role
  uq_financial_series_value_period_index
  uq_financial_series_value_source_cell
  ck_financial_series_value_period_index
  ck_financial_series_value_quarter
  ck_financial_series_value_month
  ```

  Use `ON DELETE RESTRICT` from model version to workbook, `ON DELETE CASCADE` for canonical children, and `passive_deletes=True` relationships.

- [ ] **Step 4: Add SQLite FK enforcement and metadata import**

  Register a SQLite connection listener in `database.py`:

  ```python
  @event.listens_for(engine, "connect")
  def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
      if DATABASE_URL.startswith("sqlite"):
          cursor = dbapi_connection.cursor()
          cursor.execute("PRAGMA foreign_keys=ON")
          cursor.close()
  ```

  Import `model_extraction_models` in `main.py` before metadata creation. Keep `Base.metadata.create_all()` only when `USE_SQLITE=true` or `AUTO_CREATE_SCHEMA=true`; production PostgreSQL relies on Alembic.

- [ ] **Step 5: Add Alembic baseline and additive revision**

  Configure `env.py` with `target_metadata = Base.metadata`, `compare_type=True`, `render_as_batch` only for SQLite, and the runtime `DATABASE_URL`. Revision `20260715_0001` has empty `upgrade()`/`downgrade()`. Revision `20260715_0002` creates the five tables in FK order and drops them in reverse order.

- [ ] **Step 6: Install the pinned dependency and verify GREEN**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pip install 'alembic==1.13.1'
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_model_extraction_persistence_schema.py -q
  ```

  Expected: every schema/migration test passes on SQLite.

- [ ] **Step 7: Commit Task 1**

  ```bash
  git add apps/api/requirements.txt apps/api/app/database.py apps/api/app/main.py apps/api/app/model_extraction_models.py apps/api/alembic.ini apps/api/alembic tests/model_extraction_test_support.py tests/test_model_extraction_persistence_schema.py
  git diff --cached --check
  git commit -m "feat: add model extraction persistence schema"
  ```

---

### Task 2: Workbook Storage Port and Immutable Catalog

**Files:**
- Create: `apps/api/app/model_extraction_types.py`
- Create: `apps/api/app/workbook_storage.py`
- Create: `apps/api/app/model_extraction_repository.py`
- Create: `tests/test_workbook_storage.py`
- Modify: `tests/model_extraction_test_support.py`

**Interfaces:**
- Produces:

  ```python
  @dataclass(frozen=True)
  class WorkbookStorageLocation:
      storage_type: str
      storage_ref: str

  class WorkbookStorage(Protocol):
      def location_for(self, storage_key: str) -> WorkbookStorageLocation:
          raise NotImplementedError

      def store_if_absent(self, location: WorkbookStorageLocation, content_bytes: bytes, expected_sha256: str) -> None:
          raise NotImplementedError

      def load(self, location: WorkbookStorageLocation) -> bytes:
          raise NotImplementedError

      def verify(self, location: WorkbookStorageLocation, expected_sha256: str, expected_size: int) -> None:
          raise NotImplementedError
  ```

- Produces: `DatabaseWorkbookStorage(session: Session)`.
- Produces: `WorkbookVersionRepository(session, storage).get_or_create(content_bytes, original_filename) -> WorkbookVersion`.
- Produces: `WorkbookIntegrityError`, `WorkbookVersionNotFound`.

- [ ] **Step 1: Add RED storage contract tests**

  Add tests named:

  ```text
  test_database_adapter_round_trips_bytes_through_storage_port
  test_storage_location_is_content_addressed_and_opaque
  test_identical_bytes_reuse_workbook_version_id
  test_identical_bytes_with_new_filename_preserve_first_filename
  test_storage_conflict_at_existing_key_raises_integrity_error
  test_load_rejects_sha_mismatch
  test_load_rejects_size_mismatch
  test_repository_never_returns_mutable_content_buffer
  ```

  Use a real SQLite session and `WorkbookToolset` fixture bytes; do not mock the adapter.

- [ ] **Step 2: Verify RED**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_workbook_storage.py -q
  ```

  Expected: import fails because the storage port and repository are absent.

- [ ] **Step 3: Implement stable storage types and JSON-safe utility**

  In `model_extraction_types.py`, implement:

  ```python
  def new_uuid() -> str:
      return str(uuid.uuid4())

  def json_safe(value: Any) -> Any:
      if isinstance(value, (datetime, date)):
          return value.isoformat()
      if isinstance(value, uuid.UUID):
          return str(value)
      if isinstance(value, dict):
          return {str(key): json_safe(item) for key, item in value.items()}
      if isinstance(value, (list, tuple)):
          return [json_safe(item) for item in value]
      return value
  ```

  Define typed errors without embedding workbook data in their messages.

- [ ] **Step 4: Implement `DatabaseWorkbookStorage`**

  `location_for()` returns `WorkbookStorageLocation("database", storage_key)`. The adapter resolves a pending or persisted `WorkbookVersion` by `(storage_type, storage_ref)`, is the only module that touches `content_bytes`, compares conflicting existing bytes, and verifies both size and SHA-256 on every load/reuse.

- [ ] **Step 5: Implement workbook catalog dedupe**

  `WorkbookVersionRepository.get_or_create()` computes SHA-256 and `workbooks/sha256/<digest>.xlsx`, reuses an existing SHA row after adapter verification, or inserts a UUIDv4 catalog row and asks the adapter to supply bytes before flush. Catch a named SHA uniqueness race inside `session.begin_nested()`, reload the winner, and verify it.

- [ ] **Step 6: Verify GREEN and regressions**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_workbook_storage.py tests/test_model_extraction_persistence_schema.py -q
  ```

- [ ] **Step 7: Commit Task 2**

  ```bash
  git add apps/api/app/model_extraction_types.py apps/api/app/workbook_storage.py apps/api/app/model_extraction_repository.py tests/model_extraction_test_support.py tests/test_workbook_storage.py
  git diff --cached --check
  git commit -m "feat: add immutable workbook storage"
  ```

---

### Task 3: Canonical FinancialEntity Writer

**Files:**
- Modify: `apps/api/app/model_extraction_types.py`
- Modify: `apps/api/app/model_extraction_repository.py`
- Create: `tests/test_model_extraction_persistence.py`

**Interfaces:**
- Produces: `FinancialEntityIdFactory.parameter_id()`, `series_id()`, and `value_id()` using UUIDv5.
- Produces: `ModelExtractionRepository.create_model_version()`, `save_extraction_snapshot()`, `persist_canonical_model()`, `mark_status()`, and private `load_snapshot_for_retry()`.
- Consumes canonical row dictionaries whose keys match the five ORM tables exactly.

- [ ] **Step 1: Add RED ID and atomic-write tests**

  Add tests named:

  ```text
  test_parameter_and_series_ids_share_financial_entity_factory
  test_llm_alias_changes_do_not_change_backend_ids
  test_repository_persists_parameter_series_and_aligned_values
  test_parameter_source_cell_conflict_rolls_back_all_canonical_rows
  test_value_period_index_conflict_rolls_back_all_canonical_rows
  test_private_snapshot_loader_is_not_a_public_read_dto
  ```

  Force a failure after parameters but before values and assert all three canonical tables remain empty.

- [ ] **Step 2: Verify RED**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_model_extraction_persistence.py -q
  ```

- [ ] **Step 3: Implement shared FinancialEntity identity**

  Implement UUIDv5 keys exactly as:

  ```text
  financial_entity|parameter|<source_sheet>|<source_cell>
  financial_entity|financial_series|<period_range>|<value_range>|<scenario>|<entity>|<unit>|<currency>
  financial_series_value|<period_index>
  ```

  Define immutable `FinancialEntityRef(id, model_version_id, entity_kind, label)` and use checked kinds `parameter` and `financial_series`.

- [ ] **Step 4: Implement lifecycle and canonical repository writes**

  Repository methods accept a caller-owned session and call `flush()`, never `commit()`. `persist_canonical_model()` requires an `extracted` or `persistence_failed` model version with no canonical child rows, inserts deterministic IDs, validates expected counts, and sets `materialized` only after every row flushes. A failed flush is rolled back atomically, so persistence retry starts from the same empty canonical state and regenerates the same deterministic child IDs. Materialized rows are immutable and are never deleted or replaced. Snapshot access remains a private repository method with a leading underscore and is never included in DTO conversion.

- [ ] **Step 5: Verify GREEN**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_model_extraction_persistence.py tests/test_workbook_storage.py -q
  ```

- [ ] **Step 6: Commit Task 3**

  ```bash
  git add apps/api/app/model_extraction_types.py apps/api/app/model_extraction_repository.py tests/test_model_extraction_persistence.py
  git diff --cached --check
  git commit -m "feat: persist canonical model extraction entities"
  ```

---

### Task 4: Canonical-Only Reload and Provenance Contract

**Files:**
- Modify: `apps/api/app/model_extraction_types.py`
- Create: `apps/api/app/model_extraction_read_service.py`
- Create: `tests/test_model_extraction_reload.py`

**Interfaces:**
- Produces:

  ```python
  load_workbook_version(workbook_version_id: str) -> WorkbookVersionData
  load_model_version(model_version_id: str, require_materialized: bool = True) -> ModelVersionData
  list_financial_entities(model_version_id: str) -> list[CanonicalParameter | CanonicalFinancialSeries]
  list_parameters(model_version_id: str) -> list[CanonicalParameter]
  list_financial_series(model_version_id: str) -> list[CanonicalFinancialSeries]
  list_financial_series_values(model_version_id: str, financial_series_id: str | None = None) -> list[CanonicalFinancialSeriesValue]
  resolve_entity_by_source_cell(model_version_id: str, sheet_name: str, cell_address: str) -> SourceResolvedEntity | None
  ```

- Produces: `ModelVersionNotFound`, `ModelVersionNotReady`, `ModelWorkbookMismatch`, `FinancialSeriesNotFound`, `InvalidCellAddress`, `AmbiguousSourceCellError`.

- [ ] **Step 1: Add RED reload tests**

  Add tests named:

  ```text
  test_reload_workbook_after_new_session_returns_verified_bytes
  test_nonmaterialized_model_is_not_canonically_reloadable
  test_list_financial_entities_returns_discriminated_parameter_and_series
  test_series_values_are_ordered_by_series_and_period_index
  test_source_cell_resolves_parameter
  test_source_cell_resolves_series_value_with_parent_entity_ref
  test_unmapped_source_cell_returns_none
  test_invalid_a1_address_is_rejected
  test_cross_type_source_collision_raises_ambiguity
  test_read_dtos_expose_no_snapshot_telemetry_or_validation_json
  test_missing_canonical_row_never_falls_back_to_snapshot
  ```

- [ ] **Step 2: Verify RED**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_model_extraction_reload.py -q
  ```

- [ ] **Step 3: Implement immutable DTOs and materialized-only reads**

  Define frozen dataclasses for workbook/model/parameter/series/value and source resolutions. `ModelVersionData` includes only IDs, lifecycle/validation status, upload filename, submitted/stop metadata, and timestamps. It has no JSON evidence fields. All canonical reads first require `model_versions.status == "materialized"` unless an explicit internal diagnostic call sets `require_materialized=False`.

- [ ] **Step 4: Implement strict source-cell resolution**

  Validate uppercase A1 syntax, query parameter by exact `(model_version_id, sheet, cell)`, query value joined through series/model, return `None` for no mapping, and raise on cross-type ambiguity. A series-value resolution includes its parent `FinancialEntityRef(entity_kind="financial_series")` and point ID/index.

- [ ] **Step 5: Verify GREEN**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_model_extraction_reload.py tests/test_model_extraction_persistence.py -q
  ```

- [ ] **Step 6: Commit Task 4**

  ```bash
  git add apps/api/app/model_extraction_types.py apps/api/app/model_extraction_read_service.py tests/test_model_extraction_reload.py
  git diff --cached --check
  git commit -m "feat: add canonical model extraction reload"
  ```

---

### Task 5: T1/T2/T3 Persistence Orchestration

**Files:**
- Create: `apps/api/app/model_extraction_service.py`
- Create: `tests/test_model_extraction_lifecycle.py`
- Modify: `tests/model_extraction_test_support.py`

**Interfaces:**
- Produces:

  ```python
  class ModelExtractionPersistenceService:
      # Constructor takes a caller-owned session, storage adapter, repository,
      # and deterministic validation runner.

      def process_upload(self, file_bytes: bytes, filename: str) -> dict[str, Any]:
          raise NotImplementedError

      def retry_canonical_persistence(self, model_version_id: str) -> tuple[str, str]:
          raise NotImplementedError
  ```

- Produces: `ModelExtractionPersistenceError`, `CanonicalSourceConflictError`, `PersistenceRetryNotAllowed`.
- Consumes: unchanged `run_workbook_validation(file_bytes, filename) -> dict` output.

- [ ] **Step 1: Add RED lifecycle tests**

  Add tests named:

  ```text
  test_t1_commits_workbook_and_extracting_model_before_runner
  test_invalid_workbook_creates_no_rows
  test_runner_exception_marks_extraction_failed_and_preserves_exception_type
  test_submitted_false_marks_extraction_failed_and_returns_null_ids
  test_t2_snapshot_commits_before_t3
  test_success_persists_parameter_series_values_and_returns_ids
  test_snapshot_strips_dependency_evidence
  test_metadata_and_output_candidates_remain_snapshot_only
  test_formula_derived_parameter_reloads_exact_formula_and_null_cache
  test_t3_failure_rolls_back_children_and_marks_persistence_failed
  test_persistence_retry_reuses_snapshot_ids_without_runner_call
  test_same_bytes_new_upload_reuses_workbook_and_creates_model
  test_already_materialized_retry_is_idempotent
  ```

  Use deterministic result payloads and a real `WorkbookToolset` fixture. Instrument the runner with a second session to prove T1 is committed before it executes.

- [ ] **Step 2: Verify RED**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_model_extraction_lifecycle.py -q
  ```

- [ ] **Step 3: Implement preparation and T1**

  Validate OOXML with `WorkbookToolset(file_bytes=file_bytes)` before persistence. T1 stores/reuses workbook bytes, creates UUIDv4 model version with `extracting/not_run`, commits, and leaves no transaction open around the runner.

- [ ] **Step 4: Implement T2 audit/retry projection**

  On `submitted=false`, mark `extraction_failed` and return both IDs as `None`. On success, deep-convert the extraction result through `json_safe()`, recursively omit every `dependency_evidence` key, persist snapshot/telemetry/validation evidence, calculate aggregate validation status, set `extracted`, and commit. The private retry loader is the only canonicalization path that reads the snapshot.

- [ ] **Step 5: Implement deterministic parameter canonicalization**

  Match validation results to source candidates by `(_bucket, candidate_id)`, accept only source-valid assumption/derived/selector families, group by exact sheet/A1 cell, prefer `parameter_candidates`, then `derived_value_candidates`, `unclassified_inputs`, `review_candidates`, `all_assumption_candidates`, and finally eligible reclassified `output_candidates`. Re-read each source fact from the durable workbook for exact formula/status/value. Raise `CanonicalSourceConflictError` when surviving validated roles or values disagree.

- [ ] **Step 6: Implement deterministic series/value canonicalization and T3**

  Consume only backend materialized `final_extraction.financial_series`. Generate series ID from normalized source/context, zip aligned period/value point dictionaries, parse qualified cell references, persist exact formula/cache/format/type fields, and require equal lengths. T3 writes parameters, series, and values atomically, verifies counts, sets `materialized`, and commits. A failure rolls T3 back and marks `persistence_failed` in a new short transaction.

- [ ] **Step 7: Implement persistence-only retry**

  Permit only `extracted` or `persistence_failed` rows with a private snapshot. Reload verified bytes, reconstruct the same deterministic rows, skip the LLM runner, and return existing IDs as a no-op for `materialized`.

- [ ] **Step 8: Verify GREEN and focused regressions**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_model_extraction_lifecycle.py tests/test_model_extraction_persistence.py tests/test_model_extraction_reload.py tests/test_workbook_validation.py experiments/workbook_agent_poc/tests/test_financial_series.py experiments/workbook_agent_poc/tests/test_validator.py -q
  ```

- [ ] **Step 9: Commit Task 5**

  ```bash
  git add apps/api/app/model_extraction_service.py tests/model_extraction_test_support.py tests/test_model_extraction_lifecycle.py
  git diff --cached --check
  git commit -m "feat: orchestrate model extraction persistence"
  ```

---

### Task 6: Synchronous API Integration and Migration Startup

**Files:**
- Modify: `apps/api/app/routers/models.py`
- Modify: `apps/api/app/schemas.py`
- Modify: `apps/api/Dockerfile`
- Modify: `tests/test_experimental_workbook_upload.py`
- Modify: `tests/test_workbook_validation.py`

**Interfaces:**
- Produces: `WorkbookValidationResponse.workbook_version_id: str | None` and `model_version_id: str | None`.
- Produces: active `POST /api/v1/models/upload` with `db: Session = Depends(get_db)` and unchanged non-persistence error mapping.
- Produces: sanitized `MODEL_EXTRACTION_PERSISTENCE_ERROR` response for persistence failures.
- Produces: container startup command `alembic -c apps/api/alembic.ini upgrade head` before Uvicorn.

- [ ] **Step 1: Add RED API contract tests**

  Update `REQUIRED_RESPONSE_FIELDS` with both IDs and add tests named:

  ```text
  test_success_returns_committed_workbook_and_model_version_ids
  test_submitted_false_returns_null_version_ids
  test_upload_route_has_database_but_not_auth_dependency
  test_persistence_failure_is_sanitized_and_not_returned_as_success
  test_successful_upload_is_reloadable_after_request_session_closes
  test_dockerfile_runs_alembic_before_uvicorn
  ```

  Override `get_db` with an isolated SQLite session factory. Pass a deterministic validation runner through a monkeypatched router symbol; do not make Azure calls.

- [ ] **Step 2: Verify RED**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_experimental_workbook_upload.py -q
  ```

- [ ] **Step 3: Integrate the persistence service**

  Change the active route signature to:

  ```python
  async def upload_model(
      file: UploadFile = File(...),
      db: Session = Depends(get_db),
  ):
      service = ModelExtractionPersistenceService(
          session=db,
          validation_runner=run_workbook_validation,
      )
      return service.process_upload(file_bytes, filename)
  ```

  Preserve 400/415/422/500/502/503 mappings and add one sanitized persistence error mapping. Do not add auth, a public reload endpoint, or legacy side effects.

- [ ] **Step 4: Add response IDs and container migration command**

  Add nullable Pydantic string fields. Update Docker CMD to run the pinned Alembic head before Uvicorn:

  ```dockerfile
  CMD ["sh", "-c", "alembic -c apps/api/alembic.ini upgrade head && uvicorn apps.api.app.main:app --host 0.0.0.0 --port 8000"]
  ```

- [ ] **Step 5: Verify GREEN and current adapter behavior**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests/test_experimental_workbook_upload.py tests/test_workbook_validation.py -q
  ```

- [ ] **Step 6: Commit Task 6**

  ```bash
  git add apps/api/app/routers/models.py apps/api/app/schemas.py apps/api/Dockerfile tests/test_experimental_workbook_upload.py tests/test_workbook_validation.py
  git diff --cached --check
  git commit -m "feat: persist model extraction uploads"
  ```

---

### Task 7: Cross-Dialect and Completion Verification

**Files:**
- Modify: `tests/test_model_extraction_persistence_schema.py`
- Modify: `tests/test_model_extraction_lifecycle.py`
- Modify: `docs/superpowers/plans/2026-07-15-model-extraction-persistence.md`

**Interfaces:**
- Consumes: `TEST_POSTGRES_URL` or the repository PostgreSQL Docker service.
- Produces: execution evidence for SQLite, PostgreSQL, restart reload, rollback, API regression, and unchanged workbook-agent behavior.

- [ ] **Step 1: Add PostgreSQL migration/transaction acceptance coverage**

  Add `@pytest.mark.postgres` tests that use an isolated PostgreSQL test database and run Alembic to head before executing:

  ```text
  test_alembic_upgrades_postgres_database_to_persistence_head
  test_postgres_large_binary_round_trip_and_sha_dedupe
  test_postgres_t3_failure_rolls_back_every_canonical_child
  ```

  Skip only when no explicit test database URL is available; local completion requires providing one and observing PASS.

- [ ] **Step 2: Run the PostgreSQL acceptance suite and classify any dialect gaps**

  Run with the isolated URL:

  ```bash
  TEST_POSTGRES_URL='postgresql://investiq:investiq@127.0.0.1:5432/investiq_persistence_test' '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest -m postgres tests/test_model_extraction_persistence_schema.py tests/test_model_extraction_lifecycle.py -q
  ```

  Expected: tests either pass unchanged or expose a concrete dialect-specific DDL, transaction, or JSON serialization defect. Distinguish a test-environment failure from a product defect before changing production code. If the new tests pass immediately, record them as acceptance coverage and do not make an artificial production change.

- [ ] **Step 3: Apply minimal cross-dialect fixes and verify GREEN**

  Keep generic `Uuid(as_uuid=False)`, `JSON`, `LargeBinary`, named `CheckConstraint`, and `DateTime(timezone=True)`. Do not introduce PostgreSQL-only JSONB indexes or enums.

- [ ] **Step 4: Run full verification**

  Run:

  ```bash
  '/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3' -m pytest tests experiments/workbook_agent_poc/tests -q
  git diff --check
  git status --short --branch
  ```

  Required results:

  ```text
  all tests pass
  no diff whitespace errors
  no frontend, Calculation Rule Extraction, vector, legacy parser, or generated-result files changed
  ```

- [ ] **Step 5: Mark this plan's completed checkboxes and commit verification-only changes**

  ```bash
  git add tests/test_model_extraction_persistence_schema.py tests/test_model_extraction_lifecycle.py docs/superpowers/plans/2026-07-15-model-extraction-persistence.md
  git diff --cached --check
  git commit -m "test: verify model extraction persistence"
  ```

---

## Plan Self-Review Checklist

- [x] Every approved design section maps to an implementation task.
- [x] Every production behavior starts with a named failing test and an explicit RED command.
- [x] All signatures and field names are consistent across tasks.
- [x] No snapshot JSON appears in a downstream DTO or public reload API.
- [x] No provider type leaks through `WorkbookStorage`.
- [x] Parameter and series IDs share the `FinancialEntity` evolution seam.
- [x] T1/T2/T3 commit and rollback semantics match the lifecycle table.
- [x] SQLite and PostgreSQL verification are both required before completion.
- [x] No placeholder or deferred-scope implementation is included.
