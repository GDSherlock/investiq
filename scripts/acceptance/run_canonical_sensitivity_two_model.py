"""Executable two-model canonical sensitivity acceptance harness.

It intentionally reuses the repository test fixture factories and drives the
real FastAPI, SQLAlchemy, calculation, persistence, output-projection, and
sensitivity paths.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any

WORKTREE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE))

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select

from apps.api.app.calculation_rules.phase2_models import CalculationRunRecord
from apps.api.app.database import Base, get_db
from apps.api.app.main import app
from apps.api.app.model_extraction_models import (
    CanonicalOutput,
    ModelParameter,
    ModelVersion,
)
from apps.api.app.model_extraction_repository import WorkbookVersionRepository
from apps.api.app.model_extraction_types import FinancialEntityIdFactory, new_uuid
from apps.api.app.workbook_storage import DatabaseWorkbookStorage
from tests.calculation_rule_test_support import (
    calculation_workbook_bytes,
    create_materialized_rule_model,
)
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


EVIDENCE_PATH = (
    WORKTREE
    / "docs/reports/evidence/canonical-sensitivity-two-model.json"
)
DATABASE_PATH = Path("/tmp/investiq-task-6-two-model-acceptance.db")
FORBIDDEN_REQUEST_KEYS = {
    "label",
    "sheet_name",
    "cell_address",
    "source_sheet",
    "source_cell",
}


def _second_workbook_bytes() -> bytes:
    workbook = load_workbook(BytesIO(calculation_workbook_bytes()))
    workbook["Inputs"]["A1"] = 7
    workbook["Inputs"]["A2"] = 11
    workbook["Calc"]["B2"] = "=B1*3"
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def _add_parameter(
    session,
    model_id: str,
    *,
    source_sheet: str,
    source_cell: str,
    value: int,
    label: str,
) -> ModelParameter:
    parameter = ModelParameter(
        id=FinancialEntityIdFactory(model_id).parameter_id(
            source_sheet,
            source_cell,
        ),
        model_version_id=model_id,
        entity_kind="parameter",
        source_bucket="parameter_candidates",
        label=label,
        submitted_role="hardcoded_input",
        validated_role="hardcoded_input",
        raw_value_json=value,
        validated_value_json=value,
        source_sheet=source_sheet,
        source_cell=source_cell,
        formula_status="static_value",
        source_validation_status="validated",
        role_validation_status="validated",
        validation_status="validated",
        data_type="n",
        number_format="General",
    )
    session.add(parameter)
    return parameter


def _add_output(
    session,
    model_id: str,
    *,
    source_cell: str,
    label: str,
    business_role: str,
    exact_formula: str,
) -> CanonicalOutput:
    output = CanonicalOutput(
        id=FinancialEntityIdFactory(model_id).output_id("Calc", source_cell),
        model_version_id=model_id,
        entity_kind="canonical_output",
        llm_candidate_alias=business_role,
        label=label,
        category="summary",
        canonical_name=label,
        business_role=business_role,
        submitted_role="formula_output",
        validated_role="formula_output",
        raw_value_json=None,
        unit="USD",
        scenario="base",
        source_sheet="Calc",
        source_cell=source_cell,
        exact_formula=exact_formula,
        formula_status="formula_no_cache",
        source_validation_status="validated",
        role_validation_status="validated",
        validation_status="validated",
        data_type="f",
        number_format="General",
        validation_warnings_json=[],
    )
    session.add(output)
    return output


def _create_models(session) -> list[dict[str, Any]]:
    (
        _storage,
        first_workbook,
        first_model,
        first_row_parameter,
        _series,
        _series_value,
    ) = create_materialized_rule_model(session)
    first_column_parameter = _add_parameter(
        session,
        first_model.id,
        source_sheet="Inputs",
        source_cell="A2",
        value=3,
        label="First unit price",
    )
    first_current_parameter = _add_parameter(
        session,
        first_model.id,
        source_sheet="Calc",
        source_cell="A1",
        value=2026,
        label="First reporting year",
    )
    first_unavailable_output = _add_output(
        session,
        first_model.id,
        source_cell="B5",
        label="First circular metric",
        business_role="unclassified",
        exact_formula="=B6+1",
    )

    storage = DatabaseWorkbookStorage(session)
    second_workbook = WorkbookVersionRepository(session, storage).get_or_create(
        _second_workbook_bytes(),
        "second-calculation-rules.xlsx",
    )
    second_model = ModelVersion(
        id=new_uuid(),
        workbook_version_id=second_workbook.id,
        upload_filename="second-calculation-rules.xlsx",
        status="materialized",
        validation_status="validated",
        submitted=True,
        extraction_snapshot_json={"acceptance_fixture": "second-model"},
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    session.add(second_model)
    session.flush()
    second_row_parameter = _add_parameter(
        session,
        second_model.id,
        source_sheet="Inputs",
        source_cell="A2",
        value=11,
        label="Second unit volume",
    )
    second_column_parameter = _add_parameter(
        session,
        second_model.id,
        source_sheet="Inputs",
        source_cell="A1",
        value=7,
        label="Second unit price",
    )
    second_current_parameter = _add_parameter(
        session,
        second_model.id,
        source_sheet="Calc",
        source_cell="A2",
        value=2027,
        label="Second reporting year",
    )
    second_selected_output = _add_output(
        session,
        second_model.id,
        source_cell="B2",
        label="Second model total",
        business_role="total_project_cost",
        exact_formula="=B1*3",
    )
    second_unavailable_output = _add_output(
        session,
        second_model.id,
        source_cell="B5",
        label="Second circular metric",
        business_role="unclassified",
        exact_formula="=B6+1",
    )
    session.commit()

    first_selected_output_id = FinancialEntityIdFactory(
        first_model.id
    ).output_id("Calc", "B1")
    return [
        {
            "name": "first_model",
            "workbook_version_id": first_workbook.id,
            "model_version_id": first_model.id,
            "selected_output_id": first_selected_output_id,
            "selected_output_source": {"sheet": "Calc", "cell": "B1"},
            "unavailable_output_id": first_unavailable_output.id,
            "row_parameter_id": first_row_parameter.id,
            "row_parameter_source": {"sheet": "Inputs", "cell": "A1"},
            "column_parameter_id": first_column_parameter.id,
            "column_parameter_source": {"sheet": "Inputs", "cell": "A2"},
            "current_parameter_id": first_current_parameter.id,
            "current_parameter_source": {"sheet": "Calc", "cell": "A1"},
            "current_value": "2030",
            "row_low": "1",
            "row_high": "4",
            "column_low": "2",
            "column_high": "5",
            "row_axis": ["1", "2", "4"],
            "column_axis": ["2", "3", "5"],
        },
        {
            "name": "second_model",
            "workbook_version_id": second_workbook.id,
            "model_version_id": second_model.id,
            "selected_output_id": second_selected_output.id,
            "selected_output_source": {"sheet": "Calc", "cell": "B2"},
            "unavailable_output_id": second_unavailable_output.id,
            "row_parameter_id": second_row_parameter.id,
            "row_parameter_source": {"sheet": "Inputs", "cell": "A2"},
            "column_parameter_id": second_column_parameter.id,
            "column_parameter_source": {"sheet": "Inputs", "cell": "A1"},
            "current_parameter_id": second_current_parameter.id,
            "current_parameter_source": {"sheet": "Calc", "cell": "A2"},
            "current_value": "2032",
            "row_low": "8",
            "row_high": "14",
            "column_low": "5",
            "column_high": "9",
            "row_axis": ["8", "11", "14"],
            "column_axis": ["5", "7", "9"],
        },
    ]


def _collect_keys_and_strings(
    value: Any,
    *,
    keys: set[str],
    strings: set[str],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            _collect_keys_and_strings(child, keys=keys, strings=strings)
    elif isinstance(value, list):
        for child in value:
            _collect_keys_and_strings(child, keys=keys, strings=strings)
    elif isinstance(value, str):
        strings.add(value)


def _assert_canonical_request(
    payload: dict[str, Any],
    *,
    known_labels: set[str],
) -> None:
    keys: set[str] = set()
    strings: set[str] = set()
    _collect_keys_and_strings(payload, keys=keys, strings=strings)
    assert not FORBIDDEN_REQUEST_KEYS.intersection(keys)
    assert not known_labels.intersection(strings)
    assert not {"A1", "A2", "B1", "B2", "B5", "Calc", "Inputs"}.intersection(
        strings
    )


def _number(value: str) -> dict[str, str]:
    return {"value_type": "number", "value": value}


def _target(parameter_id: str) -> dict[str, str]:
    return {"kind": "parameter", "parameter_id": parameter_id}


def _sensitivity_payload(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_version_id": model["graph_version_id"],
        "output_id": model["selected_output_id"],
        "current_overrides": [
            {
                "target": _target(model["current_parameter_id"]),
                "value": _number(model["current_value"]),
            }
        ],
        "drivers": [
            {
                "target": _target(model["row_parameter_id"]),
                "low": _number(model["row_low"]),
                "high": _number(model["row_high"]),
            },
            {
                "target": _target(model["column_parameter_id"]),
                "low": _number(model["column_low"]),
                "high": _number(model["column_high"]),
            },
        ],
        "two_way": {
            "row": {
                "target": _target(model["row_parameter_id"]),
                "values": [_number(value) for value in model["row_axis"]],
            },
            "column": {
                "target": _target(model["column_parameter_id"]),
                "values": [_number(value) for value in model["column_axis"]],
            },
        },
    }


def _json(response, expected_status: int = 200) -> dict[str, Any]:
    assert response.status_code == expected_status, response.text
    return response.json()


def _post(
    client: TestClient,
    url: str,
    payload: dict[str, Any],
    *,
    known_labels: set[str],
    audited_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    _assert_canonical_request(payload, known_labels=known_labels)
    audited_requests.append(
        {
            "method": "POST",
            "path_template": url,
            "payload_keys": sorted(payload),
        }
    )
    return _json(client.post(url, json=payload))


def _run_count(session_factory) -> int:
    with session_factory() as session:
        return int(
            session.scalar(select(func.count()).select_from(CalculationRunRecord))
            or 0
        )


def _list_all_inputs(
    client: TestClient,
    model_version_id: str,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for target_kind in ("parameter", "financial_series_value"):
        cursor = None
        while True:
            params: dict[str, Any] = {
                "target_kind": target_kind,
                "editable_only": "true",
                "limit": 2,
            }
            if cursor is not None:
                params["cursor"] = cursor
            page = _json(
                client.get(
                    f"/api/v1/models/{model_version_id}/calculation/inputs",
                    params=params,
                )
            )
            collected.extend(
                item
                for item in page["inputs"]
                if item["editable"]
                and item["current_value"]["value_type"] == "number"
            )
            cursor = page["next_cursor"]
            if cursor is None:
                break
    return collected


def _expected_case_outputs(
    sensitivity: dict[str, Any],
) -> list[dict[str, Any]]:
    expected = [
        {
            "kind": "current",
            "run_id": sensitivity["current_run_id"],
            "output": sensitivity["selected_output"]["current"],
        }
    ]
    for index, driver in enumerate(sensitivity["drivers"]):
        for endpoint in ("low_case", "high_case"):
            case = driver[endpoint]
            expected.append(
                {
                    "kind": f"driver_{index}_{endpoint}",
                    "run_id": case["calculation_run_id"],
                    "output": case["output"],
                }
            )
    assert sensitivity["two_way"] is not None
    for index, cell in enumerate(sensitivity["two_way"]["cells"]):
        expected.append(
            {
                "kind": f"matrix_{index}",
                "run_id": cell["calculation_run_id"],
                "output": cell["output"],
            }
        )
    return expected


def _reload_case(
    client: TestClient,
    session_factory,
    model: dict[str, Any],
    baseline_run_id: str,
    expected: dict[str, Any],
) -> dict[str, Any]:
    run = _json(
        client.get(f"/api/v1/calculation-runs/{expected['run_id']}")
    )
    projection = _json(
        client.get(f"/api/v1/calculation-runs/{expected['run_id']}/outputs")
    )
    selected = next(
        output
        for output in projection["outputs"]
        if output["entity_kind"] == "scalar"
        and output["output_id"] == model["selected_output_id"]
    )
    with session_factory() as session:
        persisted = session.get(CalculationRunRecord, expected["run_id"])
        assert persisted is not None
        persisted_status = persisted.status
    assert run["calculation_run_id"] == expected["run_id"]
    assert run["model_version_id"] == model["model_version_id"]
    assert projection["comparison_baseline_run_id"] == baseline_run_id
    assert selected["current"] == expected["output"]
    return {
        "kind": expected["kind"],
        "run_id": expected["run_id"],
        "persisted": True,
        "status": persisted_status,
        "run_reload_matches": True,
        "selected_output_reload_matches": True,
        "comparison_baseline_matches": True,
    }


def _accept_model(
    client: TestClient,
    session_factory,
    model: dict[str, Any],
    *,
    known_labels: set[str],
    audited_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    model_id = model["model_version_id"]
    prepared = _post(
        client,
        f"/api/v1/models/{model_id}/calculation/prepare",
        {},
        known_labels=known_labels,
        audited_requests=audited_requests,
    )
    assert prepared["status"] in {"ready", "ready_with_warning"}
    model["graph_version_id"] = prepared["graph_version_id"]

    baseline_request = {
        "graph_version_id": model["graph_version_id"],
        "overrides": [],
        "idempotency_key": None,
    }
    baseline = _post(
        client,
        f"/api/v1/models/{model_id}/calculations",
        baseline_request,
        known_labels=known_labels,
        audited_requests=audited_requests,
    )
    baseline_run_id = baseline["calculation_run_id"]
    with session_factory() as session:
        persisted_baseline = session.get(CalculationRunRecord, baseline_run_id)
        assert persisted_baseline is not None
        assert persisted_baseline.overrides_json == []
    baseline_reload = _json(
        client.get(f"/api/v1/calculation-runs/{baseline_run_id}")
    )
    baseline_projection = _json(
        client.get(f"/api/v1/calculation-runs/{baseline_run_id}/outputs")
    )
    assert baseline_reload["calculation_run_id"] == baseline_run_id
    assert baseline_projection["comparison_baseline_run_id"] == baseline_run_id

    inputs = _list_all_inputs(client, model_id)
    input_ids = {item["target_id"] for item in inputs}
    required_input_ids = {
        model["row_parameter_id"],
        model["column_parameter_id"],
        model["current_parameter_id"],
    }
    assert required_input_ids.issubset(input_ids)
    outputs = _json(
        client.get(f"/api/v1/models/{model_id}/calculation/outputs")
    )["outputs"]
    scalar_outputs = [
        output for output in outputs if output["entity_kind"] == "scalar"
    ]
    selected_definition = next(
        output
        for output in scalar_outputs
        if output["output_id"] == model["selected_output_id"]
    )
    assert selected_definition["source"] == {
        **selected_definition["source"],
        "sheet_name": model["selected_output_source"]["sheet"],
        "cell_address": model["selected_output_source"]["cell"],
    }

    sensitivity_request = _sensitivity_payload(model)
    count_before = _run_count(session_factory)
    sensitivity = _post(
        client,
        f"/api/v1/models/{model_id}/calculation/sensitivity",
        sensitivity_request,
        known_labels=known_labels,
        audited_requests=audited_requests,
    )
    count_after_first = _run_count(session_factory)
    assert sensitivity["comparison_baseline_run_id"] == baseline_run_id
    assert len(sensitivity["drivers"]) == 2
    assert sensitivity["two_way"] is not None
    assert len(sensitivity["two_way"]["cells"]) == 9
    assert [
        (cell["row_value"]["value"], cell["column_value"]["value"])
        for cell in sensitivity["two_way"]["cells"]
    ] == [
        (row_value, column_value)
        for row_value in model["row_axis"]
        for column_value in model["column_axis"]
    ]

    expected_cases = _expected_case_outputs(sensitivity)
    assert len(expected_cases) == 14
    assert len({case["run_id"] for case in expected_cases}) == 14
    reload_checks = [
        _reload_case(
            client,
            session_factory,
            model,
            baseline_run_id,
            expected,
        )
        for expected in expected_cases
    ]

    current_projection = _json(
        client.get(
            f"/api/v1/calculation-runs/{sensitivity['current_run_id']}/outputs"
        )
    )
    unavailable = next(
        output
        for output in current_projection["outputs"]
        if output["entity_kind"] == "scalar"
        and output["output_id"] == model["unavailable_output_id"]
    )
    unavailable_current = unavailable["current"]
    assert unavailable_current["availability_status"] == "unavailable"
    assert unavailable_current["value"] is None
    assert isinstance(unavailable_current["unavailable_reason"], str)
    assert unavailable_current["unavailable_reason"]

    replay = _post(
        client,
        f"/api/v1/models/{model_id}/calculation/sensitivity",
        deepcopy(sensitivity_request),
        known_labels=known_labels,
        audited_requests=audited_requests,
    )
    count_after_replay = _run_count(session_factory)
    assert replay == sensitivity
    assert count_after_replay == count_after_first

    driver_cases = []
    for driver in sensitivity["drivers"]:
        driver_cases.append(
            {
                "target": driver["target"],
                "low_run_id": driver["low_case"]["calculation_run_id"],
                "high_run_id": driver["high_case"]["calculation_run_id"],
                "low_output": driver["low_case"]["output"],
                "high_output": driver["high_case"]["output"],
                "impact": driver["impact"],
            }
        )
    matrix = [
        {
            "index": index,
            "row_value": cell["row_value"]["value"],
            "column_value": cell["column_value"]["value"],
            "run_id": cell["calculation_run_id"],
            "output": cell["output"],
        }
        for index, cell in enumerate(sensitivity["two_way"]["cells"])
    ]
    return {
        "name": model["name"],
        "workbook_version_id": model["workbook_version_id"],
        "model_version_id": model_id,
        "graph_version_id": model["graph_version_id"],
        "canonical_mappings": {
            "selected_row_parameter": {
                "parameter_id": model["row_parameter_id"],
                "source": model["row_parameter_source"],
            },
            "second_driver_parameter": {
                "parameter_id": model["column_parameter_id"],
                "source": model["column_parameter_source"],
            },
            "current_override_parameter": {
                "parameter_id": model["current_parameter_id"],
                "source": model["current_parameter_source"],
            },
            "selected_scalar_output": {
                "output_id": model["selected_output_id"],
                "source": model["selected_output_source"],
                "formula_cell_id": selected_definition["source"][
                    "formula_cell_id"
                ],
            },
        },
        "editable_numeric_inputs": inputs,
        "scalar_outputs": scalar_outputs,
        "baseline": {
            "run_id": baseline_run_id,
            "zero_override": True,
            "persisted": True,
            "reload_matches": True,
            "summary": baseline["summary"],
        },
        "current": {
            "run_id": sensitivity["current_run_id"],
            "selected_output": sensitivity["selected_output"]["current"],
        },
        "comparison_baseline_run_id": sensitivity[
            "comparison_baseline_run_id"
        ],
        "driver_cases": driver_cases,
        "matrix_cells_row_major": matrix,
        "persisted_reload_checks": reload_checks,
        "unavailable_output_sample": {
            "output_id": unavailable["output_id"],
            "availability_status": unavailable_current["availability_status"],
            "value": unavailable_current["value"],
            "unavailable_reason": unavailable_current["unavailable_reason"],
            "execution_status": unavailable_current["execution_status"],
            "engine_error_code": unavailable_current["engine_error_code"],
            "warnings": unavailable_current["warnings"],
        },
        "replay": {
            "response_equal": True,
            "run_ids_equal": [
                case["run_id"] for case in expected_cases
            ]
            == [
                case["run_id"] for case in _expected_case_outputs(replay)
            ],
            "run_count_before_sensitivity": count_before,
            "run_count_after_first": count_after_first,
            "run_count_after_replay": count_after_replay,
            "runs_created_by_first_request": count_after_first - count_before,
            "no_run_count_increase": count_after_replay == count_after_first,
        },
        "totals": {
            "editable_numeric_inputs": len(inputs),
            "scalar_outputs": len(scalar_outputs),
            "drivers": len(driver_cases),
            "matrix_cells": len(matrix),
            "returned_case_ids": len(expected_cases),
            "unique_returned_case_ids": len(
                {case["run_id"] for case in expected_cases}
            ),
            "persisted_reload_checks": len(reload_checks),
        },
    }


def main() -> None:
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(DATABASE_PATH)
    )
    Base.metadata.create_all(engine)
    with session_factory() as setup:
        models = _create_models(setup)
        known_labels = {
            label
            for label in setup.scalars(select(ModelParameter.label)).all()
            if label
        }
        known_labels.update(
            label
            for label in setup.scalars(select(CanonicalOutput.label)).all()
            if label
        )

    assert models[0]["workbook_version_id"] != models[1]["workbook_version_id"]
    assert models[0]["model_version_id"] != models[1]["model_version_id"]
    assert models[0]["row_parameter_id"] != models[1]["row_parameter_id"]
    assert models[0]["row_parameter_source"] != models[1]["row_parameter_source"]
    assert models[0]["selected_output_id"] != models[1]["selected_output_id"]
    assert (
        models[0]["selected_output_source"]
        != models[1]["selected_output_source"]
    )

    def override_get_db():
        with session_factory() as session:
            yield session

    audited_requests: list[dict[str, Any]] = []
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            model_evidence = [
                _accept_model(
                    client,
                    session_factory,
                    model,
                    known_labels=known_labels,
                    audited_requests=audited_requests,
                )
                for model in models
            ]
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()

    assert (
        model_evidence[0]["graph_version_id"]
        != model_evidence[1]["graph_version_id"]
    )
    total_run_count = max(
        model["replay"]["run_count_after_replay"] for model in model_evidence
    )
    evidence = {
        "schema_version": 1,
        "acceptance": "two_model_canonical_sensitivity",
        "status": "passed",
        "database": {
            "dialect": "sqlite",
            "path": str(DATABASE_PATH),
            "temporary": True,
        },
        "models": model_evidence,
        "request_contract_audit": {
            "requests_audited": len(audited_requests),
            "forbidden_request_keys": sorted(FORBIDDEN_REQUEST_KEYS),
            "forbidden_keys_or_labels_observed": False,
            "all_post_requests_canonical_uuid_only": True,
            "requests": audited_requests,
        },
        "cross_model_assertions": {
            "different_workbook_version_ids": True,
            "different_model_version_ids": True,
            "different_graph_version_ids": True,
            "different_selected_parameter_ids": True,
            "different_selected_parameter_source_mappings": True,
            "different_selected_output_ids": True,
            "different_selected_output_source_mappings": True,
        },
        "totals": {
            "models": len(model_evidence),
            "baseline_runs": len(model_evidence),
            "drivers": sum(
                model["totals"]["drivers"] for model in model_evidence
            ),
            "matrix_cells": sum(
                model["totals"]["matrix_cells"] for model in model_evidence
            ),
            "returned_case_ids": sum(
                model["totals"]["returned_case_ids"]
                for model in model_evidence
            ),
            "persisted_reload_checks": sum(
                model["totals"]["persisted_reload_checks"]
                for model in model_evidence
            ),
            "final_calculation_run_count": total_run_count,
            "replays_without_new_runs": sum(
                1
                for model in model_evidence
                if model["replay"]["no_run_count_increase"]
            ),
            "typed_unavailable_output_samples": sum(
                1
                for model in model_evidence
                if model["unavailable_output_sample"]["unavailable_reason"]
            ),
        },
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence["totals"], sort_keys=True))
    print(EVIDENCE_PATH)


if __name__ == "__main__":
    main()
