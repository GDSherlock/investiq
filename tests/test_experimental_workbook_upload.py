"""FastAPI contract tests for the experimental workbook-agent upload route."""

import inspect
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from apps.api.app.calculation_rules.models import CalculationRuleExtraction
from apps.api.app.calculation_rules.phase2_models import CalculationGraphVersionRecord
from apps.api.app.database import Base
from apps.api.app.model_extraction_read_service import ModelExtractionReadService
from apps.api.app.model_extraction_types import ModelExtractionPersistenceError
from apps.api.app.routers import models
from apps.api.app.workbook_storage import DatabaseWorkbookStorage
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    persistence_workbook_bytes,
    sqlite_file_url,
)


REQUIRED_RESPONSE_FIELDS = {
    "endpoint_mode",
    "filename",
    "runtime_seconds",
    "driver_meta",
    "submitted",
    "stop_reason",
    "coverage",
    "final_extraction",
    "validation_summary",
    "time_series_summary",
    "validation_results",
    "warnings",
    "errors",
    "trace",
    "trace_truncated",
    "workbook_version_id",
    "model_version_id",
}


def _app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(models.router, prefix="/api/v1")

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[models.get_db] = override_get_db
    return app


@pytest.fixture
def api_context(tmp_path):
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "api.db")
    )
    Base.metadata.create_all(engine)
    app = _app(session_factory)
    try:
        yield app, session_factory
    finally:
        engine.dispose()


def _result(filename: str = "benchmark.xlsx") -> dict:
    return {
        "endpoint_mode": "experimental_workbook_agent_validation",
        "filename": filename,
        "runtime_seconds": 1.25,
        "driver_meta": {
            "api": "responses",
            "deployment": "deterministic-test-driver",
            "prompt_tokens": 10,
            "completion_tokens": 5,
        },
        "submitted": True,
        "stop_reason": "submitted",
        "coverage": {"total_sheets": 1},
        "final_extraction": {"all_assumption_candidates": [], "output_candidates": []},
        "validation_summary": {
            "candidate_count": 0,
            "validated": 0,
            "validated_null": 0,
            "reclassified": 0,
            "review_required": 0,
            "rejected": 0,
        },
        "time_series_summary": {
            "submitted_descriptors": 0,
            "legacy_series_detected": 0,
            "submitted_series": 0,
            "materialized_series": 0,
            "validated_series": 0,
            "validated_with_warning": 0,
            "rejected_series": 0,
            "representative_cell_only": 0,
            "period_value_mismatches": 0,
            "duplicate_series": 0,
            "backend_range_reads": 0,
            "reclassified_series": 0,
        },
        "validation_results": [],
        "warnings": [],
        "errors": [],
        "trace": [],
        "trace_truncated": False,
    }


def _upload_route(app: FastAPI) -> APIRoute:
    return next(
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/v1/models/upload"
        and "POST" in route.methods
    )


def test_openapi_marks_upload_as_experimental_workbook_agent_validation(api_context):
    app, _session_factory = api_context
    operation = app.openapi()["paths"]["/api/v1/models/upload"]["post"]

    assert "experimental" in operation["summary"].lower()
    assert "workbook-agent" in operation["summary"].lower()
    assert "synchronous" in operation["description"].lower()


def test_upload_route_runs_as_a_sync_endpoint_off_the_event_loop(api_context):
    app, _session_factory = api_context

    assert inspect.iscoroutinefunction(_upload_route(app).endpoint) is False


@pytest.mark.parametrize("filename", ["legacy.xls", "data.csv", "book.xlsm", "notes.txt"])
def test_unsupported_formats_return_structured_415_without_running_agent(
    monkeypatch,
    filename,
    api_context,
):
    app, _session_factory = api_context
    called = False

    def unexpected_agent_call(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("agent must not run for unsupported formats")

    monkeypatch.setattr(models, "run_workbook_validation", unexpected_agent_call, raising=False)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/models/upload", files={"file": (filename, b"content")})

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "UNSUPPORTED_WORKBOOK_FORMAT"
    assert called is False


def test_empty_xlsx_returns_structured_400_without_running_agent(monkeypatch, api_context):
    app, _session_factory = api_context
    monkeypatch.setattr(
        models,
        "run_workbook_validation",
        lambda *args, **kwargs: pytest.fail("agent must not run for an empty upload"),
        raising=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/models/upload", files={"file": ("empty.xlsx", b"")})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "EMPTY_FILE"


def test_oversized_xlsx_returns_structured_413_without_running_agent(
    monkeypatch,
    api_context,
):
    app, _session_factory = api_context
    content = persistence_workbook_bytes()
    monkeypatch.setenv("MODEL_EXTRACTION_MAX_WORKBOOK_BYTES", str(len(content) - 1))
    monkeypatch.setattr(
        models,
        "run_workbook_validation",
        lambda *args, **kwargs: pytest.fail("agent must not run for an oversized upload"),
        raising=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("oversized.xlsx", content)},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "WORKBOOK_TOO_LARGE"


def test_success_returns_committed_workbook_and_model_version_ids(
    monkeypatch,
    api_context,
):
    app, _session_factory = api_context
    monkeypatch.setattr(
        models,
        "run_workbook_validation",
        lambda file_bytes, filename: _result(filename),
        raising=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("benchmark.xlsx", persistence_workbook_bytes())},
    )

    assert response.status_code == 200
    assert REQUIRED_RESPONSE_FIELDS == set(response.json())
    assert response.json()["driver_meta"]["api"] == "responses"
    assert UUID(response.json()["workbook_version_id"])
    assert UUID(response.json()["model_version_id"])


def test_successful_upload_prepares_rules_and_graph_before_return(
    monkeypatch,
    api_context,
):
    app, session_factory = api_context
    monkeypatch.setattr(
        models,
        "run_workbook_validation",
        lambda file_bytes, filename: _result(filename),
        raising=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("benchmark.xlsx", persistence_workbook_bytes())},
    )

    assert response.status_code == 200
    session = session_factory()
    try:
        extraction = session.scalar(select(CalculationRuleExtraction))
        graph = session.scalar(select(CalculationGraphVersionRecord))
        assert extraction is not None
        assert extraction.model_version_id == response.json()["model_version_id"]
        assert extraction.status in {"completed", "completed_with_warning"}
        assert graph is not None
        assert graph.workbook_version_id == response.json()["workbook_version_id"]
        assert session.scalar(
            select(func.count()).select_from(CalculationRuleExtraction)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(CalculationGraphVersionRecord)
        ) == 1
    finally:
        session.close()


