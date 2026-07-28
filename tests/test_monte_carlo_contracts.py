from __future__ import annotations

from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect

from apps.api.app.schemas import MonteCarloRunCreateRequest


def _request() -> dict[str, object]:
    parameter_id = str(uuid.uuid4())
    return {
        "graph_version_id": str(uuid.uuid4()),
        "baseline_calculation_run_id": str(uuid.uuid4()),
        "current_calculation_run_id": str(uuid.uuid4()),
        "trial_count": 50_000,
        "random_seed": 42,
        "inputs": [
            {
                "parameter_id": parameter_id,
                "distribution_type": "normal",
                "distribution_parameters": {
                    "mean": 10.0,
                    "stddev": 1.0,
                },
            }
        ],
        "correlation_matrix": [[1.0]],
        "selected_output_roles": ["project_irr", "project_npv"],
        "idempotency_key": "mc-request-1",
    }


def test_monte_carlo_request_accepts_bounded_canonical_configuration() -> None:
    request = MonteCarloRunCreateRequest.model_validate(_request())

    assert request.trial_count == 50_000
    assert request.inputs[0].distribution_type == "normal"


def test_monte_carlo_request_rejects_duplicate_parameters() -> None:
    payload = _request()
    payload["inputs"] = [
        payload["inputs"][0],
        payload["inputs"][0],
    ]
    payload["correlation_matrix"] = [[1.0, 0.0], [0.0, 1.0]]

    with pytest.raises(ValidationError):
        MonteCarloRunCreateRequest.model_validate(payload)


def test_monte_carlo_request_rejects_invalid_matrix_and_trial_limit() -> None:
    invalid_matrix = _request()
    invalid_matrix["correlation_matrix"] = [[0.5]]
    with pytest.raises(ValidationError):
        MonteCarloRunCreateRequest.model_validate(invalid_matrix)

    too_many = _request()
    too_many["trial_count"] = 50_001
    with pytest.raises(ValidationError):
        MonteCarloRunCreateRequest.model_validate(too_many)


def test_monte_carlo_migration_creates_queue_configuration_and_artifact(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monte-carlo.db"
    config = Config(
        str(Path(__file__).parents[1] / "apps" / "api" / "alembic.ini")
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")
    script = ScriptDirectory.from_config(config)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        assert script.get_current_head() == "20260728_0009"
        assert {
            "monte_carlo_runs",
            "monte_carlo_input_configurations",
            "monte_carlo_result_artifacts",
        } <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
