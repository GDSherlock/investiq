"""Contract tests for the deterministic calculation HTTP API."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select

from apps.api.app.calculation_rules.models import CalculationRuleExtraction
from apps.api.app.calculation_rules.phase2_models import (
    CalculationGraphVersionRecord,
    CalculationRunRecord,
    CalculationRunValueRecord,
)
from apps.api.app.database import Base, get_db
from apps.api.app.main import app
from apps.api.app.routers.calculations import (
    get_calculation_sensitivity_service,
)
from apps.api.app.model_extraction_models import (
    CanonicalOutput,
    FinancialSeries,
    FinancialSeriesValue,
    ModelParameter,
    ModelVersion,
)
from apps.api.app.schemas import (
    CalculationBlankValue,
    CalculationBooleanValue,
    CalculationDateValue,
    CalculationInputValue,
    CalculationRequest,
)
from tests.calculation_rule_test_support import create_materialized_rule_model
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


def _request(*overrides: dict[str, object]) -> dict[str, object]:
    return {
        "graph_version_id": str(uuid.uuid4()),
        "overrides": list(overrides),
        "idempotency_key": None,
    }


def test_number_value_accepts_finite_decimal_string() -> None:
    value = TypeAdapter(CalculationInputValue).validate_python(
        {"value_type": "number", "value": "900.000000000000000001"}
    )

    assert value.value_type == "number"
    assert value.value == "900.000000000000000001"


def test_number_value_accepts_smallest_binary64_subnormal() -> None:
    value = TypeAdapter(CalculationInputValue).validate_python(
        {"value_type": "number", "value": "5e-324"}
    )

    assert value.value == "5e-324"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999999"])
def test_number_value_rejects_non_finite_decimal_string(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CalculationInputValue).validate_python(
            {"value_type": "number", "value": value}
        )


@pytest.mark.parametrize(
    "value",
    ["1e-100000", "0e-100000", "0e100000"],
)
def test_number_value_rejects_unbounded_decimal_exponents(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CalculationInputValue).validate_python(
            {"value_type": "number", "value": value}
        )


def test_number_value_rejects_nonzero_binary64_underflow() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CalculationInputValue).validate_python(
            {"value_type": "number", "value": "1e-324"}
        )


def test_number_value_rejects_overlong_literal() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CalculationInputValue).validate_python(
            {"value_type": "number", "value": f"{'0' * 128}1"}
        )


def test_number_value_rejects_excess_significant_digits() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CalculationInputValue).validate_python(
            {
                "value_type": "number",
                "value": "123456789012345678901234567890123",
            }
        )


def test_formula_like_text_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CalculationInputValue).validate_python(
            {"value_type": "text", "value": "=SUM(A1:A2)"}
        )


def test_blank_date_and_boolean_values_are_accepted() -> None:
    adapter = TypeAdapter(CalculationInputValue)

    assert adapter.validate_python({"value_type": "blank", "value": None}) == (
        CalculationBlankValue(value_type="blank", value=None)
    )
    assert adapter.validate_python(
        {"value_type": "date", "value": "2030-01-01"}
    ) == CalculationDateValue(value_type="date", value="2030-01-01")
    assert adapter.validate_python(
        {"value_type": "boolean", "value": True}
    ) == CalculationBooleanValue(value_type="boolean", value=True)


def test_parameter_and_financial_series_value_targets_are_accepted() -> None:
    parameter_id = str(uuid.uuid4())
    financial_series_value_id = str(uuid.uuid4())

    parameter = CalculationRequest.model_validate(
        _request(
            {
                "target": {"kind": "parameter", "parameter_id": parameter_id},
                "value": {"value_type": "number", "value": "900"},
            }
        )
    )
    financial_value = CalculationRequest.model_validate(
        _request(
            {
                "target": {
                    "kind": "financial_series_value",
                    "financial_series_value_id": financial_series_value_id,
                },
                "value": {"value_type": "number", "value": "125.5"},
            }
        )
    )

    assert parameter.overrides[0].target.parameter_id == parameter_id
    assert (
        financial_value.overrides[0].target.financial_series_value_id
        == financial_series_value_id
    )


def test_raw_cell_target_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CalculationRequest.model_validate(
            _request(
                {
                    "target": {
                        "kind": "cell",
                        "sheet_name": "Inputs",
                        "cell_address": "A1",
                    },
                    "value": {"value_type": "number", "value": "1"},
                }
            )
        )


def test_duplicate_override_target_is_rejected() -> None:
    parameter_id = str(uuid.uuid4())
    override = {
        "target": {"kind": "parameter", "parameter_id": parameter_id},
        "value": {"value_type": "number", "value": "900"},
    }

    with pytest.raises(ValidationError, match="Duplicate override target"):
        CalculationRequest.model_validate(_request(override, override))


@pytest.fixture
def api_context(tmp_path: Path, request):
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "calculation-api.db")
    )
    Base.metadata.create_all(engine)
    setup = session_factory()
    try:
        _storage, workbook, model, parameter, _series, series_value = (
            create_materialized_rule_model(
                setup,
                include_calculation_properties=getattr(request, "param", True),
            )
        )
        identifiers = {
            "workbook_version_id": workbook.id,
            "model_version_id": model.id,
            "parameter_id": parameter.id,
            "financial_series_value_id": series_value.id,
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
            yield {
                **identifiers,
                "client": client,
                "session_factory": session_factory,
            }
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_all_calculation_endpoints_and_openapi_contract_are_registered() -> None:
    schema = app.openapi()
    expected = {
        ("/api/v1/models/{model_version_id}/calculation/readiness", "get"),
        ("/api/v1/models/{model_version_id}/calculation/prepare", "post"),
        ("/api/v1/models/{model_version_id}/calculation/inputs", "get"),
        ("/api/v1/models/{model_version_id}/calculation/outputs", "get"),
        (
            "/api/v1/models/{model_version_id}/calculation/sensitivity",
            "post",
        ),
        (
            "/api/v1/calculation-sensitivity-analyses/{analysis_id}",
            "get",
        ),
        ("/api/v1/models/{model_version_id}/calculations", "post"),
        ("/api/v1/calculation-runs/{calculation_run_id}", "get"),
        ("/api/v1/calculation-runs/{calculation_run_id}/outputs", "get"),
        ("/api/v1/models/{model_version_id}/semantic-bindings", "get"),
        (
            "/api/v1/models/{model_version_id}/semantic-bindings/{semantic_role}",
            "put",
        ),
        (
            "/api/v1/models/{model_version_id}/analysis-parameters/{parameter_id}",
            "put",
        ),
    }

    for path, method in expected:
        operation = schema["paths"][path][method]
        assert operation["tags"] == ["Calculation"]
        assert "200" in operation["responses"]

    calculate = schema["paths"][
        "/api/v1/models/{model_version_id}/calculations"
    ]["post"]
    assert calculate["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CalculationRequest"
    }
    assert calculate["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/CalculationRunResponse"}
    components = schema["components"]["schemas"]
    parameter_target = components["ParameterOverrideTarget"]["properties"]
    financial_target = components["FinancialSeriesValueOverrideTarget"][
        "properties"
    ]
    assert parameter_target["kind"]["const"] == "parameter"
    assert set(parameter_target) == {"kind", "parameter_id"}
    assert financial_target["kind"]["const"] == "financial_series_value"
    assert set(financial_target) == {"kind", "financial_series_value_id"}
    assert "sheet_name" not in str(components["CalculationOverrideRequest"])
    assert "cell_address" not in str(components["CalculationOverrideRequest"])
    sensitivity = schema["paths"][
        "/api/v1/models/{model_version_id}/calculation/sensitivity"
    ]["post"]
    assert sensitivity["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/CalculationSensitivityRequest"}
    assert sensitivity["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/CalculationSensitivityResponse"}


def test_semantic_binding_preview_and_review_require_exact_canonical_entities(
    api_context,
) -> None:
    model_id = api_context["model_version_id"]
    client = api_context["client"]

    preview = client.get(f"/api/v1/models/{model_id}/semantic-bindings")

    assert preview.status_code == 200
    slots = {slot["semantic_role"]: slot for slot in preview.json()["slots"]}
    assert slots["revenue"]["status"] == "candidate"
    assert slots["revenue"]["candidates"][0]["entity_kind"] == "financial_series"
    assert slots["project_irr"] == {
        "semantic_role": "project_irr",
        "status": "unresolved",
        "binding": None,
        "candidates": [],
    }

    revenue_id = slots["revenue"]["candidates"][0]["entity_id"]
    reviewed = client.put(
        f"/api/v1/models/{model_id}/semantic-bindings/revenue",
        json={"entity_kind": "financial_series", "entity_id": revenue_id},
    )

    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "reviewed"
    assert reviewed.json()["binding"]["entity_id"] == revenue_id

    wrong_role = client.put(
        f"/api/v1/models/{model_id}/semantic-bindings/project_irr",
        json={"entity_kind": "financial_series", "entity_id": revenue_id},
    )

    assert wrong_role.status_code == 409
    assert wrong_role.json()["detail"]["code"] == "SEMANTIC_ENTITY_ROLE_MISMATCH"


def test_parameter_analysis_review_controls_role_and_stochastic_eligibility(
    api_context,
) -> None:
    model_id = api_context["model_version_id"]
    parameter_id = api_context["parameter_id"]
    client = api_context["client"]

    reviewed = client.put(
        f"/api/v1/models/{model_id}/analysis-parameters/{parameter_id}",
        json={"business_role": "discount_rate", "stochastic_eligible": True},
    )

    assert reviewed.status_code == 200
    assert reviewed.json() == {
        "model_version_id": model_id,
        "parameter_id": parameter_id,
        "business_role": "discount_rate",
        "stochastic_eligible": True,
    }
    preview = client.get(f"/api/v1/models/{model_id}/semantic-bindings")
    discount_rate = next(
        slot
        for slot in preview.json()["slots"]
        if slot["semantic_role"] == "discount_rate"
    )
    assert discount_rate["status"] == "candidate"
    assert discount_rate["candidates"][0]["entity_id"] == parameter_id


@pytest.mark.parametrize(
    "payload",
    [
        {
            "graph_version_id": str(uuid.uuid4()),
            "output_id": str(uuid.uuid4()),
            "drivers": [
                {
                    "target": {
                        "kind": "cell",
                        "sheet_name": "Inputs",
                        "cell_address": "A1",
                    },
                    "low": {"value_type": "number", "value": "1"},
                    "high": {"value_type": "number", "value": "2"},
                }
            ],
        },
        {
            "graph_version_id": str(uuid.uuid4()),
            "output_id": str(uuid.uuid4()),
            "drivers": [
                {
                    "target": {
                        "kind": "parameter",
                        "parameter_id": str(uuid.uuid4()),
                    },
                    "low": {"value_type": "number", "value": str(index)},
                    "high": {
                        "value_type": "number",
                        "value": str(index + 1),
                    },
                }
                for index in range(13)
            ],
        },
    ],
)
def test_sensitivity_api_rejects_malformed_or_over_limit_before_service(
    api_context,
    payload: dict[str, object],
) -> None:
    class _SensitivityMustNotAnalyze:
        def analyze(self, *_args, **_kwargs):
            raise AssertionError("Malformed requests must not execute service")

    app.dependency_overrides[get_calculation_sensitivity_service] = (
        lambda: _SensitivityMustNotAnalyze()
    )
    try:
        response = api_context["client"].post(
            f"/api/v1/models/{api_context['model_version_id']}"
            "/calculation/sensitivity",
            json=payload,
        )
    finally:
        app.dependency_overrides.pop(
            get_calculation_sensitivity_service,
            None,
        )

    assert response.status_code == 422


def _sensitivity_api_payload(
    context,
    graph_version_id: str,
    output_id: str,
) -> dict[str, object]:
    return {
        "graph_version_id": graph_version_id,
        "output_id": output_id,
        "current_overrides": [
            {
                "target": {
                    "kind": "parameter",
                    "parameter_id": context["parameter_id"],
                },
                "value": {"value_type": "number", "value": "10"},
            }
        ],
        "drivers": [
            {
                "target": {
                    "kind": "parameter",
                    "parameter_id": context["parameter_id"],
                },
                "low": {"value_type": "number", "value": "1"},
                "high": {"value_type": "number", "value": "4"},
            }
        ],
    }


def test_sensitivity_http_runs_real_persisted_cases(api_context) -> None:
    context = api_context
    client = context["client"]
    prepared = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculation/prepare",
        json={},
    )
    graph_version_id = prepared.json()["graph_version_id"]
    baseline = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculations",
        json={
            "graph_version_id": graph_version_id,
            "overrides": [],
            "idempotency_key": None,
        },
    )
    outputs = client.get(
        f"/api/v1/models/{context['model_version_id']}/calculation/outputs"
    )
    scalar = next(
        item
        for item in outputs.json()["outputs"]
        if item["entity_kind"] == "scalar"
    )

    response = client.post(
        f"/api/v1/models/{context['model_version_id']}"
        "/calculation/sensitivity",
        json=_sensitivity_api_payload(
            context,
            graph_version_id,
            scalar["output_id"],
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert (
        payload["comparison_baseline_run_id"]
        == baseline.json()["calculation_run_id"]
    )
    assert payload["selected_output"]["current"]["value"]["value"] == "13"
    assert payload["drivers"][0]["low_case"]["output"]["value"]["value"] == "4"
    assert payload["drivers"][0]["high_case"]["output"]["value"]["value"] == "7"
    assert payload["drivers"][0]["impact"] == "3"


def test_sensitivity_http_compact_analysis_can_be_reloaded_by_get(
    api_context,
) -> None:
    context = api_context
    client = context["client"]
    prepared = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculation/prepare",
        json={},
    ).json()
    baseline = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculations",
        json={
            "graph_version_id": prepared["graph_version_id"],
            "overrides": [],
            "idempotency_key": None,
        },
    ).json()
    current = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculations",
        json={
            "graph_version_id": prepared["graph_version_id"],
            "overrides": [
                {
                    "target": {
                        "kind": "parameter",
                        "parameter_id": context["parameter_id"],
                    },
                    "value": {"value_type": "number", "value": "10"},
                }
            ],
            "idempotency_key": None,
        },
    ).json()
    outputs = client.get(
        f"/api/v1/models/{context['model_version_id']}/calculation/outputs"
    ).json()
    scalar = next(
        item
        for item in outputs["outputs"]
        if item["entity_kind"] == "scalar"
    )
    request = _sensitivity_api_payload(
        context,
        prepared["graph_version_id"],
        scalar["output_id"],
    )
    request["current_run_id"] = current["calculation_run_id"]

    response = client.post(
        f"/api/v1/models/{context['model_version_id']}"
        "/calculation/sensitivity",
        json=request,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["comparison_baseline_run_id"] == baseline[
        "calculation_run_id"
    ]
    assert payload["case_count"] == 2
    assert (
        payload["drivers"][0]["low_case"]["calculation_run_id"]
        is None
    )
    reload = client.get(
        "/api/v1/calculation-sensitivity-analyses/"
        f"{payload['analysis_id']}"
    )
    assert reload.status_code == 200
    assert reload.json() == payload


def test_sensitivity_http_preserves_structured_domain_failure(
    api_context,
) -> None:
    context = api_context
    client = context["client"]
    prepared = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculation/prepare",
        json={},
    )
    outputs = client.get(
        f"/api/v1/models/{context['model_version_id']}/calculation/outputs"
    )
    scalar = next(
        item
        for item in outputs.json()["outputs"]
        if item["entity_kind"] == "scalar"
    )

    response = client.post(
        f"/api/v1/models/{context['model_version_id']}"
        "/calculation/sensitivity",
        json=_sensitivity_api_payload(
            context,
            prepared.json()["graph_version_id"],
            scalar["output_id"],
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "CALCULATION_BASELINE_NOT_FOUND",
        "message": (
            "A completed zero-override calculation with matching versions "
            "is required."
        ),
        "retryable": False,
        "resource_id": context["model_version_id"],
    }


def test_raw_cell_request_is_rejected_by_public_schema(api_context) -> None:
    context = api_context
    client = context["client"]
    prepared = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculation/prepare",
        json={},
    )
    assert prepared.status_code == 200

    response = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculations",
        json={
            "graph_version_id": prepared.json()["graph_version_id"],
            "overrides": [
                {
                    "target": {
                        "kind": "cell",
                        "sheet_name": "Inputs",
                        "cell_address": "A1",
                    },
                    "value": {"value_type": "number", "value": "5"},
                }
            ],
            "idempotency_key": None,
        },
    )

    assert response.status_code == 422


def test_output_discovery_returns_business_definitions_without_cell_input(
    api_context,
) -> None:
    context = api_context
    client = context["client"]
    prepared = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculation/prepare",
        json={},
    )
    assert prepared.status_code == 200

    response = client.get(
        f"/api/v1/models/{context['model_version_id']}/calculation/outputs"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_version_id"] == context["model_version_id"]
    by_role = {item["business_role"]: item for item in payload["outputs"]}
    assert set(by_role) == {"revenue", "total_project_cost"}
    assert by_role["total_project_cost"]["entity_kind"] == "scalar"
    assert by_role["total_project_cost"]["mapping_status"] == "mapped"
    assert by_role["total_project_cost"]["source"]["formula_cell_id"]
    assert by_role["revenue"]["entity_kind"] == "series"
    assert by_role["revenue"]["points"][0]["formula_cell_id"]
    assert "project_irr" not in by_role


def test_run_output_projection_returns_business_values_without_cell_coordinates(
    api_context,
) -> None:
    context = api_context
    client = context["client"]
    prepared = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculation/prepare",
        json={},
    )
    graph_version_id = prepared.json()["graph_version_id"]
    baseline = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculations",
        json={
            "graph_version_id": graph_version_id,
            "overrides": [],
            "idempotency_key": None,
        },
    )
    override = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculations",
        json={
            "graph_version_id": graph_version_id,
            "overrides": [
                {
                    "target": {
                        "kind": "parameter",
                        "parameter_id": context["parameter_id"],
                    },
                    "value": {"value_type": "number", "value": "10"},
                }
            ],
            "idempotency_key": None,
        },
    )

    response = client.get(
        f"/api/v1/calculation-runs/"
        f"{override.json()['calculation_run_id']}/outputs"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_run_id"] == baseline.json()["calculation_run_id"]
    assert (
        payload["comparison_baseline_run_id"]
        == baseline.json()["calculation_run_id"]
    )
    by_role = {item["business_role"]: item for item in payload["outputs"]}
    assert by_role["total_project_cost"]["baseline"]["value"]["value"] == "5"
    assert by_role["total_project_cost"]["current"]["value"]["value"] == "13"
    assert by_role["revenue"]["points"][0]["baseline"]["value"]["value"] == "10"
    assert by_role["revenue"]["points"][0]["current"]["value"]["value"] == "26"
    assert "sheet_name" not in response.text
    assert "cell_address" not in response.text


def test_calculation_api_returns_stable_structured_domain_errors(api_context) -> None:
    context = api_context
    client = context["client"]
    missing_id = str(uuid.uuid4())

    missing = client.get(
        f"/api/v1/models/{missing_id}/calculation/readiness"
    )
    missing_projection = client.get(
        f"/api/v1/calculation-runs/{missing_id}/outputs"
    )
    prepared = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculation/prepare"
    )
    mismatch = client.post(
        f"/api/v1/models/{context['model_version_id']}/calculations",
        json=_request(),
    )

    assert missing.status_code == 404
    assert missing.json()["detail"] == {
        "code": "MODEL_VERSION_NOT_FOUND",
        "message": "Model version was not found.",
        "retryable": False,
        "resource_id": missing_id,
    }
    assert missing_projection.status_code == 404
    assert missing_projection.json()["detail"] == {
        "code": "CALCULATION_RUN_NOT_FOUND",
        "message": "Calculation run was not found.",
        "retryable": False,
        "resource_id": missing_id,
    }
    assert prepared.status_code == 200
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "GRAPH_VERSION_MISMATCH"


@pytest.mark.parametrize("api_context", [False], indirect=True)
def test_prepare_handles_workbook_without_calculation_properties(api_context) -> None:
    context = api_context

    response = context["client"].post(
        f"/api/v1/models/{context['model_version_id']}/calculation/prepare",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ready_with_warning"
    assert response.json()["calculation_rule_extraction_id"] is not None
    assert response.json()["graph_version_id"] is not None


def _api_canonical_fingerprint(session, model_version_id: str) -> tuple[object, ...]:
    model = session.get(ModelVersion, model_version_id)
    parameters = session.scalars(
        select(ModelParameter)
        .where(ModelParameter.model_version_id == model_version_id)
        .order_by(ModelParameter.id)
    ).all()
    series = session.scalars(
        select(FinancialSeries)
        .where(FinancialSeries.model_version_id == model_version_id)
        .order_by(FinancialSeries.id)
    ).all()
    outputs = session.scalars(
        select(CanonicalOutput)
        .where(CanonicalOutput.model_version_id == model_version_id)
        .order_by(CanonicalOutput.id)
    ).all()
    values = session.scalars(
        select(FinancialSeriesValue)
        .where(FinancialSeriesValue.financial_series_id.in_([item.id for item in series]))
        .order_by(FinancialSeriesValue.id)
    ).all()
    return (
        (model.id, model.status, model.validation_status),
        tuple((item.id, item.validated_value_json) for item in parameters),
        tuple(
            (item.id, item.business_role, item.raw_value_json)
            for item in outputs
        ),
        tuple((item.id, item.label) for item in series),
        tuple((item.id, item.value_json) for item in values),
    )


def test_full_calculation_api_flow_is_idempotent_and_preserves_canonical_rows(
    api_context,
) -> None:
    context = api_context
    client = context["client"]
    model_id = context["model_version_id"]
    setup = context["session_factory"]()
    try:
        canonical_before = _api_canonical_fingerprint(setup, model_id)
    finally:
        setup.close()

    readiness_before = client.get(
        f"/api/v1/models/{model_id}/calculation/readiness"
    )
    prepared = client.post(
        f"/api/v1/models/{model_id}/calculation/prepare"
    )
    prepared_replay = client.post(
        f"/api/v1/models/{model_id}/calculation/prepare",
        json={},
    )
    readiness_after = client.get(
        f"/api/v1/models/{model_id}/calculation/readiness"
    )
    inputs = client.get(f"/api/v1/models/{model_id}/calculation/inputs")
    graph_id = prepared.json()["graph_version_id"]
    baseline_request = {
        "graph_version_id": graph_id,
        "overrides": [],
        "idempotency_key": None,
    }
    baseline = client.post(
        f"/api/v1/models/{model_id}/calculations",
        json=baseline_request,
    )
    baseline_replay = client.post(
        f"/api/v1/models/{model_id}/calculations",
        json=baseline_request,
    )
    override_request = {
        "graph_version_id": graph_id,
        "overrides": [
            {
                "target": {
                    "kind": "parameter",
                    "parameter_id": context["parameter_id"],
                },
                "value": {"value_type": "number", "value": "10"},
            }
        ],
        "idempotency_key": None,
    }
    override = client.post(
        f"/api/v1/models/{model_id}/calculations",
        json=override_request,
    )
    override_replay = client.post(
        f"/api/v1/models/{model_id}/calculations",
        json=override_request,
    )
    baseline_get = client.get(
        f"/api/v1/calculation-runs/{baseline.json()['calculation_run_id']}"
    )
    override_get = client.get(
        f"/api/v1/calculation-runs/{override.json()['calculation_run_id']}"
    )

    assert readiness_before.status_code == 200
    assert readiness_before.json()["status"] == "not_prepared"
    assert prepared.status_code == prepared_replay.status_code == 200
    assert prepared.json()["status"] == "ready_with_warning"
    assert prepared_replay.json()["calculation_rule_extraction_id"] == (
        prepared.json()["calculation_rule_extraction_id"]
    )
    assert prepared_replay.json()["graph_version_id"] == graph_id
    assert readiness_after.json()["status"] == "ready_with_warning"
    assert inputs.status_code == 200
    assert inputs.json()["inputs"][0]["target_id"] == context["parameter_id"]
    assert baseline.status_code == baseline_replay.status_code == 200
    assert override.status_code == override_replay.status_code == 200
    assert baseline_replay.json()["calculation_run_id"] == (
        baseline.json()["calculation_run_id"]
    )
    assert override_replay.json()["calculation_run_id"] == (
        override.json()["calculation_run_id"]
    )
    assert baseline.json()["summary"]["calculated_formula_cells"] == 7
    assert override.json()["summary"] == {
        **override.json()["summary"],
        "calculated_formula_cells": 5,
        "reused_formula_cells": 2,
        "dirty_formula_cells": 5,
    }
    assert baseline_get.status_code == override_get.status_code == 200
    assert baseline_get.json() == baseline.json()
    assert override_get.json() == override.json()

    verification = context["session_factory"]()
    try:
        assert _api_canonical_fingerprint(verification, model_id) == canonical_before
        assert verification.get(ModelVersion, model_id).status == "materialized"
        assert verification.scalar(
            select(func.count()).select_from(CalculationRuleExtraction)
        ) == 1
        assert verification.scalar(
            select(func.count()).select_from(CalculationGraphVersionRecord)
        ) == 1
        assert verification.scalar(
            select(func.count()).select_from(CalculationRunRecord)
        ) == 2
        assert verification.scalar(
            select(func.count()).select_from(CalculationRunValueRecord)
        ) == 20
    finally:
        verification.close()