def test_submitted_false_returns_null_version_ids(monkeypatch, api_context):
    app, _session_factory = api_context
    incomplete = _result()
    incomplete.update(
        submitted=False,
        stop_reason="model_returned_no_tool_call",
        errors=[{"code": "AGENT_INCOMPLETE", "message": "incomplete"}],
    )
    monkeypatch.setattr(
        models,
        "run_workbook_validation",
        lambda file_bytes, filename: {**incomplete, "filename": filename},
        raising=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("benchmark.xlsx", persistence_workbook_bytes())},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] is False
    assert response.json()["workbook_version_id"] is None
    assert response.json()["model_version_id"] is None


def test_corrupt_xlsx_returns_structured_422(api_context):
    app, _session_factory = api_context
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("broken.xlsx", b"not an OOXML workbook")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_XLSX"


@pytest.mark.parametrize(
    ("exception_name", "status_code", "error_code"),
    [
        ("AzureConfigurationError", 503, "AZURE_CONFIGURATION_ERROR"),
        ("AzureResponsesError", 502, "AZURE_RESPONSES_ERROR"),
        ("WorkbookValidationError", 500, "WORKBOOK_VALIDATION_ERROR"),
    ],
)
def test_adapter_errors_map_to_sanitized_http_errors(
    monkeypatch,
    exception_name,
    status_code,
    error_code,
    api_context,
):
    app, _session_factory = api_context
    exception_type = getattr(models, exception_name)

    def fail(*args, **kwargs):
        raise exception_type("secret-value-must-not-escape")

    monkeypatch.setattr(models, "run_workbook_validation", fail, raising=False)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("benchmark.xlsx", persistence_workbook_bytes())},
    )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == error_code
    assert "secret-value" not in response.text


def test_upload_route_has_database_but_not_auth_dependency(api_context):
    app, _session_factory = api_context
    route = _upload_route(app)
    dependency_names = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if dependency.call is not None
    }

    assert "get_db" in dependency_names
    assert "get_current_user" not in dependency_names


def test_persistence_failure_is_sanitized_and_not_returned_as_success(
    monkeypatch,
    api_context,
):
    app, _session_factory = api_context

    class FailingUploadOrchestrationService:
        def __init__(self, *args, **kwargs):
            pass

        def process_upload(self, file_bytes, filename):
            raise ModelExtractionPersistenceError("secret database details")

    monkeypatch.setattr(
        models,
        "ModelUploadOrchestrationService",
        FailingUploadOrchestrationService,
        raising=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("benchmark.xlsx", persistence_workbook_bytes())},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "MODEL_EXTRACTION_PERSISTENCE_ERROR"
    assert "secret database" not in response.text


def test_successful_upload_is_reloadable_after_request_session_closes(
    monkeypatch,
    api_context,
):
    app, session_factory = api_context
    monkeypatch.setattr(
        models,
        "run_workbook_validation",
        lambda file_bytes, filename: _result(filename),
        raising=False,
    )
    client = TestClient(app, raise_server_exceptions=False)
    content = persistence_workbook_bytes()

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("benchmark.xlsx", content)},
    )

    assert response.status_code == 200
    restarted_session = session_factory()
    try:
        read_service = ModelExtractionReadService(
            restarted_session,
            DatabaseWorkbookStorage(restarted_session),
        )
        model_version = read_service.load_model_version(
            response.json()["model_version_id"],
            expected_workbook_version_id=response.json()["workbook_version_id"],
        )
        workbook_version = read_service.load_workbook_version(
            response.json()["workbook_version_id"]
        )
        assert model_version.status == "materialized"
        assert workbook_version.content_bytes == content
    finally:
        restarted_session.close()


def test_dockerfile_packages_workbook_agent_source():
    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")

    assert "COPY experiments/workbook_agent_poc/ /app/experiments/workbook_agent_poc/" in dockerfile


def test_dockerfile_runs_alembic_before_uvicorn():
    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")

    assert "alembic -c apps/api/alembic.ini upgrade head" in dockerfile
    assert dockerfile.index("alembic -c apps/api/alembic.ini upgrade head") < dockerfile.index(
        "uvicorn apps.api.app.main:app"
    )
