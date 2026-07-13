# Experimental Workbook-Agent Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `POST /api/v1/models/upload` in the `Modelextratcion_test` worktree with a synchronous Swagger-first endpoint that runs the experimental Azure workbook agent and deterministic validator over uploaded `.xlsx` files.

**Architecture:** Keep the legacy production upload function in `models.py` but unregister it. A new API adapter imports the existing PoC modules, owns temporary-file cleanup and result assembly, and returns a typed raw validation envelope. The API image explicitly copies the PoC source so runtime behavior matches the worktree.

**Tech Stack:** FastAPI 0.115, Pydantic 2.7, openpyxl 3.1, OpenAI Responses API, pytest, Docker Compose.

## Global Constraints

- The route must be explicitly labelled `experimental workbook-agent validation endpoint` in OpenAPI.
- Support `.xlsx`; reject `.xls` and all other extensions with HTTP 415.
- Return `validation_summary`, `warnings`, `errors`, `trace_truncated`, and `driver_meta.api`.
- Do not create `Investment`, `FinancialModel`, `ModelAssumption`, or audit records.
- Do not vectorize or call the legacy parser, mapper, health report, or fixed sheet-name logic.
- Preserve legacy production code in an unregistered rollback-only function.
- Return complete extraction, coverage, deterministic validation results, and every trace event through Swagger.
- Use the repository environment at `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3` for Python verification; it has the locked `openpyxl==3.1.2` used by the API image.

---

### Task 1: Make Trace Truncation Explicit

**Files:**
- Create: `experiments/workbook_agent_poc/tests/test_agent_loop.py`
- Modify: `experiments/workbook_agent_poc/agent_loop.py`

**Interfaces:**
- Consumes: `run_loop(model, tools, caps=None, verbose=False) -> dict[str, Any]`
- Produces: every trace event has `result_preview: str` and `result_truncated: bool`.

- [ ] **Step 1: Write a failing trace metadata test**

Create a small fake tools object and driver whose tool result exceeds the preview limit, then assert:

```python
run = run_loop(driver, tools)
assert run["trace"][0]["result_preview"].endswith("…")
assert run["trace"][0]["result_truncated"] is True
```

Also test a short result produces `result_truncated is False`.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest experiments/workbook_agent_poc/tests/test_agent_loop.py -q
```

Expected: FAIL with missing `result_truncated`.

- [ ] **Step 3: Implement preview metadata**

Change the helper to return both the preview and truncation state:

```python
def _preview(result: Any, limit: int = 200) -> tuple[str, bool]:
    rendered = json.dumps(result, default=str, ensure_ascii=False)
    truncated = len(rendered) > limit
    return (rendered if not truncated else rendered[:limit] + "…", truncated)
```

When appending each trace event, store both returned values. Keep verbose logging on the string preview only.

- [ ] **Step 4: Verify GREEN and regressions**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest experiments/workbook_agent_poc/tests/test_agent_loop.py experiments/workbook_agent_poc/tests -q
```

Expected: all PoC tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add experiments/workbook_agent_poc/agent_loop.py experiments/workbook_agent_poc/tests/test_agent_loop.py
git commit -m "test: expose workbook trace truncation"
```

---

### Task 2: Add the Experimental Workbook Validation Adapter

**Files:**
- Create: `apps/api/app/workbook_validation.py`
- Create: `tests/test_workbook_validation.py`

**Interfaces:**
- Consumes: `WorkbookToolset`, `AzureDriver`, `run_loop`, `HardCaps`, and `validate_extraction` from `experiments/workbook_agent_poc`.
- Produces: `run_workbook_validation(file_bytes: bytes, filename: str, driver_factory: Callable[[], Any] = AzureDriver) -> dict[str, Any]`.
- Produces: `InvalidWorkbookError`, `AzureConfigurationError`, `AzureResponsesError`, and `WorkbookValidationError` with API-safe messages.

- [ ] **Step 1: Write failing adapter tests**

Use a valid benchmark fixture and a deterministic planned driver. Assert the adapter returns:

```python
assert result["endpoint_mode"] == "experimental_workbook_agent_validation"
assert result["driver_meta"]["api"] == "responses"
assert result["coverage"]["total_sheets"] > 0
assert "final_extraction" in result
assert "validation_results" in result
assert result["validation_summary"]["candidate_count"] == len(result["validation_results"])
assert isinstance(result["warnings"], list)
assert isinstance(result["errors"], list)
assert result["trace_truncated"] == any(e["result_truncated"] for e in result["trace"])
```

Use `monkeypatch` on `tempfile.NamedTemporaryFile` cleanup observation or a captured temporary path to prove the file no longer exists after both success and an induced driver exception. Assert a driver that returns no final submission yields HTTP-neutral result data with `AGENT_INCOMPLETE` in `errors`.

- [ ] **Step 2: Run the adapter tests and verify RED**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest tests/test_workbook_validation.py -q
```

