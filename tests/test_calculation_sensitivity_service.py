"""Contracts and persisted orchestration tests for canonical sensitivity."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from apps.api.app.calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from apps.api.app.calculation_rules.phase2_models import CalculationRunRecord
from apps.api.app.database import Base
from apps.api.app.model_extraction_models import (
    CanonicalOutput,
    ModelParameter,
    ModelVersion,
)
from apps.api.app.model_extraction_read_service import ModelExtractionReadService
from apps.api.app.model_extraction_types import FinancialEntityIdFactory, new_uuid
from apps.api.app.schemas import (
    CalculationRequest,
    CalculationSensitivityRequest,
)
from apps.api.app.workbook_storage import DatabaseWorkbookStorage
from tests.calculation_rule_test_support import create_materialized_rule_model
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


def _number(value: object = "1") -> dict[str, object]:
    return {"value_type": "number", "value": value}


def _target(identifier: str | None = None) -> dict[str, object]:
    return {
        "kind": "parameter",
        "parameter_id": identifier or str(uuid.uuid4()),
    }


def _contract_request() -> dict[str, object]:
    return {
        "graph_version_id": str(uuid.uuid4()),
        "output_id": str(uuid.uuid4()),
        "current_overrides": [
            {"target": _target(), "value": _number("3.000")}
        ],
        "drivers": [
            {
                "target": _target(),
                "low": _number("1.00"),
                "high": _number("2.00"),
            }
        ],
    }


def test_sensitivity_contract_preserves_decimal_strings() -> None:
    payload = _contract_request()

    request = CalculationSensitivityRequest.model_validate(payload)

    assert request.current_overrides[0].value.value == "3.000"
    assert request.drivers[0].low.value == "1.00"
    assert request.drivers[0].high.value == "2.00"


def test_sensitivity_contract_defaults_to_explicit_two_way_mode() -> None:
    request = CalculationSensitivityRequest.model_validate(_contract_request())

    assert request.two_way_mode == "explicit"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload.update(
                {
                    "two_way_mode": "top_impact",
                    "two_way": {
                        "row": {
                            "target": _target(),
                            "values": [_number("1")],
                        },
                        "column": {
                            "target": _target(),
                            "values": [_number("2")],
                        },
                    },
                }
            ),
            "Top-impact two-way mode does not accept explicit axes",
        ),
        (
            lambda payload: payload.update({"two_way_mode": "top_impact"}),
            "Top-impact two-way mode requires at least two one-way drivers",
        ),
    ],
)
def test_top_impact_contract_rejects_incompatible_shapes(
    mutation,
    message: str,
) -> None:
    payload = _contract_request()
    mutation(payload)

    with pytest.raises(ValidationError, match=message):
        CalculationSensitivityRequest.model_validate(payload)


def test_top_impact_contract_keeps_existing_driver_and_case_bounds() -> None:
    payload = _contract_request()
    payload["two_way_mode"] = "top_impact"
    payload["drivers"] = [
        {
            "target": _target(),
            "low": _number(str(index)),
            "high": _number(str(index + 1)),
        }
        for index in range(12)
    ]

    CalculationSensitivityRequest.model_validate(payload)
    payload["drivers"].append(
        {
            "target": _target(),
            "low": _number("100"),
            "high": _number("101"),
        }
    )

    with pytest.raises(ValidationError):
        CalculationSensitivityRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["current_overrides"].append(
                deepcopy(payload["current_overrides"][0])
            ),
            "Duplicate current override target",
        ),
        (
            lambda payload: payload["drivers"].append(
                deepcopy(payload["drivers"][0])
            ),
            "Duplicate one-way driver target",
        ),
        (
            lambda payload: payload["drivers"][0].update(
                {"low": _number("1.0"), "high": _number("1.00")}
            ),
            "Driver low and high values must differ",
        ),
    ],
)
def test_sensitivity_contract_rejects_invalid_one_way_shapes(
    mutation,
    message: str,
) -> None:
    payload = _contract_request()
    mutation(payload)

    with pytest.raises(ValidationError, match=message):
        CalculationSensitivityRequest.model_validate(payload)


@pytest.mark.parametrize("axis_name", ["row", "column"])
def test_sensitivity_contract_rejects_duplicate_two_way_axis_values(
    axis_name: str,
) -> None:
    payload = _contract_request()
    payload["two_way"] = {
        "row": {"target": _target(), "values": [_number("1"), _number("1.0")]},
        "column": {"target": _target(), "values": [_number("2")]},
    }
    payload["two_way"][axis_name]["values"] = [_number("4"), _number("4.0")]

    with pytest.raises(ValidationError, match="Duplicate two-way axis value"):
        CalculationSensitivityRequest.model_validate(payload)


def test_sensitivity_contract_rejects_same_two_way_axis_target() -> None:
    payload = _contract_request()
    target = _target()
    payload["two_way"] = {
        "row": {"target": target, "values": [_number("1")]},
        "column": {"target": target, "values": [_number("2")]},
    }

    with pytest.raises(ValidationError, match="Two-way axis targets must differ"):
        CalculationSensitivityRequest.model_validate(payload)


def test_sensitivity_contract_rejects_more_than_fifty_cases() -> None:
    payload = _contract_request()
    payload["drivers"] = [
        {
            "target": _target(),
            "low": _number(str(index)),
            "high": _number(str(index + 1)),
        }
        for index in range(12)
    ]
    payload["two_way"] = {
        "row": {
            "target": _target(),
            "values": [_number(str(index)) for index in range(5)],
        },
        "column": {
            "target": _target(),
            "values": [_number(str(index + 10)) for index in range(5)],
        },
    }

    assert 1 + 2 * len(payload["drivers"]) + 25 == 50
    CalculationSensitivityRequest.model_validate(payload)
    payload["drivers"].append(
        {"target": _target(), "low": _number("100"), "high": _number("101")}
    )

    with pytest.raises(ValidationError):
        CalculationSensitivityRequest.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload["drivers"][0].update({"unexpected": True}),
        lambda payload: payload["drivers"][0].update(
            {
                "target": {
                    "kind": "cell",
                    "sheet_name": "Inputs",
                    "cell_address": "A1",
                }
            }
        ),
        lambda payload: payload["drivers"][0].update({"low": _number(1)}),
        lambda payload: payload["drivers"][0].update({"low": _number("NaN")}),
        lambda payload: payload["drivers"][0].update(
            {"high": _number("Infinity")}
        ),
    ],
)
def test_sensitivity_contract_rejects_malformed_values(mutation) -> None:
    payload = _contract_request()
    mutation(payload)

    with pytest.raises(ValidationError):
        CalculationSensitivityRequest.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"drivers": []}),
        lambda payload: payload.update(
            {
                "drivers": [
                    {
                        "target": _target(),
                        "low": _number(str(index)),
                        "high": _number(str(index + 1)),
                    }
                    for index in range(13)
                ]
            }
        ),
        lambda payload: payload.update(
            {
                "current_overrides": [
                    {"target": _target(), "value": _number(str(index))}
                    for index in range(501)
                ]
            }
        ),
        lambda payload: payload.update(
            {
                "two_way": {
                    "row": {"target": _target(), "values": []},
                    "column": {"target": _target(), "values": [_number("1")]},
                }
            }
        ),
        lambda payload: payload.update(
            {
                "two_way": {
                    "row": {
                        "target": _target(),
                        "values": [_number(str(index)) for index in range(6)],
                    },
                    "column": {
                        "target": _target(),
                        "values": [_number("1")],
                    },
                }
            }
        ),
    ],
)
def test_sensitivity_contract_enforces_collection_bounds(mutation) -> None:
    payload = _contract_request()
    mutation(payload)

    with pytest.raises(ValidationError):
        CalculationSensitivityRequest.model_validate(payload)


def _parameter_target(parameter_id: str) -> dict[str, object]:
    return {"kind": "parameter", "parameter_id": parameter_id}


def _financial_series_value_target(
    financial_series_value_id: str,
) -> dict[str, object]:
    return {
        "kind": "financial_series_value",
        "financial_series_value_id": financial_series_value_id,
    }


def _sensitivity_request(
    graph_version_id: str,
    output_id: str,
    parameter_id: str,
    *,
    current: str = "10",
    low: str = "1",
    high: str = "4",
    two_way: dict[str, object] | None = None,
) -> CalculationSensitivityRequest:
    return CalculationSensitivityRequest.model_validate(
        {
            "graph_version_id": graph_version_id,
            "output_id": output_id,
            "current_overrides": [
                {
                    "target": _parameter_target(parameter_id),
                    "value": _number(current),
                }
            ],
            "drivers": [
                {
                    "target": _parameter_target(parameter_id),
                    "low": _number(low),
                    "high": _number(high),
                }
            ],
            "two_way": two_way,
        }
    )


def _output_id(model_id: str, cell_address: str = "B1") -> str:
    return FinancialEntityIdFactory(model_id).output_id("Calc", cell_address)


def _add_parameter(
    session,
    model_id: str,
    *,
    source_sheet: str = "Inputs",
    source_cell: str,
    value: object,
    data_type: str,
    label: str,
) -> ModelParameter:
    parameter = ModelParameter(
        id=FinancialEntityIdFactory(model_id).parameter_id(
            source_sheet, source_cell
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
        data_type=data_type,
        number_format="General",
    )
    session.add(parameter)
    session.commit()
    return parameter


def _add_output(
    session,
    model_id: str,
    *,
    source_cell: str,
    business_role: str,
    label: str,
) -> CanonicalOutput:
    output = CanonicalOutput(
        id=_output_id(model_id, source_cell),
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
        exact_formula=f"=Calc!{source_cell}",
        formula_status="formula_no_cache",
        source_validation_status="validated",
        role_validation_status="validated",
        validation_status="validated",
        data_type="f",
        number_format="General",
        validation_warnings_json=[],
    )
    session.add(output)
    session.commit()
    return output


@pytest.fixture
def sensitivity_context(tmp_path: Path):
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "calculation-sensitivity.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    storage, workbook, model, parameter, series, series_value = (
        create_materialized_rule_model(session)
    )
    read_service = ModelExtractionReadService(session, storage)
    facade = CalculationIntegrationService(session, read_service)
    try:
        yield {
            "engine": engine,
            "session_factory": session_factory,
            "session": session,
            "storage": storage,
            "workbook": workbook,
            "model": model,
            "parameter": parameter,
            "series": series,
            "series_value": series_value,
            "read_service": read_service,
            "facade": facade,
        }
    finally:
        session.close()
        engine.dispose()


def _service(context):
    from apps.api.app.calculation_sensitivity_service import (
        CalculationSensitivityService,
    )

    return CalculationSensitivityService(
        context["session"],
        context["facade"],
    )


def _run_count(context) -> int:
    return context["session"].scalar(
        select(func.count()).select_from(CalculationRunRecord)
    )


def _prepare_with_baseline(context):
    prepared = context["facade"].prepare(context["model"].id)
    baseline = context["facade"].calculate(
        context["model"].id,
        CalculationRequest(
            graph_version_id=prepared.graph_version_id,
            overrides=[],
            idempotency_key=None,
        ),
    )
    return prepared, baseline


def test_one_way_runs_are_persisted_and_use_real_engine_values(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    prepared, baseline = _prepare_with_baseline(context)
    request = _sensitivity_request(
        prepared.graph_version_id,
        _output_id(context["model"].id),
        context["parameter"].id,
    )

    response = _service(context).analyze(context["model"].id, request)

    assert response.comparison_baseline_run_id == baseline.calculation_run_id
    assert response.selected_output.baseline.value.value == "5"
    assert response.selected_output.current.value.value == "13"
    driver = response.drivers[0]
    assert driver.low_case.output.value.value == "4"
    assert driver.high_case.output.value.value == "7"
    assert driver.impact == "3"
    case_ids = [
        response.current_run_id,
        driver.low_case.calculation_run_id,
        driver.high_case.calculation_run_id,
    ]
    runs = [
        context["session"].get(CalculationRunRecord, run_id)
        for run_id in case_ids
    ]
    assert all(
        run.status in {"completed", "completed_with_warning"} for run in runs
    )
    assert len(set(case_ids)) == 3
    for run_id in case_ids:
        projection = context["facade"].get_run_outputs(run_id)
        assert (
            projection.comparison_baseline_run_id
            == baseline.calculation_run_id
        )


def test_unrelated_unsupported_input_does_not_block_valid_sensitivity(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    _add_parameter(
        context["session"],
        context["model"].id,
        source_cell="A3",
        value={"unsupported": True},
        data_type="x",
        label="Unrelated unsupported input",
    )
    prepared, baseline = _prepare_with_baseline(context)
    request = _sensitivity_request(
        prepared.graph_version_id,
        _output_id(context["model"].id),
        context["parameter"].id,
    )

    response = _service(context).analyze(context["model"].id, request)

    assert response.comparison_baseline_run_id == baseline.calculation_run_id
    assert response.selected_output.current.value.value == "13"
    assert response.drivers[0].low_case.output.value.value == "4"
    assert response.drivers[0].high_case.output.value.value == "7"


def test_editable_numeric_financial_series_value_runs_real_one_way_cases(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    series_value = context["series_value"]
    series_value.value_json = 3
    series_value.value_source_sheet = "Inputs"
    series_value.value_source_cell = "A2"
    series_value.exact_formula = None
    series_value.formula_status = "static_value"
    series_value.cached_value_available = True
    series_value.cached_value_freshness = "unknown"
    series_value.data_type = "n"
    context["session"].commit()
    prepared, baseline = _prepare_with_baseline(context)
    payload = _sensitivity_request(
        prepared.graph_version_id,
        _output_id(context["model"].id),
        context["parameter"].id,
    ).model_dump(mode="json")
    target = _financial_series_value_target(series_value.id)
    payload["current_overrides"][0]["target"] = target
    payload["drivers"][0]["target"] = target
    request = CalculationSensitivityRequest.model_validate(payload)

    response = _service(context).analyze(context["model"].id, request)

    assert response.comparison_baseline_run_id == baseline.calculation_run_id
    assert response.selected_output.current.value.value == "12"
    assert response.drivers[0].low_case.output.value.value == "3"
    assert response.drivers[0].high_case.output.value.value == "6"
    assert response.drivers[0].impact == "3"
    for run_id in _response_run_ids(response):
        run = context["session"].get(CalculationRunRecord, run_id)
        assert run.status in {"completed", "completed_with_warning"}


def test_baseline_preflight_fails_before_creating_a_run(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    prepared = context["facade"].prepare(context["model"].id)
    request = _sensitivity_request(
        prepared.graph_version_id,
        _output_id(context["model"].id),
        context["parameter"].id,
    )

    with pytest.raises(CalculationIntegrationError) as captured:
        _service(context).analyze(context["model"].id, request)

    assert captured.value.code == "CALCULATION_BASELINE_NOT_FOUND"
    assert captured.value.status_code == 409
    assert _run_count(context) == 0


@pytest.mark.parametrize(
    ("preflight_state", "expected_code", "expected_status"),
    [
        ("unknown_model", "MODEL_VERSION_NOT_FOUND", 404),
        ("model_not_ready", "MODEL_NOT_MATERIALIZED", 409),
        ("not_prepared", "CALCULATION_NOT_PREPARED", 409),
        ("graph_mismatch", "GRAPH_VERSION_MISMATCH", 409),
    ],
)
def test_preflight_validates_readiness_and_graph_before_baseline_lookup(
    sensitivity_context,
    monkeypatch: pytest.MonkeyPatch,
    preflight_state: str,
    expected_code: str,
    expected_status: int,
) -> None:
    context = sensitivity_context
    model_version_id = context["model"].id
    graph_version_id = str(uuid.uuid4())
    expected_resource_id = model_version_id
    if preflight_state == "unknown_model":
        model_version_id = str(uuid.uuid4())
        expected_resource_id = model_version_id
    elif preflight_state == "model_not_ready":
        context["model"].status = "extracted"
        context["session"].commit()
    elif preflight_state == "graph_mismatch":
        context["facade"].prepare(model_version_id)
        expected_resource_id = graph_version_id

    request = _sensitivity_request(
        graph_version_id,
        _output_id(context["model"].id),
        context["parameter"].id,
    )
    service = _service(context)
    monkeypatch.setattr(
        service._repository,
        "find_completed_zero_override_run",
        lambda *_args, **_kwargs: pytest.fail(
            "Baseline lookup must follow model and graph validation"
        ),
    )

    with pytest.raises(CalculationIntegrationError) as captured:
        service.analyze(model_version_id, request)

    assert captured.value.code == expected_code
    assert captured.value.status_code == expected_status
    assert captured.value.resource_id == expected_resource_id
    assert _run_count(context) == 0


@pytest.mark.parametrize(
    "invalid_kind",
    ["unknown", "wrong_model", "non_editable", "non_numeric"],
)
def test_baseline_preflight_validates_all_targets_before_new_runs(
    sensitivity_context,
    invalid_kind: str,
) -> None:
    context = sensitivity_context
    prepared, _baseline = _prepare_with_baseline(context)
    other_model = ModelVersion(
        id=new_uuid(),
        workbook_version_id=context["workbook"].id,
        upload_filename="wrong-model.xlsx",
        status="materialized",
        validation_status="validated",
        submitted=True,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    context["session"].add(other_model)
    context["session"].commit()
    wrong_parameter = _add_parameter(
        context["session"],
        other_model.id,
        source_cell="A2",
        value=3,
        data_type="n",
        label="Wrong model input",
    )
    non_numeric = _add_parameter(
        context["session"],
        context["model"].id,
        source_cell="A2",
        value="not-a-number",
        data_type="s",
        label="Non numeric input",
    )
    targets = {
        "unknown": _target(),
        "wrong_model": _parameter_target(wrong_parameter.id),
        "non_editable": {
            "kind": "financial_series_value",
            "financial_series_value_id": context["series_value"].id,
        },
        "non_numeric": _parameter_target(non_numeric.id),
    }
    payload = _sensitivity_request(
        prepared.graph_version_id,
        _output_id(context["model"].id),
        context["parameter"].id,
    ).model_dump(mode="json")
    payload["drivers"][0]["target"] = targets[invalid_kind]
    request = CalculationSensitivityRequest.model_validate(payload)
    before = _run_count(context)

    with pytest.raises(CalculationIntegrationError) as captured:
        _service(context).analyze(context["model"].id, request)

    assert captured.value.code == "INVALID_SENSITIVITY_TARGET"
    assert captured.value.status_code == 422
    assert _run_count(context) == before


@pytest.mark.parametrize("output_kind", ["unknown", "series"])
def test_baseline_preflight_rejects_unknown_or_series_output_before_new_runs(
    sensitivity_context,
    output_kind: str,
) -> None:
    context = sensitivity_context
    prepared, _baseline = _prepare_with_baseline(context)
    output_id = (
        str(uuid.uuid4())
        if output_kind == "unknown"
        else context["series"].id
    )
    request = _sensitivity_request(
        prepared.graph_version_id,
        output_id,
        context["parameter"].id,
    )
    before = _run_count(context)

    with pytest.raises(CalculationIntegrationError) as captured:
        _service(context).analyze(context["model"].id, request)

    assert captured.value.code == "INVALID_SENSITIVITY_OUTPUT"
    assert captured.value.status_code == 422
    assert captured.value.resource_id == output_id
    assert _run_count(context) == before


def _two_way_request(
    context,
    graph_version_id: str,
    second_parameter_id: str,
) -> CalculationSensitivityRequest:
    return _sensitivity_request(
        graph_version_id,
        _output_id(context["model"].id),
        context["parameter"].id,
        two_way={
            "row": {
                "target": _parameter_target(context["parameter"].id),
                "values": [_number("1"), _number("2"), _number("4")],
            },
            "column": {
                "target": _parameter_target(second_parameter_id),
                "values": [_number("3"), _number("5")],
            },
        },
    )


def _top_impact_request(
    context,
    graph_version_id: str,
    output_id: str,
    second_parameter_id: str,
) -> CalculationSensitivityRequest:
    payload = _sensitivity_request(
        graph_version_id,
        output_id,
        context["parameter"].id,
    ).model_dump(mode="json")
    payload["two_way_mode"] = "top_impact"
    payload["drivers"] = [
        {
            "target": _parameter_target(context["parameter"].id),
            "low": _number("1"),
            "high": _number("5"),
        },
        {
            "target": _parameter_target(second_parameter_id),
            "low": _number("1"),
            "high": _number("4"),
        },
    ]
    payload["two_way"] = None
    return CalculationSensitivityRequest.model_validate(payload)


def _response_run_ids(response) -> list[str]:
    return [
        response.current_run_id,
        *[
            case_id
            for driver in response.drivers
            for case_id in (
                driver.low_case.calculation_run_id,
                driver.high_case.calculation_run_id,
            )
        ],
        *[
            cell.calculation_run_id
            for cell in (response.two_way.cells if response.two_way else [])
        ],
    ]


def test_two_way_returns_real_cartesian_cells_in_row_major_order(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    second_parameter = _add_parameter(
        context["session"],
        context["model"].id,
        source_cell="A2",
        value=3,
        data_type="n",
        label="Unit price",
    )
    unrelated_parameter = _add_parameter(
        context["session"],
        context["model"].id,
        source_sheet="Calc",
        source_cell="A1",
        value=2026,
        data_type="n",
        label="Unrelated current override",
    )
    prepared, baseline = _prepare_with_baseline(context)
    request = _two_way_request(
        context,
        prepared.graph_version_id,
        second_parameter.id,
    )
    assert request.two_way_mode == "explicit"
    payload = request.model_dump(mode="json")
    payload["current_overrides"].append(
        {
            "target": _parameter_target(unrelated_parameter.id),
            "value": _number("11"),
        }
    )
    request = CalculationSensitivityRequest.model_validate(payload)

    response = _service(context).analyze(context["model"].id, request)

    assert response.two_way is not None
    assert response.two_way.row_target == request.two_way.row.target
    assert response.two_way.column_target == request.two_way.column.target
    assert [
        (cell.row_value.value, cell.column_value.value)
        for cell in response.two_way.cells
    ] == [
        ("1", "3"),
        ("1", "5"),
        ("2", "3"),
        ("2", "5"),
        ("4", "3"),
        ("4", "5"),
    ]
    assert [
        cell.output.value.value for cell in response.two_way.cells
    ] == ["4", "6", "5", "7", "7", "9"]
    cell_ids = [
        cell.calculation_run_id for cell in response.two_way.cells
    ]
    assert len(cell_ids) == len(set(cell_ids)) == 6
    for cell_id in cell_ids:
        run = context["session"].get(CalculationRunRecord, cell_id)
        assert run.status in {"completed", "completed_with_warning"}
        projection = context["facade"].get_run_outputs(cell_id)
        assert (
            projection.comparison_baseline_run_id
            == baseline.calculation_run_id
        )
        run = context["session"].get(CalculationRunRecord, cell_id)
        unrelated_override = next(
            override
            for override in run.overrides_json
            if override["target_id"] == unrelated_parameter.id
        )
        assert unrelated_override["value_type"] == "number"
        assert unrelated_override["value"] == "11"


def test_top_impact_ranks_numeric_impacts_by_request_order(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    second_parameter = _add_parameter(
        context["session"],
        context["model"].id,
        source_cell="A2",
        value=3,
        data_type="n",
        label="Unit price",
    )
    prepared, _baseline = _prepare_with_baseline(context)
    request = _top_impact_request(
        context,
        prepared.graph_version_id,
        _output_id(context["model"].id),
        second_parameter.id,
    )
    response = _service(context).analyze(context["model"].id, request)
    from apps.api.app.calculation_sensitivity_service import (
        _rank_top_impact_drivers,
    )

    first, second = response.drivers
    ranked = _rank_top_impact_drivers(
        [
            second.model_copy(update={"impact": "4"}),
            first.model_copy(update={"impact": "4"}),
            first.model_copy(update={"impact": None}),
        ]
    )

    assert [driver.target.identity for driver in ranked] == [
        second.target.identity,
        first.target.identity,
    ]


def test_top_impact_persists_twenty_five_linear_cartesian_cases(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    second_parameter = _add_parameter(
        context["session"],
        context["model"].id,
        source_cell="A2",
        value=3,
        data_type="n",
        label="Unit price",
    )
    prepared, _baseline = _prepare_with_baseline(context)
    request = _top_impact_request(
        context,
        prepared.graph_version_id,
        _output_id(context["model"].id),
        second_parameter.id,
    )

    response = _service(context).analyze(context["model"].id, request)

    assert response.two_way is not None
    assert response.two_way.row_target.identity == (
        "parameter",
        context["parameter"].id,
    )
    assert response.two_way.column_target.identity == (
        "parameter",
        second_parameter.id,
    )
    assert [cell.row_value.value for cell in response.two_way.cells] == [
        value for value in ["1", "2", "3", "4", "5"] for _ in range(5)
    ]
    assert [cell.column_value.value for cell in response.two_way.cells] == [
        value
        for _ in range(5)
        for value in ["1", "1.75", "2.5", "3.25", "4"]
    ]
    assert len(response.two_way.cells) == 25
    assert len({cell.calculation_run_id for cell in response.two_way.cells}) == 25
    assert _run_count(context) == 31


def test_top_impact_returns_typed_warning_when_fewer_than_two_impacts_are_usable(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    second_parameter = _add_parameter(
        context["session"],
        context["model"].id,
        source_cell="A2",
        value=3,
        data_type="n",
        label="Unit price",
    )
    unavailable_output = _add_output(
        context["session"],
        context["model"].id,
        source_cell="B5",
        business_role="unclassified",
        label="Circular metric",
    )
    prepared, _baseline = _prepare_with_baseline(context)
    request = _top_impact_request(
        context,
        prepared.graph_version_id,
        unavailable_output.id,
        second_parameter.id,
    )

    response = _service(context).analyze(context["model"].id, request)

    assert response.two_way is None
    assert "TOP_IMPACT_TWO_WAY_UNAVAILABLE" in response.warnings


def test_replay_returns_identical_current_endpoint_and_cell_run_ids(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    second_parameter = _add_parameter(
        context["session"],
        context["model"].id,
        source_cell="A2",
        value=3,
        data_type="n",
        label="Unit price",
    )
    prepared, _baseline = _prepare_with_baseline(context)
    request = _two_way_request(
        context,
        prepared.graph_version_id,
        second_parameter.id,
    )

    first = _service(context).analyze(context["model"].id, request)
    count_after_first = _run_count(context)
    second = _service(context).analyze(context["model"].id, request)

    assert _response_run_ids(first) == _response_run_ids(second)
    assert _run_count(context) == count_after_first


def test_unavailable_outputs_keep_typed_values_run_ids_and_warning(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    unavailable_output = _add_output(
        context["session"],
        context["model"].id,
        source_cell="B5",
        business_role="unclassified",
        label="Circular metric",
    )
    prepared, _baseline = _prepare_with_baseline(context)
    request = _sensitivity_request(
        prepared.graph_version_id,
        unavailable_output.id,
        context["parameter"].id,
    )

    response = _service(context).analyze(context["model"].id, request)

    assert response.selected_output.current.availability_status == "unavailable"
    assert response.selected_output.current.value is None
    assert response.selected_output.current.unavailable_reason
    driver = response.drivers[0]
    assert driver.low_case.output.availability_status == "unavailable"
    assert driver.high_case.output.availability_status == "unavailable"
    assert driver.low_case.calculation_run_id
    assert driver.high_case.calculation_run_id
    assert driver.impact is None
    assert driver.warnings == [
        "Impact is unavailable because one or both endpoint outputs are not "
        "available numeric values."
    ]
    assert response.warnings == [
        *response.selected_output.current.warnings,
        "Selected output is unavailable: "
        f"{response.selected_output.current.unavailable_reason}.",
        "Impact is unavailable because one or both endpoint outputs are not "
        "available numeric values.",
    ]


def test_model_specific_uuids_drive_two_real_models(
    sensitivity_context,
) -> None:
    context = sensitivity_context
    first_prepared, _first_baseline = _prepare_with_baseline(context)
    second_model = ModelVersion(
        id=new_uuid(),
        workbook_version_id=context["workbook"].id,
        upload_filename="second-project-finance.xlsx",
        status="materialized",
        validation_status="validated",
        submitted=True,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    context["session"].add(second_model)
    context["session"].commit()
    second_parameter = _add_parameter(
        context["session"],
        second_model.id,
        source_cell="A2",
        value=3,
        data_type="n",
        label="Second model input",
    )
    second_output = _add_output(
        context["session"],
        second_model.id,
        source_cell="B2",
        business_role="total_project_cost",
        label="Second model output",
    )
    second_facade = CalculationIntegrationService(
        context["session"],
        ModelExtractionReadService(
            context["session"],
            DatabaseWorkbookStorage(context["session"]),
        ),
    )
    second_prepared = second_facade.prepare(second_model.id)
    second_facade.calculate(
        second_model.id,
        CalculationRequest(
            graph_version_id=second_prepared.graph_version_id,
            overrides=[],
            idempotency_key=None,
        ),
    )
    first_request = _sensitivity_request(
        first_prepared.graph_version_id,
        _output_id(context["model"].id),
        context["parameter"].id,
        low="1",
        high="4",
    )
    second_request = _sensitivity_request(
        second_prepared.graph_version_id,
        second_output.id,
        second_parameter.id,
        low="4",
        high="6",
    )

    first_response = _service(context).analyze(
        context["model"].id,
        first_request,
    )
    from apps.api.app.calculation_sensitivity_service import (
        CalculationSensitivityService,
    )

    second_response = CalculationSensitivityService(
        context["session"],
        second_facade,
    ).analyze(second_model.id, second_request)

    assert first_request.drivers[0].target != second_request.drivers[0].target
    assert (
        first_response.selected_output.output_id
        != second_response.selected_output.output_id
    )
    assert first_response.drivers[0].low_case.output.value.value == "4"
    assert second_response.drivers[0].low_case.output.value.value == "12"
