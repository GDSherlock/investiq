"""FastAPI contract tests for the experimental workbook-agent upload route."""

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from apps.api.app.routers import models


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
    "validation_results",
    "warnings",
    "errors",
    "trace",
    "trace_truncated",
}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(models.router, prefix="/api/v1")
    return app


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


def test_openapi_marks_upload_as_experimental_workbook_agent_validation():
    operation = _app().openapi()["paths"]["/api/v1/models/upload"]["post"]

    assert "experimental" in operation["summary"].lower()
    assert "workbook-agent" in operation["summary"].lower()
    assert "synchronous" in operation["description"].lower()


@pytest.mark.parametrize("filename", ["legacy.xls", "data.csv", "book.xlsm", "notes.txt"])
def test_unsupported_formats_return_structured_415_without_running_agent(monkeypatch, filename):
    called = False

    def unexpected_agent_call(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("agent must not run for unsupported formats")

    monkeypatch.setattr(models, "run_workbook_validation", unexpected_agent_call, raising=False)
    client = TestClient(_app(), raise_server_exceptions=False)

    response = client.post("/api/v1/models/upload", files={"file": (filename, b"content")})

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "UNSUPPORTED_WORKBOOK_FORMAT"
    assert called is False


def test_empty_xlsx_returns_structured_400_without_running_agent(monkeypatch):
    monkeypatch.setattr(
        models,
        "run_workbook_validation",
        lambda *args, **kwargs: pytest.fail("agent must not run for an empty upload"),
        raising=False,
    )
    client = TestClient(_app(), raise_server_exceptions=False)

    response = client.post("/api/v1/models/upload", files={"file": ("empty.xlsx", b"")})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "EMPTY_FILE"


def test_success_returns_complete_raw_validation_contract(monkeypatch):
    monkeypatch.setattr(
        models,
        "run_workbook_validation",
        lambda file_bytes, filename: _result(filename),
        raising=False,
    )
    client = TestClient(_app(), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("benchmark.xlsx", b"validity is adapter-owned")},
    )

    assert response.status_code == 200
    assert REQUIRED_RESPONSE_FIELDS == set(response.json())
    assert response.json()["driver_meta"]["api"] == "responses"


def test_corrupt_xlsx_returns_structured_422():
    client = TestClient(_app(), raise_server_exceptions=False)

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
    monkeypatch, exception_name, status_code, error_code
):
    exception_type = getattr(models, exception_name)

    def fail(*args, **kwargs):
        raise exception_type("secret-value-must-not-escape")

    monkeypatch.setattr(models, "run_workbook_validation", fail, raising=False)
    client = TestClient(_app(), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/models/upload",
        files={"file": ("benchmark.xlsx", b"validity is adapter-owned")},
    )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == error_code
    assert "secret-value" not in response.text


def test_experimental_route_has_no_database_or_auth_dependency():
    route = _upload_route(_app())
    dependency_names = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if dependency.call is not None
    }

    assert "get_db" not in dependency_names
    assert "get_current_user" not in dependency_names