Expected: collection fails because `apps.api.app.workbook_validation` does not exist.

- [ ] **Step 3: Implement the adapter**

The adapter must:

```python
def run_workbook_validation(file_bytes, filename, driver_factory=AzureDriver):
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="investiq-workbook-") as temp_dir:
        path = Path(temp_dir) / "uploaded.xlsx"
        path.write_bytes(file_bytes)
        tools = WorkbookToolset(file_path=str(path))
        driver = driver_factory()
        run = run_loop(driver, tools, caps=HardCaps())
        results = validate_extraction(tools, run["final_extraction"])
        summary = summarize_validation(results)
        errors = [] if run["submitted"] else [{
            "code": "AGENT_INCOMPLETE",
            "message": f"Workbook agent stopped before submission: {run['stop_reason']}",
        }]
        return {
            "endpoint_mode": "experimental_workbook_agent_validation",
            "filename": filename,
            "runtime_seconds": round(time.monotonic() - started, 2),
            "driver_meta": {
                "api": "responses",
                "deployment": getattr(driver, "deployment", os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-5.4-mini")),
                "prompt_tokens": getattr(driver, "usage_prompt", 0),
                "completion_tokens": getattr(driver, "usage_completion", 0),
            },
            "submitted": run["submitted"],
            "stop_reason": run["stop_reason"],
            "coverage": run["coverage"],
            "final_extraction": run["final_extraction"],
            "validation_summary": summary,
            "validation_results": results,
            "warnings": collect_warnings(results),
            "errors": errors,
            "trace": run["trace"],
            "trace_truncated": any(e.get("result_truncated", False) for e in run["trace"]),
        }
```

Add the PoC directory to `sys.path` from the repository root without copying its implementation. Catch `openpyxl`/ZIP workbook load failures as `InvalidWorkbookError`; missing Azure environment keys as `AzureConfigurationError`; OpenAI client/API exceptions as `AzureResponsesError`; and other local validation failures as `WorkbookValidationError`. Sanitize error strings so environment values are never returned.

- [ ] **Step 4: Verify GREEN and adapter regressions**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest tests/test_workbook_validation.py experiments/workbook_agent_poc/tests -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add apps/api/app/workbook_validation.py tests/test_workbook_validation.py
git commit -m "feat: add experimental workbook validation adapter"
```

---

### Task 3: Replace the Upload Route Without Deleting Legacy Code

**Files:**
- Create: `tests/test_experimental_workbook_upload.py`
- Modify: `apps/api/app/schemas.py`
- Modify: `apps/api/app/routers/models.py`

**Interfaces:**
- Consumes: `run_workbook_validation(file_bytes, filename) -> dict[str, Any]` and adapter exception types.
- Produces: `POST /api/v1/models/upload` with `WorkbookValidationResponse`.

- [ ] **Step 1: Write failing route contract tests**

Build a small FastAPI test app with `models.router` and monkeypatch the adapter call. Assert:

```python
route = app.openapi()["paths"]["/api/v1/models/upload"]["post"]
assert "experimental" in route["summary"].lower()

assert client.post("/api/v1/models/upload", files={"file": ("old.xls", b"x")}).status_code == 415
assert client.post("/api/v1/models/upload", files={"file": ("bad.csv", b"x")}).status_code == 415
assert client.post("/api/v1/models/upload", files={"file": ("empty.xlsx", b"")}).status_code == 400
```

For a successful monkeypatched adapter result, assert the response exposes every required top-level field. For adapter exceptions, assert `422`, `503`, `502`, and `500` map to structured `detail.code` values.

Assert route dependencies do not include `get_db` or `get_current_user`, and monkeypatch legacy parser/vector functions to raise if called.

- [ ] **Step 2: Run route tests and verify RED**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest tests/test_experimental_workbook_upload.py -q
```

Expected: FAIL because the current route still advertises and executes legacy production upload behavior.

- [ ] **Step 3: Add the response schema**

Add a Pydantic model containing the exact response fields:

