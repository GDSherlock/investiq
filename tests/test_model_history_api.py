"""Contract tests for the canonical historical-model listing API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.calculation_rules.phase2_models import (
    CalculationGraphVersionRecord,
    CalculationRunRecord,
)
from apps.api.app.database import Base, get_db
from apps.api.app.main import app
from apps.api.app.model_extraction_models import ModelVersion
from apps.api.app.model_extraction_types import new_uuid
from tests.calculation_rule_test_support import create_materialized_rule_model
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


@pytest.fixture
def model_history_context(tmp_path: Path):
    database_path = tmp_path / "model-history.db"
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(database_path)
    )
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    setup = session_factory()
    try:
        _storage, workbook, older_model, *_rest = create_materialized_rule_model(
            setup
        )
        older_model.upload_filename = "older-model.xlsx"
        older_model.created_at = now - timedelta(days=3)

        newer_model = ModelVersion(
            id=new_uuid(),
            workbook_version_id=workbook.id,
            upload_filename="newer-model.xlsx",
            status="materialized",
            validation_status="validated_with_warning",
            submitted=True,
            created_at=now - timedelta(hours=1),
            completed_at=now - timedelta(minutes=50),
        )
        extracting_model = ModelVersion(
            id=new_uuid(),
            workbook_version_id=workbook.id,
            upload_filename="still-extracting.xlsx",
            status="extracting",
            validation_status="not_run",
            submitted=False,
            created_at=now,
        )
        graph = CalculationGraphVersionRecord(
            id=new_uuid(),
            workbook_version_id=workbook.id,
            compiler_version="test-compiler",
            ir_version="test-ir",
            function_registry_version="test-registry",
            semantics_profile="test-semantics",
            compiler_manifest_hash="a" * 64,
            content_fingerprint="b" * 64,
            node_count=0,
            edge_count=0,
            topological_layers_json=[],
            volatile_nodes_json=[],
            created_at=now - timedelta(minutes=45),
        )
        baseline_run = CalculationRunRecord(
            id=new_uuid(),
            model_version_id=newer_model.id,
            graph_version_id=graph.id,
            base_run_id=None,
            engine_version="test-engine",
            function_registry_version="test-registry",
            semantics_profile="test-semantics",
            normalized_override_hash="c" * 64,
            run_policy_hash="d" * 64,
            overrides_json=[],
            run_policy_json={},
            status="completed",
            summary_json={},
            warnings_json=[],
            started_at=now - timedelta(minutes=40),
            completed_at=now - timedelta(minutes=39),
            created_at=now - timedelta(minutes=40),
        )
        setup.add_all([newer_model, extracting_model, graph])
        setup.flush()
        setup.add(baseline_run)
        setup.commit()
        identifiers = {
            "newer_model_id": newer_model.id,
            "older_model_id": older_model.id,
            "extracting_model_id": extracting_model.id,
            "workbook_version_id": workbook.id,
            "graph_version_id": graph.id,
            "baseline_run_id": baseline_run.id,
        }
    finally:
        setup.close()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield {**identifiers, "client": client}
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_model_history_lists_only_materialized_models_newest_first(
    model_history_context,
) -> None:
    response = model_history_context["client"].get(
        "/api/v1/models?limit=20"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert [item["model_version_id"] for item in payload["models"]] == [
        model_history_context["newer_model_id"],
        model_history_context["older_model_id"],
    ]
    assert model_history_context["extracting_model_id"] not in str(payload)
    assert payload["models"][0]["filename"] == "newer-model.xlsx"
    assert payload["models"][1]["calculation_status"] == (
        "calculation_required"
    )


def test_model_history_reports_latest_completed_zero_override_run(
    model_history_context,
) -> None:
    response = model_history_context["client"].get(
        "/api/v1/models?limit=20"
    )

    assert response.status_code == 200
    item = response.json()["models"][0]
    assert item["calculation_status"] == "baseline_ready"
    assert item["baseline_run_id"] == model_history_context["baseline_run_id"]
    assert item["graph_version_id"] == model_history_context["graph_version_id"]
    assert item["workbook_version_id"] == (
        model_history_context["workbook_version_id"]
    )


def test_model_history_rejects_limits_outside_the_contract(
    model_history_context,
) -> None:
    client = model_history_context["client"]

    assert client.get("/api/v1/models?limit=0").status_code == 422
    assert client.get("/api/v1/models?limit=101").status_code == 422
