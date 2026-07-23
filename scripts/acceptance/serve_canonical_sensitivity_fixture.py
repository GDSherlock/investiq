"""Seed and serve the real two-model canonical sensitivity fixture.

Default mode keeps the FastAPI dependency override alive and serves via
uvicorn. ``--smoke-test`` exercises the browser-required routes through
FastAPI TestClient and exits.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from typing import Any

WORKTREE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE))

from fastapi.testclient import TestClient
from sqlalchemy import func, select
import uvicorn

from apps.api.app.calculation_rules.phase2_models import CalculationRunRecord
from apps.api.app.database import Base, get_db
from apps.api.app.main import app
from run_canonical_sensitivity_two_model import (
    _create_models,
    _sensitivity_payload,
)
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


DEFAULT_DATABASE_PATH = Path(
    "/tmp/investiq-canonical-sensitivity-browser-fixture.db"
)
DEFAULT_FIXTURE_PATH = Path(
    "/tmp/investiq-canonical-sensitivity-browser-fixture.json"
)
STORAGE_KEYS = {
    "workbook_version_id": "investiq_workbook_version_id",
    "model_version_id": "investiq_model_version_id",
    "graph_version_id": "investiq_calculation_graph_version_id",
    "baseline_run_id": "investiq_baseline_calculation_run_id",
    "current_run_id": "investiq_override_calculation_run_id",
    "workbench": "investiq_sensitivity_workbench:v2",
}


def _response_json(response, expected_status: int = 200) -> dict[str, Any]:
    assert response.status_code == expected_status, response.text
    return response.json()


def _post(
    client: TestClient,
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _response_json(client.post(path, json=payload))


def _target_key(parameter_id: str) -> str:
    return f"parameter:{parameter_id}"


def _seed_database(database_path: Path):
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(database_path)
    )
    Base.metadata.create_all(engine)
    with session_factory() as session:
        models = _create_models(session)
    return engine, session_factory, models


def _install_database_override(session_factory) -> None:
    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db


def _list_paginated_inputs(
    client: TestClient,
    model_version_id: str,
    *,
    limit: int = 1,
) -> tuple[list[dict[str, Any]], int]:
    inputs: list[dict[str, Any]] = []
    page_count = 0
    cursor = None
    while True:
        params: dict[str, Any] = {
            "target_kind": "parameter",
            "editable_only": "true",
            "limit": limit,
        }
        if cursor is not None:
            params["cursor"] = cursor
        page = _response_json(
            client.get(
                f"/api/v1/models/{model_version_id}/calculation/inputs",
                params=params,
            )
        )
        page_count += 1
        inputs.extend(page["inputs"])
        cursor = page["next_cursor"]
        if cursor is None:
            return inputs, page_count


def _prepare_model(
    client: TestClient,
    model: dict[str, Any],
) -> dict[str, Any]:
    model_id = model["model_version_id"]
    readiness = _post(
        client,
        f"/api/v1/models/{model_id}/calculation/prepare",
        {},
    )
    assert readiness["status"] in {"ready", "ready_with_warning"}
    model["graph_version_id"] = readiness["graph_version_id"]
    baseline = _post(
        client,
        f"/api/v1/models/{model_id}/calculations",
        {
            "graph_version_id": model["graph_version_id"],
            "overrides": [],
            "idempotency_key": None,
        },
    )
    sensitivity_request = _sensitivity_payload(model)
    sensitivity = _post(
        client,
        f"/api/v1/models/{model_id}/calculation/sensitivity",
        sensitivity_request,
    )
    assert (
        sensitivity["comparison_baseline_run_id"]
        == baseline["calculation_run_id"]
    )
    inputs, input_page_count = _list_paginated_inputs(client, model_id)
    outputs = _response_json(
        client.get(f"/api/v1/models/{model_id}/calculation/outputs")
    )
    current_projection = _response_json(
        client.get(
            f"/api/v1/calculation-runs/"
            f"{sensitivity['current_run_id']}/outputs"
        )
    )
    assert (
        current_projection["comparison_baseline_run_id"]
        == baseline["calculation_run_id"]
    )
    series = [
        output
        for output in outputs["outputs"]
        if output["entity_kind"] == "series"
    ]
    workbench_document = {
        "version": 2,
        "revision": f"fixture-{model_id}",
        "modelVersionId": model_id,
        "graphVersionId": model["graph_version_id"],
        "comparisonBaselineRunId": baseline["calculation_run_id"],
        "currentRunId": sensitivity["current_run_id"],
        "overridesByTarget": {
            _target_key(model["current_parameter_id"]): model["current_value"]
        },
        "tornadoDriverKeys": [
            _target_key(model["row_parameter_id"]),
            _target_key(model["column_parameter_id"]),
        ],
        "selectedOutputId": model["selected_output_id"],
        "rowDriverKey": _target_key(model["row_parameter_id"]),
        "columnDriverKey": _target_key(model["column_parameter_id"]),
    }
    local_storage_entries = {
        STORAGE_KEYS["workbook_version_id"]: model["workbook_version_id"],
        STORAGE_KEYS["model_version_id"]: model_id,
        STORAGE_KEYS["graph_version_id"]: model["graph_version_id"],
        STORAGE_KEYS["baseline_run_id"]: baseline["calculation_run_id"],
        STORAGE_KEYS["current_run_id"]: sensitivity["current_run_id"],
        STORAGE_KEYS["workbench"]: json.dumps(
            workbench_document,
            separators=(",", ":"),
            sort_keys=True,
        ),
    }
    return {
        "name": model["name"],
        "workbook_version_id": model["workbook_version_id"],
        "model_version_id": model_id,
        "graph_version_id": model["graph_version_id"],
        "baseline_run_id": baseline["calculation_run_id"],
        "current_run_id": sensitivity["current_run_id"],
        "assumptions": {
            "current_override_parameter_id": model["current_parameter_id"],
            "row_parameter_id": model["row_parameter_id"],
            "column_parameter_id": model["column_parameter_id"],
        },
        "selected_output_id": model["selected_output_id"],
        "unavailable_output_id": model["unavailable_output_id"],
        "canonical_series": {
            "exist": bool(series),
            "count": len(series),
            "output_ids": [output["output_id"] for output in series],
        },
        "editable_parameter_count": len(inputs),
        "input_pagination_pages_at_limit_1": input_page_count,
        "sensitivity_request": sensitivity_request,
        "sensitivity_response_ids": {
            "comparison_baseline_run_id": sensitivity[
                "comparison_baseline_run_id"
            ],
            "current_run_id": sensitivity["current_run_id"],
            "driver_run_ids": [
                {
                    "low": driver["low_case"]["calculation_run_id"],
                    "high": driver["high_case"]["calculation_run_id"],
                }
                for driver in sensitivity["drivers"]
            ],
            "matrix_run_ids": [
                cell["calculation_run_id"]
                for cell in sensitivity["two_way"]["cells"]
            ],
        },
        "recommended_workbench_document": workbench_document,
        "recommended_local_storage_entries": local_storage_entries,
    }


def _write_fixture_document(
    fixture_path: Path,
    *,
    host: str,
    port: int,
    database_path: Path,
    prepared_models: list[dict[str, Any]],
    primary_index: int,
) -> dict[str, Any]:
    primary = prepared_models[primary_index]
    document = {
        "schema_version": 1,
        "status": "ready",
        "server": {
            "host": host,
            "port": port,
            "base_url": f"http://{host}:{port}",
            "database_path": str(database_path),
            "frontend_api_proxy_target": f"http://{host}:{port}",
        },
        "primary_model": primary,
        "models": prepared_models,
        "browser_setup": {
            "route": "/sensitivity",
            "local_storage_entries": primary[
                "recommended_local_storage_entries"
            ],
            "workbench_document": primary[
                "recommended_workbench_document"
            ],
            "instructions": (
                "Set each local_storage_entries key/value in the frontend "
                "origin, then navigate to /sensitivity."
            ),
        },
        "limitations": [
            "Isolated SQLite fixture; not PostgreSQL acceptance.",
            "Fixture-backed models; not live upload or LLM extraction.",
            "Frontend same-origin API calls require API_PROXY_TARGET to point "
            "to this server.",
        ],
    }
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document


def _smoke_test(
    client: TestClient,
    session_factory,
    document: dict[str, Any],
) -> dict[str, Any]:
    primary = document["primary_model"]
    model_id = primary["model_version_id"]
    health = _response_json(client.get("/health"))
    readiness = _response_json(
        client.get(f"/api/v1/models/{model_id}/calculation/readiness")
    )
    assert readiness["status"] in {"ready", "ready_with_warning"}
    assert readiness["graph_version_id"] == primary["graph_version_id"]

    inputs, input_pages = _list_paginated_inputs(
        client,
        model_id,
        limit=1,
    )
    assert len(inputs) >= 3
    assert input_pages >= 3
    current_projection = _response_json(
        client.get(
            f"/api/v1/calculation-runs/{primary['current_run_id']}/outputs"
        )
    )
    assert current_projection["model_version_id"] == model_id
    assert (
        current_projection["comparison_baseline_run_id"]
        == primary["baseline_run_id"]
    )
    selected = next(
        output
        for output in current_projection["outputs"]
        if output["entity_kind"] == "scalar"
        and output["output_id"] == primary["selected_output_id"]
    )
    assert selected["current"]["availability_status"] == "available"

    with session_factory() as session:
        before = int(
            session.scalar(
                select(func.count()).select_from(CalculationRunRecord)
            )
            or 0
        )
    replay = _post(
        client,
        f"/api/v1/models/{model_id}/calculation/sensitivity",
        deepcopy(primary["sensitivity_request"]),
    )
    with session_factory() as session:
        after = int(
            session.scalar(
                select(func.count()).select_from(CalculationRunRecord)
            )
            or 0
        )
    assert replay["current_run_id"] == primary["current_run_id"]
    assert (
        replay["comparison_baseline_run_id"] == primary["baseline_run_id"]
    )
    assert after == before
    replay_projection = _response_json(
        client.get(
            f"/api/v1/calculation-runs/{replay['current_run_id']}/outputs"
        )
    )
    assert (
        replay_projection["calculation_run_id"]
        == primary["current_run_id"]
    )
    return {
        "health": health,
        "readiness": readiness["status"],
        "paginated_input_pages": input_pages,
        "editable_inputs": len(inputs),
        "current_projection_reloaded": True,
        "sensitivity_replay_current_run_id": replay["current_run_id"],
        "sensitivity_replay_created_runs": after - before,
        "sensitivity_replay_projection_reloaded": True,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=os.getenv("TWO_MODEL_FIXTURE_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("TWO_MODEL_FIXTURE_PORT", "18080")),
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
    )
    parser.add_argument(
        "--fixture-json",
        type=Path,
        default=DEFAULT_FIXTURE_PATH,
    )
    parser.add_argument(
        "--primary-model",
        choices=("first", "second"),
        default="first",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Exercise browser-required routes through TestClient and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    if args.host != "127.0.0.1":
        raise SystemExit("The fixture server is restricted to 127.0.0.1.")
    if not 1 <= args.port <= 65535:
        raise SystemExit("Port must be between 1 and 65535.")

    engine, session_factory, models = _seed_database(args.database)
    _install_database_override(session_factory)
    primary_index = 0 if args.primary_model == "first" else 1
    try:
        with TestClient(app) as client:
            prepared_models = [
                _prepare_model(client, model) for model in models
            ]
        document = _write_fixture_document(
            args.fixture_json,
            host=args.host,
            port=args.port,
            database_path=args.database,
            prepared_models=prepared_models,
            primary_index=primary_index,
        )
        if args.smoke_test:
            with TestClient(app) as client:
                smoke = _smoke_test(client, session_factory, document)
            print(json.dumps(smoke, sort_keys=True))
            print(args.fixture_json.resolve())
            return

        primary = document["primary_model"]
        print(
            json.dumps(
                {
                    "base_url": document["server"]["base_url"],
                    "fixture_json": str(args.fixture_json.resolve()),
                    "primary_model_version_id": primary["model_version_id"],
                    "primary_graph_version_id": primary["graph_version_id"],
                    "primary_baseline_run_id": primary["baseline_run_id"],
                    "primary_current_run_id": primary["current_run_id"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        try:
            uvicorn.run(
                app,
                host=args.host,
                port=args.port,
                log_level="info",
            )
        except KeyboardInterrupt:
            pass
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


if __name__ == "__main__":
    main()