```python
class WorkbookValidationResponse(BaseModel):
    endpoint_mode: str
    filename: str
    runtime_seconds: float
    driver_meta: dict[str, Any]
    submitted: bool
    stop_reason: str
    coverage: dict[str, Any]
    final_extraction: dict[str, Any]
    validation_summary: dict[str, int]
    validation_results: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    trace_truncated: bool
```

- [ ] **Step 4: Register the experimental route and retain legacy code**

Move the route decorator to a new handler:

```python
@router.post(
    "/models/upload",
    response_model=WorkbookValidationResponse,
    summary="Experimental workbook-agent validation endpoint",
    description="Synchronously runs Azure Responses API workbook exploration and deterministic validation for benchmark testing.",
)
async def upload_model_experimental(file: UploadFile = File(...)):
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise api_error(415, "UNSUPPORTED_WORKBOOK_FORMAT", "Only .xlsx is supported; legacy .xls is not reliably readable.")
    file_bytes = await file.read()
    if not file_bytes:
        raise api_error(400, "EMPTY_FILE", "Uploaded workbook is empty.")
    try:
        return run_workbook_validation(file_bytes, filename)
    except InvalidWorkbookError:
        raise api_error(422, "INVALID_XLSX", "The upload is not a readable OOXML workbook.")
    # map remaining adapter exception types without leaking secrets
```

Rename the old handler `_legacy_upload_model_for_rollback` and leave its body and production imports intact without a route decorator.

- [ ] **Step 5: Verify GREEN and API regressions**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest tests/test_experimental_workbook_upload.py tests/test_workbook_validation.py experiments/workbook_agent_poc/tests -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add apps/api/app/schemas.py apps/api/app/routers/models.py tests/test_experimental_workbook_upload.py
git commit -m "feat: replace upload with workbook agent validation"
```

---

### Task 4: Package and Verify the Live Docker API

**Files:**
- Modify: `apps/api/Dockerfile`
- Modify: `experiments/workbook_agent_poc/README.md`
- Test: `tests/test_experimental_workbook_upload.py`

**Interfaces:**
- Consumes: PoC source at `experiments/workbook_agent_poc/`.
- Produces: API image path `/app/experiments/workbook_agent_poc/` and documented Swagger workflow.

- [ ] **Step 1: Add a failing Dockerfile contract assertion**

Add a source-level test:

```python
dockerfile = Path("apps/api/Dockerfile").read_text()
assert "COPY experiments/workbook_agent_poc/ /app/experiments/workbook_agent_poc/" in dockerfile
```

Run the route test and verify RED because the COPY line is absent.

- [ ] **Step 2: Package the PoC and document the endpoint**

Add this Dockerfile line before copying the API app:

```dockerfile
COPY experiments/workbook_agent_poc/ /app/experiments/workbook_agent_poc/
```

Update the PoC README to state that this worktree intentionally wires it to `POST /api/v1/models/upload`, supports `.xlsx` only, and is tested through `/docs`.

- [ ] **Step 3: Run the full local test suite**

Run:

```bash
"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 4: Rebuild only the API service**

Run from the linked worktree:

```bash
docker compose build --no-cache api
docker compose up -d --force-recreate api
docker compose ps api
```

Expected: `modelextratcion_test-api-1` is running on port 8000.

- [ ] **Step 5: Verify runtime provenance and OpenAPI**

Run:

```bash
docker inspect modelextratcion_test-api-1 --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/openapi.json
```

Expected: the Compose working directory is the `Modelextratcion_test` path; health is successful; the upload operation summary contains `Experimental workbook-agent validation endpoint` and the response schema contains all required fields.

- [ ] **Step 6: Perform a no-cost manual upload contract check**

Use a monkeypatch-free local fixture only if Azure credentials are intentionally available; otherwise stop before a paid Azure call and report Swagger readiness. When authorized, upload one benchmark fixture through `/docs` and verify the returned deployment, extraction, coverage, validation summary, trace, warnings, and errors.

- [ ] **Step 7: Commit Task 4**

```bash
git add apps/api/Dockerfile experiments/workbook_agent_poc/README.md tests/test_experimental_workbook_upload.py
git commit -m "build: package workbook agent in API image"
```

---

### Final Verification

- [ ] Run `git diff --check`.
- [ ] Run `"/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3" -m pytest -q` and record pass/fail counts.
- [ ] Confirm `git status --short` contains only pre-existing unrelated user changes.
- [ ] Confirm the live API container source matches the worktree and OpenAPI advertises the experimental contract.
- [ ] Do not claim a real Azure workbook result unless a real upload was executed successfully in this run.
