"""Service and persistence tests for deterministic calculation API integration."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import uuid

import pytest
from sqlalchemy import func, select

from apps.api.app.calculation_rules.models import (
    CalculationRuleExtraction,
    ExecutableFormulaRule,
    WorkbookFormulaCellRecord,
)
from apps.api.app.calculation_rules.phase2_models import (
    CalculationGraphVersionRecord,
    CalculationRunRecord,
    CalculationRunValueRecord,
)
from apps.api.app.calculation_rules.phase2_repository import Phase2CalculationRepository
from apps.api.app.calculation_rules.phase2_service import InternalCalculationEngineService
from apps.api.app.calculation_rules.phase2_types import Phase2CalculationConfiguration
from apps.api.app.calculation_rules.repository import CalculationRuleRepository
from apps.api.app.calculation_rules.types import (
    CalculationRuleExtractionConfiguration,
    FormulaIdFactory,
)
from apps.api.app.database import Base
from apps.api.app.model_extraction_models import (
    CanonicalOutput,
    FinancialSeries,
    FinancialSeriesValue,
    ModelParameter,
    ModelVersion,
)
from apps.api.app.model_extraction_read_service import ModelExtractionReadService
from apps.api.app.model_extraction_types import (
    FinancialEntityIdFactory,
    ModelExtractionPersistenceError,
    new_uuid,
)
from tests.calculation_rule_test_support import create_materialized_rule_model
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)
from apps.api.app.workbook_storage import DatabaseWorkbookStorage


@pytest.fixture
def integration_context(tmp_path: Path, request):
    parameter = getattr(request, "param", True)
    if isinstance(parameter, dict):
        include_calculation_properties = parameter.get(
            "include_calculation_properties",
            True,
        )
        include_kpi_formulas = parameter.get("include_kpi_formulas", False)
    else:
        include_calculation_properties = parameter
        include_kpi_formulas = False
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "calculation-integration.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    storage, workbook, model, parameter, series, series_value = (
        create_materialized_rule_model(
            session,
            include_calculation_properties=include_calculation_properties,
            include_kpi_formulas=include_kpi_formulas,
        )
    )
    other_model = ModelVersion(
        id=new_uuid(),
        workbook_version_id=workbook.id,
        upload_filename="other-model.xlsx",
        status="materialized",
        validation_status="validated",
        submitted=True,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    session.add(other_model)
    session.commit()
    read_service = ModelExtractionReadService(session, storage)
    try:
        yield {
            "engine": engine,
            "session_factory": session_factory,
            "session": session,
            "storage": storage,
            "workbook": workbook,
            "model": model,
            "other_model": other_model,
            "parameter": parameter,
            "series": series,
            "series_value": series_value,
            "read_service": read_service,
        }
    finally:
        session.close()
        engine.dispose()


def test_parameter_lookup_enforces_exact_model_ownership(integration_context) -> None:
    context = integration_context

    parameter = context["read_service"].get_parameter(
        context["model"].id,
        context["parameter"].id,
    )

    assert parameter.id == context["parameter"].id
    assert parameter.model_version_id == context["model"].id
    with pytest.raises(ModelExtractionPersistenceError):
        context["read_service"].get_parameter(
            context["other_model"].id,
            context["parameter"].id,
        )


def test_financial_series_value_lookup_enforces_exact_model_ownership(
    integration_context,
) -> None:
    context = integration_context

    resolution = context["read_service"].get_financial_series_value(
        context["model"].id,
        context["series_value"].id,
    )

    assert resolution.value.id == context["series_value"].id
    assert resolution.series.model_version_id == context["model"].id
    with pytest.raises(ModelExtractionPersistenceError):
        context["read_service"].get_financial_series_value(
            context["other_model"].id,
            context["series_value"].id,
        )


def test_formula_backed_canonical_input_is_not_editable(integration_context) -> None:
    context = integration_context

    calculation_input = context["read_service"].get_calculation_input(
        context["model"].id,
        "financial_series_value",
        context["series_value"].id,
    )

    assert calculation_input.formula_backed is True
    assert calculation_input.editable is False
    assert calculation_input.non_editable_reason == "formula_backed"
    assert calculation_input.source_sheet == "Calc"
    assert calculation_input.source_cell == "B2"


@pytest.mark.parametrize(
    ("status", "warnings"),
    [
        ("running", []),
        ("completed", []),
        ("completed_with_warning", ["unsupported_formula_cells"]),
        ("failed", []),
    ],
)
def test_phase1_preparation_state_reloads_by_deterministic_identity(
    integration_context,
    status: str,
    warnings: list[str],
) -> None:
    context = integration_context
    configuration = CalculationRuleExtractionConfiguration()
    extraction_id = FormulaIdFactory.extraction_id(
        context["model"].id,
        context["workbook"].id,
        configuration,
    )
    context["session"].add(
        CalculationRuleExtraction(
            id=extraction_id,
            workbook_version_id=context["workbook"].id,
            model_version_id=context["model"].id,
            inventory_version=configuration.inventory_version,
            compiler_version=configuration.compiler_version,
            ir_version=configuration.ir_version,
            engine_version=configuration.engine_version,
            function_registry_version=configuration.function_registry_version,
            semantics_profile=configuration.semantics_profile,
            configuration_hash=configuration.configuration_hash,
            status=status,
            summary_json={"formula_cells_total": 10},
            warnings_json=warnings,
            error_code="PHASE1_FAILED" if status == "failed" else None,
            error_message="sanitized failure" if status == "failed" else None,
        )
    )
    context["session"].commit()

    state = CalculationRuleRepository(context["session"]).find_preparation(
        context["model"].id,
        context["workbook"].id,
        configuration,
    )

    assert state is not None
    assert state.calculation_rule_extraction_id == extraction_id
    assert state.status == status
    assert state.summary == {"formula_cells_total": 10}
    assert state.warnings == tuple(warnings)


def test_matching_graph_and_stale_graph_are_distinguished(integration_context) -> None:
    context = integration_context
    configuration = Phase2CalculationConfiguration()
    compiled = InternalCalculationEngineService(
        context["session"],
        context["read_service"],
    ).compile_workbook(context["workbook"].id, configuration)
    repository = Phase2CalculationRepository(context["session"])

    graph = repository.find_matching_graph(context["workbook"].id, configuration)

    assert graph is not None
    assert graph.graph_version_id == compiled.graph_version_id
    assert repository.is_current_graph(
        context["workbook"].id,
        compiled.graph_version_id,
        configuration,
    )
    assert not repository.is_current_graph(
        context["workbook"].id,
        str(uuid.uuid4()),
        configuration,
    )


def test_fresh_session_reloads_persisted_graph_metadata(integration_context) -> None:
    context = integration_context
    configuration = Phase2CalculationConfiguration()
    compiled = InternalCalculationEngineService(
        context["session"],
        context["read_service"],
    ).compile_workbook(context["workbook"].id, configuration)
    context["session"].close()

    restarted = context["session_factory"]()
    try:
        graph = Phase2CalculationRepository(restarted).load_graph_metadata(
            compiled.graph_version_id
        )
    finally:
        restarted.close()

    assert graph is not None
    assert graph.graph_version_id == compiled.graph_version_id
    assert graph.workbook_version_id == context["workbook"].id
    assert graph.ir_version == "calc-ir-v2"
    assert graph.compiler_version == "formula-compiler-v3"
    assert graph.function_registry_version == "calc-functions-v3"
    assert graph.semantics_profile == "excel-compatible-kpi-v1"


def _calculation_artifact_counts(session) -> tuple[int, ...]:
    return tuple(
        session.scalar(select(func.count()).select_from(table))
        for table in (
            CalculationRuleExtraction,
            WorkbookFormulaCellRecord,
            ExecutableFormulaRule,
            CalculationGraphVersionRecord,
            CalculationRunRecord,
            CalculationRunValueRecord,
        )
    )


def _add_phase1_state(context, status: str) -> str:
    configuration = CalculationRuleExtractionConfiguration()
    extraction_id = FormulaIdFactory.extraction_id(
        context["model"].id,
        context["workbook"].id,
        configuration,
    )
    context["session"].add(
        CalculationRuleExtraction(
            id=extraction_id,
            workbook_version_id=context["workbook"].id,
            model_version_id=context["model"].id,
            inventory_version=configuration.inventory_version,
            compiler_version=configuration.compiler_version,
            ir_version=configuration.ir_version,
            engine_version=configuration.engine_version,
            function_registry_version=configuration.function_registry_version,
            semantics_profile=configuration.semantics_profile,
            configuration_hash=configuration.configuration_hash,
            status=status,
            summary_json={
                "formula_cells_total": 10,
                "formula_cells_executable": 8,
            },
            warnings_json=(
                ["unsupported_formula_cells"]
                if status == "completed_with_warning"
                else []
            ),
            error_code="CALCULATION_RULE_EXTRACTION_FAILED"
            if status == "failed"
            else None,
            error_message="Calculation rule extraction failed"
            if status == "failed"
            else None,
        )
    )
    context["session"].commit()
    return extraction_id


@pytest.mark.parametrize(
    ("phase1_status", "with_graph", "expected_status"),
    [
        ("non_materialized", False, "model_not_ready"),
        (None, False, "not_prepared"),
        ("running", False, "preparing"),
        ("failed", False, "failed"),
        ("completed", False, "not_prepared"),
        ("completed", True, "ready"),
        ("completed_with_warning", True, "ready_with_warning"),
    ],
)
def test_readiness_maps_persisted_state_without_creating_artifacts(
    integration_context,
    phase1_status: str | None,
    with_graph: bool,
    expected_status: str,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    model = context["model"]
    extraction_id = None
    if phase1_status == "non_materialized":
        model.status = "extracted"
        context["session"].commit()
    elif phase1_status is not None:
        extraction_id = _add_phase1_state(context, phase1_status)
    if with_graph:
        InternalCalculationEngineService(
            context["session"],
            context["read_service"],
        ).compile_workbook(context["workbook"].id)

    before = _calculation_artifact_counts(context["session"])
    readiness = CalculationIntegrationService(
        context["session"],
        context["read_service"],
    ).get_readiness(model.id)
    after = _calculation_artifact_counts(context["session"])

    assert readiness.model_version_id == model.id
    assert readiness.workbook_version_id == context["workbook"].id
    assert readiness.model_status == model.status
    assert readiness.status == expected_status
    assert readiness.calculation_rule_extraction_id == extraction_id
    assert readiness.graph_version_id is not None if with_graph else (
        readiness.graph_version_id is None
    )
    assert readiness.versions.phase1_ir == "calc-ir-v1"
    assert readiness.versions.phase2_ir == "calc-ir-v2"
    assert readiness.versions.compiler == "formula-compiler-v3"
    assert readiness.versions.engine == "calc-engine-v3"
    assert readiness.versions.registry == "calc-functions-v3"
    assert readiness.versions.semantics == "excel-compatible-kpi-v1"
    if with_graph:
        assert readiness.summary.graph_nodes == 10
    if phase1_status == "failed":
        assert readiness.error is not None
        assert readiness.error.code == "CALCULATION_PREPARATION_FAILED"
    else:
        assert readiness.error is None
    assert after == before


def _canonical_fingerprint(session, model_version_id: str) -> dict[str, object]:
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
    series_ids = [item.id for item in series]
    values = session.scalars(
        select(FinancialSeriesValue)
        .where(FinancialSeriesValue.financial_series_id.in_(series_ids))
        .order_by(FinancialSeriesValue.id)
    ).all()
    return {
        "model": (
            model.id,
            model.workbook_version_id,
            model.status,
            model.validation_status,
        ),
        "parameters": tuple(
            (
                item.id,
                item.source_sheet,
                item.source_cell,
                json.dumps(item.validated_value_json, sort_keys=True),
            )
            for item in parameters
        ),
        "outputs": tuple(
            (
                item.id,
                item.business_role,
                item.source_sheet,
                item.source_cell,
                json.dumps(item.raw_value_json, sort_keys=True),
            )
            for item in outputs
        ),
        "series": tuple(
            (item.id, item.label, item.value_source_range) for item in series
        ),
        "values": tuple(
            (
                item.id,
                item.financial_series_id,
                item.value_source_sheet,
                item.value_source_cell,
                json.dumps(item.value_json, sort_keys=True),
            )
            for item in values
        ),
    }


class _ExplodingInventory:
    def scan(self, _content_bytes, _workbook_version_id):
        raise RuntimeError("internal workbook details must not cross the facade")


def _preparation_failure_log_payload(caplog) -> dict[str, object]:
    prefix = "Calculation preparation failed: "
    matching = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith(prefix)
    ]
    assert len(matching) == 1
    return json.loads(matching[0][len(prefix) :])


def _assert_sanitized_traceback(payload: dict[str, object]) -> None:
    frames = payload["traceback"]
    assert isinstance(frames, list)
    assert frames
    assert all(
        set(frame) == {"file", "function", "line"}
        and isinstance(frame["file"], str)
        and isinstance(frame["function"], str)
        and isinstance(frame["line"], int)
        for frame in frames
    )


def test_preparation_is_successful_and_replay_is_idempotent(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"],
        context["read_service"],
    )
    canonical_before = _canonical_fingerprint(
        context["session"], context["model"].id
    )

    first = facade.prepare(context["model"].id)
    counts_before_replay = _calculation_artifact_counts(context["session"])
    second = facade.prepare(context["model"].id)
    counts_after_replay = _calculation_artifact_counts(context["session"])

    assert first.status == second.status == "ready_with_warning"
    assert (
        first.calculation_rule_extraction_id
        == second.calculation_rule_extraction_id
    )
    assert first.graph_version_id == second.graph_version_id
    assert counts_before_replay == counts_after_replay
    assert context["session"].scalar(
        select(func.count()).select_from(CalculationRuleExtraction)
    ) == 1
    assert context["session"].scalar(
        select(func.count()).select_from(CalculationGraphVersionRecord)
    ) == 1
    assert _canonical_fingerprint(
        context["session"], context["model"].id
    ) == canonical_before

def test_preparation_rejects_non_materialized_model_without_artifacts(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )

    context = integration_context
    context["model"].status = "extracted"
    context["session"].commit()
    before = _calculation_artifact_counts(context["session"])

    with pytest.raises(CalculationIntegrationError) as captured:
        CalculationIntegrationService(
            context["session"],
            context["read_service"],
        ).prepare(context["model"].id)

    assert captured.value.code == "MODEL_NOT_MATERIALIZED"
    assert captured.value.status_code == 409
    assert _calculation_artifact_counts(context["session"]) == before
    assert context["session"].get(ModelVersion, context["model"].id).status == "extracted"


@pytest.mark.parametrize("integration_context", [False], indirect=True)
def test_phase1_preparation_failure_preserves_canonical_state_and_retry_converges(
    integration_context,
    caplog,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )
    from apps.api.app.calculation_rules.service import CalculationRuleExtractionService

    context = integration_context
    canonical_before = _canonical_fingerprint(
        context["session"], context["model"].id
    )
    failing_phase1 = CalculationRuleExtractionService(
        context["session"],
        context["read_service"],
        inventory=_ExplodingInventory(),
    )
    caplog.set_level(
        logging.ERROR,
        logger="uvicorn.error",
    )

    with pytest.raises(CalculationIntegrationError) as captured:
        CalculationIntegrationService(
            context["session"],
            context["read_service"],
            phase1_service=failing_phase1,
        ).prepare(context["model"].id)

    failed = context["session"].scalar(select(CalculationRuleExtraction))
    assert captured.value.code == "CALCULATION_PREPARATION_FAILED"
    assert captured.value.detail() == {
        "code": "CALCULATION_PREPARATION_FAILED",
        "message": "Calculation preparation failed.",
        "retryable": False,
        "resource_id": context["model"].id,
    }
    log_payload = _preparation_failure_log_payload(caplog)
    assert log_payload["model_version_id"] == context["model"].id
    assert log_payload["workbook_version_id"] == context["workbook"].id
    assert log_payload["calculation_rule_extraction_id"] == failed.id
    assert log_payload["failure_stage"] == "phase1_preparation"
    assert log_payload["exception_type"] == "RuntimeError"
    _assert_sanitized_traceback(log_payload)
    assert "internal workbook details must not cross the facade" not in caplog.text
    assert "=SUM(" not in caplog.text
    assert failed.status == "failed"
    assert failed.error_message == "Calculation rule extraction failed"
    assert context["session"].scalar(
        select(func.count()).select_from(CalculationGraphVersionRecord)
    ) == 0
    assert _canonical_fingerprint(
        context["session"], context["model"].id
    ) == canonical_before

    retried = CalculationIntegrationService(
        context["session"],
        context["read_service"],
    ).prepare(context["model"].id)

    assert retried.status == "ready_with_warning"
    assert retried.calculation_rule_extraction_id == failed.id
    assert context["session"].scalar(
        select(func.count()).select_from(CalculationRuleExtraction)
    ) == 1
    assert _canonical_fingerprint(
        context["session"], context["model"].id
    ) == canonical_before


def test_phase2_preparation_failure_preserves_phase1_and_retry_converges(
    integration_context,
    caplog,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )

    context = integration_context
    canonical_before = _canonical_fingerprint(
        context["session"], context["model"].id
    )
    failing_phase2 = InternalCalculationEngineService(
        context["session"],
        context["read_service"],
        inventory=_ExplodingInventory(),
    )
    caplog.set_level(
        logging.ERROR,
        logger="uvicorn.error",
    )

    with pytest.raises(CalculationIntegrationError) as captured:
        CalculationIntegrationService(
            context["session"],
            context["read_service"],
            phase2_service=failing_phase2,
        ).prepare(context["model"].id)

    phase1 = context["session"].scalar(select(CalculationRuleExtraction))
    assert captured.value.code == "CALCULATION_PREPARATION_FAILED"
    assert captured.value.detail() == {
        "code": "CALCULATION_PREPARATION_FAILED",
        "message": "Calculation preparation failed.",
        "retryable": False,
        "resource_id": context["model"].id,
    }
    log_payload = _preparation_failure_log_payload(caplog)
    assert log_payload["model_version_id"] == context["model"].id
    assert log_payload["workbook_version_id"] == context["workbook"].id
    assert log_payload["calculation_rule_extraction_id"] == phase1.id
    assert log_payload["failure_stage"] == "phase2_compilation"
    assert log_payload["exception_type"] == "RuntimeError"
    _assert_sanitized_traceback(log_payload)
    assert "internal workbook details must not cross the facade" not in caplog.text
    assert "=SUM(" not in caplog.text
    assert phase1.status == "completed_with_warning"
    assert context["session"].scalar(
        select(func.count()).select_from(CalculationGraphVersionRecord)
    ) == 0
    assert _canonical_fingerprint(
        context["session"], context["model"].id
    ) == canonical_before

    retried = CalculationIntegrationService(
        context["session"],
        context["read_service"],
    ).prepare(context["model"].id)

    assert retried.status == "ready_with_warning"
    assert retried.calculation_rule_extraction_id == phase1.id
    assert retried.graph_version_id is not None
    assert _canonical_fingerprint(
        context["session"], context["model"].id
    ) == canonical_before


def test_list_inputs_defaults_to_editable_parameters_and_includes_graph(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)

    response = facade.list_inputs(context["model"].id)

    assert response.model_version_id == context["model"].id
    assert response.graph_version_id == prepared.graph_version_id
    assert len(response.inputs) == 1
    item = response.inputs[0]
    assert item.target_kind == "parameter"
    assert item.target_id == context["parameter"].id
    assert item.current_value.value_type == "number"
    assert item.current_value.value == "2"
    assert item.editable is True
    assert item.non_editable_reason is None
    assert "source_sheet" not in item.model_dump()
    assert "source_cell" not in item.model_dump()


def test_get_input_returns_one_exact_canonical_item(integration_context) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )

    item = facade.get_input(
        context["model"].id,
        "parameter",
        context["parameter"].id,
    )

    assert item.target_kind == "parameter"
    assert item.target_id == context["parameter"].id
    assert item.current_value.value_type == "number"
    assert item.current_value.value == "2"
    assert item.editable is True


@pytest.mark.parametrize(
    ("case", "expected_code", "expected_status"),
    [
        ("unknown_model", "MODEL_VERSION_NOT_FOUND", 404),
        ("model_not_materialized", "MODEL_NOT_MATERIALIZED", 409),
        ("unknown_target", "INVALID_OVERRIDE_TARGET", 422),
        ("unsupported_value", "INVALID_OVERRIDE_VALUE", 422),
    ],
)
def test_get_input_preserves_structured_model_target_and_value_errors(
    integration_context,
    case: str,
    expected_code: str,
    expected_status: int,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )

    context = integration_context
    model_id = context["model"].id
    target_id = context["parameter"].id
    if case == "unknown_model":
        model_id = str(uuid.uuid4())
    elif case == "model_not_materialized":
        context["model"].status = "extracting"
        context["session"].commit()
    elif case == "unknown_target":
        target_id = str(uuid.uuid4())
    elif case == "unsupported_value":
        context["parameter"].validated_value_json = {"unsupported": True}
        context["parameter"].data_type = "x"
        context["session"].commit()

    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )

    with pytest.raises(CalculationIntegrationError) as captured:
        facade.get_input(model_id, "parameter", target_id)

    assert captured.value.code == expected_code
    assert captured.value.status_code == expected_status
    assert captured.value.resource_id == (
        model_id
        if case in {"unknown_model", "model_not_materialized"}
        else target_id
    )


def test_list_inputs_filters_formula_backed_financial_series_values(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    facade.prepare(context["model"].id)

    editable = facade.list_inputs(
        context["model"].id,
        target_kind="financial_series_value",
    )
    all_values = facade.list_inputs(
        context["model"].id,
        target_kind="financial_series_value",
        editable_only=False,
    )

    assert editable.inputs == []
    assert len(all_values.inputs) == 1
    assert all_values.inputs[0].target_id == context["series_value"].id
    assert all_values.inputs[0].editable is False
    assert all_values.inputs[0].non_editable_reason == "formula_backed"
    assert all_values.inputs[0].period == "2026"


def test_list_inputs_has_stable_uuid_cursor_pagination(integration_context) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    id_factory = FinancialEntityIdFactory(context["model"].id)
    context["session"].add_all(
        [
            ModelParameter(
                id=id_factory.parameter_id("Inputs", address),
                model_version_id=context["model"].id,
                entity_kind="parameter",
                source_bucket="parameter_candidates",
                label=label,
                submitted_role="hardcoded_input",
                validated_role="hardcoded_input",
                raw_value_json=value,
                validated_value_json=value,
                source_sheet="Inputs",
                source_cell=address,
                formula_status="static_value",
                source_validation_status="validated",
                role_validation_status="validated",
                validation_status="validated",
                data_type="n",
                number_format="General",
            )
            for address, label, value in (
                ("A2", "Price", 3),
                ("A3", "Tax", 4),
            )
        ]
    )
    context["session"].commit()
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    facade.prepare(context["model"].id)

    first = facade.list_inputs(context["model"].id, limit=1)
    second = facade.list_inputs(
        context["model"].id,
        limit=10,
        cursor=first.next_cursor,
    )
    ids = [first.inputs[0].target_id, *(item.target_id for item in second.inputs)]

    assert ids == sorted(ids)
    assert len(ids) == 3
    assert first.next_cursor == first.inputs[0].target_id
    assert second.next_cursor is None


def test_list_inputs_rejects_unprepared_model(integration_context) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )

    context = integration_context

    with pytest.raises(CalculationIntegrationError) as captured:
        CalculationIntegrationService(
            context["session"], context["read_service"]
        ).list_inputs(context["model"].id)

    assert captured.value.code == "CALCULATION_NOT_PREPARED"
    assert captured.value.status_code == 409


def test_list_inputs_rejects_unknown_target_kind(integration_context) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    facade.prepare(context["model"].id)

    with pytest.raises(CalculationIntegrationError) as captured:
        facade.list_inputs(context["model"].id, target_kind="cell")

    assert captured.value.code == "INVALID_INPUT_KIND"
    assert captured.value.status_code == 422


def _calculation_request(
    graph_version_id: str,
    *overrides: dict[str, object],
):
    from apps.api.app.schemas import CalculationRequest

    return CalculationRequest.model_validate(
        {
            "graph_version_id": graph_version_id,
            "overrides": list(overrides),
            "idempotency_key": None,
        }
    )


def _run_row_counts(session) -> tuple[int, int]:
    return (
        session.scalar(select(func.count()).select_from(CalculationRunRecord)),
        session.scalar(select(func.count()).select_from(CalculationRunValueRecord)),
    )


def test_baseline_calculation_replay_is_idempotent_and_canonical_is_immutable(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    request = _calculation_request(prepared.graph_version_id)
    canonical_before = _canonical_fingerprint(
        context["session"], context["model"].id
    )

    first = facade.calculate(context["model"].id, request)
    counts_before_replay = _run_row_counts(context["session"])
    second = facade.calculate(context["model"].id, request)
    counts_after_replay = _run_row_counts(context["session"])

    assert first.calculation_run_id == second.calculation_run_id
    assert first.graph_version_id == prepared.graph_version_id
    assert first.base_run_id is None
    assert first.status == "completed_with_warning"
    assert first.summary.calculated_formula_cells == 7
    assert first.summary.reused_formula_cells == 0
    assert first.summary.dirty_formula_cells == 7
    assert counts_before_replay == counts_after_replay == (1, 10)
    values = {f"{item.sheet_name}!{item.cell_address}": item for item in first.values}
    assert values["Calc!B2"].value.value_type == "number"
    assert values["Calc!B2"].value.value == "10"
    assert _canonical_fingerprint(
        context["session"], context["model"].id
    ) == canonical_before


def test_parameter_override_creates_distinct_immutable_incremental_run(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )
    canonical_before = _canonical_fingerprint(
        context["session"], context["model"].id
    )
    request = _calculation_request(
        prepared.graph_version_id,
        {
            "target": {
                "kind": "parameter",
                "parameter_id": context["parameter"].id,
            },
            "value": {"value_type": "number", "value": "10"},
        },
    )

    changed = facade.calculate(context["model"].id, request)
    replayed = facade.calculate(context["model"].id, request)

    assert changed.calculation_run_id != baseline.calculation_run_id
    assert replayed.calculation_run_id == changed.calculation_run_id
    assert changed.base_run_id == baseline.calculation_run_id
    assert changed.summary.calculated_formula_cells == 5
    assert changed.summary.reused_formula_cells == 2
    assert changed.summary.dirty_formula_cells == 5
    values = {f"{item.sheet_name}!{item.cell_address}": item for item in changed.values}
    assert values["Calc!B2"].value.value == "26"
    assert _run_row_counts(context["session"]) == (2, 20)
    assert _canonical_fingerprint(
        context["session"], context["model"].id
    ) == canonical_before


def test_run_outputs_project_scalar_and_series_baseline_current_values(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    context["session"].add(
        FinancialSeriesValue(
            id=FinancialEntityIdFactory(context["model"].id).value_id(
                context["series"].id,
                1,
            ),
            financial_series_id=context["series"].id,
            period_index=1,
            raw_period_label_json=2027,
            display_period_label="2027",
            period_type="annual",
            year=2027,
            is_forecast=True,
            value_json=None,
            period_source_sheet="Calc",
            period_source_cell="A2",
            value_source_sheet="Calc",
            value_source_cell="B8",
            exact_formula="=IF(TRUE,B2,1/0)",
            formula_status="formula_no_cache",
            cached_value_available=False,
            cached_value_freshness="missing",
            number_format="General",
            data_type="f",
        )
    )
    context["session"].commit()
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )
    override = facade.calculate(
        context["model"].id,
        _calculation_request(
            prepared.graph_version_id,
            {
                "target": {
                    "kind": "parameter",
                    "parameter_id": context["parameter"].id,
                },
                "value": {"value_type": "number", "value": "10"},
            },
        ),
    )

    projection = facade.get_run_outputs(override.calculation_run_id)

    assert projection.calculation_run_id == override.calculation_run_id
    assert projection.base_run_id == baseline.calculation_run_id
    assert projection.model_version_id == context["model"].id
    by_role = {item.business_role: item for item in projection.outputs}

    scalar = by_role["total_project_cost"]
    assert scalar.entity_kind == "scalar"
    assert scalar.mapping_status == "mapped"
    assert scalar.support_status == "supported"
    assert scalar.number_format == "General"
    assert scalar.availability_status == "available"
    assert scalar.baseline.availability_status == "available"
    assert scalar.baseline.value.value_type == "number"
    assert scalar.baseline.value.value == "5"
    assert scalar.current.availability_status == "available"
    assert scalar.current.value.value_type == "number"
    assert scalar.current.value.value == "13"

    series = by_role["revenue"]
    assert series.entity_kind == "series"
    assert series.availability_status == "available"
    assert len(series.points) == 2
    assert series.points[0].financial_series_value_id == (
        context["series_value"].id
    )
    assert [point.period for point in series.points] == ["2026", "2027"]
    assert {point.mapping_status for point in series.points} == {"mapped"}
    assert {point.support_status for point in series.points} == {"supported"}
    assert {point.number_format for point in series.points} == {"General"}
    assert [point.baseline.value.value for point in series.points] == ["10", "10"]
    assert [point.current.value.value for point in series.points] == ["26", "26"]


def test_multiple_overrides_project_against_comparison_baseline(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )
    override_a = facade.calculate(
        context["model"].id,
        _calculation_request(
            prepared.graph_version_id,
            {
                "target": {
                    "kind": "parameter",
                    "parameter_id": context["parameter"].id,
                },
                "value": {"value_type": "number", "value": "10"},
            },
        ),
    )
    override_b = facade.calculate(
        context["model"].id,
        _calculation_request(
            prepared.graph_version_id,
            {
                "target": {
                    "kind": "parameter",
                    "parameter_id": context["parameter"].id,
                },
                "value": {"value_type": "number", "value": "20"},
            },
        ),
    )

    projection = facade.get_run_outputs(override_b.calculation_run_id)
    scalar = next(
        item
        for item in projection.outputs
        if item.business_role == "total_project_cost"
    )

    assert override_b.base_run_id == override_a.calculation_run_id
    assert projection.base_run_id == override_a.calculation_run_id
    assert (
        projection.comparison_baseline_run_id
        == baseline.calculation_run_id
    )
    assert scalar.baseline.value.value == "5"
    assert scalar.current.value.value == "23"


def test_projection_requires_zero_override_baseline_with_matching_policy(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    idempotency_baseline_request = _calculation_request(
        prepared.graph_version_id
    ).model_copy(update={"idempotency_key": "policy-specific-baseline"})
    baseline = facade.calculate(
        context["model"].id,
        idempotency_baseline_request,
    )
    override = facade.calculate(
        context["model"].id,
        _calculation_request(
            prepared.graph_version_id,
            {
                "target": {
                    "kind": "parameter",
                    "parameter_id": context["parameter"].id,
                },
                "value": {"value_type": "number", "value": "10"},
            },
        ),
    )

    assert override.base_run_id == baseline.calculation_run_id
    with pytest.raises(CalculationIntegrationError) as captured:
        facade.get_run_outputs(override.calculation_run_id)

    assert captured.value.code == "CALCULATION_BASELINE_NOT_FOUND"
    assert captured.value.status_code == 409


def test_run_outputs_keep_unsupported_output_explicitly_unavailable(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    context["session"].add(
        CanonicalOutput(
            id=FinancialEntityIdFactory(context["model"].id).output_id(
                "Calc",
                "B7",
            ),
            model_version_id=context["model"].id,
            entity_kind="canonical_output",
            label="Project IRR",
            business_role="project_irr",
            submitted_role="formula_output",
            validated_role="formula_output",
            raw_value_json=0.1234,
            unit="%",
            scenario="base",
            source_sheet="Calc",
            source_cell="B7",
            exact_formula="='[rates.xlsx]Inputs'!A1+1",
            formula_status="formula_cached",
            source_validation_status="validated",
            role_validation_status="validated",
            validation_status="validated",
            data_type="f",
            number_format="0.00%",
        )
    )
    context["session"].commit()
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )

    projection = facade.get_run_outputs(baseline.calculation_run_id)

    output = next(
        item for item in projection.outputs if item.business_role == "project_irr"
    )
    assert output.availability_status == "unavailable"
    assert output.baseline.value is None
    assert output.current.value is None
    assert output.support_status == "external_reference"
    assert output.current.execution_status == "not_executable"
    assert output.current.unavailable_reason == "not_executable"


def test_run_outputs_isolate_missing_mapping_from_available_outputs(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    context["session"].add(
        CanonicalOutput(
            id=FinancialEntityIdFactory(context["model"].id).output_id(
                "Calc",
                "C10",
            ),
            model_version_id=context["model"].id,
            entity_kind="canonical_output",
            label="NPV",
            business_role="npv",
            submitted_role="formula_output",
            validated_role="formula_output",
            raw_value_json=999,
            unit="USD",
            scenario="base",
            source_sheet="Calc",
            source_cell="C10",
            exact_formula="=SUM(Inputs!A1:A2)",
            formula_status="formula_cached",
            source_validation_status="validated",
            role_validation_status="validated",
            validation_status="validated",
            data_type="f",
            number_format="General",
        )
    )
    context["session"].commit()
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )

    projection = facade.get_run_outputs(baseline.calculation_run_id)

    by_role = {item.business_role: item for item in projection.outputs}
    assert by_role["npv"].formula_cell_id is None
    assert by_role["npv"].mapping_status == "missing"
    assert by_role["npv"].support_status == "not_prepared"
    assert by_role["npv"].availability_status == "unavailable"
    assert by_role["npv"].current.value is None
    assert by_role["npv"].current.unavailable_reason == "formula_cell_missing"
    assert by_role["total_project_cost"].availability_status == "available"
    assert by_role["total_project_cost"].current.value.value == "5"


@pytest.mark.parametrize(
    "integration_context",
    [{"include_kpi_formulas": True}],
    indirect=True,
)
def test_numeric_canonical_kpi_formulas_project_without_derived_fallbacks(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    id_factory = FinancialEntityIdFactory(context["model"].id)
    definitions = (
        ("C1", "Project IRR", "project_irr", "%", "=IRR(Inputs!C1:C2)"),
        ("C2", "NPV", "npv", "USD", "=NPV(10%,Inputs!D1:D2)"),
        (
            "C3",
            "Minimum DSCR",
            "minimum_dscr",
            "x",
            '=MINIFS(Inputs!E1:E3,Inputs!E1:E3,">0")',
        ),
        ("C4", "Payback", "payback_period", "years", "=Inputs!F1"),
        (
            "C5",
            "Equity Multiple",
            "equity_multiple",
            "x",
            "=Inputs!G2/Inputs!G1",
        ),
    )
    for cell, label, role, unit, formula in definitions:
        context["session"].add(
            CanonicalOutput(
                id=id_factory.output_id("Calc", cell),
                model_version_id=context["model"].id,
                entity_kind="canonical_output",
                label=label,
                business_role=role,
                submitted_role="formula_output",
                validated_role="formula_output",
                raw_value_json=999,
                unit=unit,
                scenario="base",
                source_sheet="Calc",
                source_cell=cell,
                exact_formula=formula,
                formula_status="formula_cached",
                source_validation_status="validated",
                role_validation_status="validated",
                validation_status="validated",
                data_type="f",
                number_format="General",
            )
        )
    context["session"].commit()
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )

    projection = facade.get_run_outputs(baseline.calculation_run_id)
    by_role = {item.business_role: item for item in projection.outputs}

    expected = {
        "project_irr": 0.1,
        "npv": 104.13223140495867,
        "minimum_dscr": 1.2,
        "payback_period": 5.0,
        "equity_multiple": 2.5,
    }
    for role, expected_value in expected.items():
        output = by_role[role]
        assert output.availability_status == "available"
        assert output.current.execution_status == "executed"
        assert float(output.current.value.value) == pytest.approx(expected_value)
        assert float(output.baseline.value.value) == pytest.approx(expected_value)
    assert "missing_kpi" not in by_role


def test_run_outputs_use_persisted_expression_support_not_latest_rule(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )
    formula_cell = context["session"].scalar(
        select(WorkbookFormulaCellRecord).where(
            WorkbookFormulaCellRecord.workbook_version_id
            == context["workbook"].id,
            WorkbookFormulaCellRecord.sheet_name == "Calc",
            WorkbookFormulaCellRecord.cell_address == "B1",
        )
    )
    context["session"].add(
        ExecutableFormulaRule(
            id=new_uuid(),
            formula_cell_id=formula_cell.id,
            ir_version="calc-ir-v2",
            compiler_version="future-formula-compiler",
            semantics_profile="excel-compatible-v2",
            formula_sha256=formula_cell.formula_sha256,
            parse_status="parsed",
            support_status="unsupported",
            ir_json=None,
            unsupported_constructs_json=["FUTURE_POLICY"],
            warnings_json=["future_policy"],
        )
    )
    context["session"].commit()

    discovery = facade.list_outputs(context["model"].id)
    projection = facade.get_run_outputs(baseline.calculation_run_id)

    discovered = next(
        item
        for item in discovery.outputs
        if item.business_role == "total_project_cost"
    )
    projected = next(
        item
        for item in projection.outputs
        if item.business_role == "total_project_cost"
    )
    assert discovered.support_status == "unsupported"
    assert projected.support_status == "supported"


def test_financial_series_value_override_resolves_trusted_canonical_cell(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    value = context["series_value"]
    value.value_json = 3
    value.value_source_sheet = "Inputs"
    value.value_source_cell = "A2"
    value.exact_formula = None
    value.formula_status = "static_value"
    value.cached_value_available = True
    value.cached_value_freshness = "unknown"
    value.data_type = "n"
    context["session"].commit()
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )
    canonical_before = _canonical_fingerprint(
        context["session"], context["model"].id
    )

    result = facade.calculate(
        context["model"].id,
        _calculation_request(
            prepared.graph_version_id,
            {
                "target": {
                    "kind": "financial_series_value",
                    "financial_series_value_id": value.id,
                },
                "value": {"value_type": "number", "value": "7"},
            },
        ),
    )

    values = {f"{item.sheet_name}!{item.cell_address}": item for item in result.values}
    assert values["Calc!B2"].value.value == "18"
    persisted = context["session"].get(CalculationRunRecord, result.calculation_run_id)
    assert persisted.overrides_json[0]["target_kind"] == "cell"
    assert persisted.overrides_json[0]["sheet_name"] == "Inputs"
    assert persisted.overrides_json[0]["cell_address"] == "A2"
    assert _canonical_fingerprint(
        context["session"], context["model"].id
    ) == canonical_before


def test_calculation_rejects_wrong_model_and_formula_backed_targets(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    other_parameter_id = FinancialEntityIdFactory(
        context["other_model"].id
    ).parameter_id("Inputs", "A2")
    context["session"].add(
        ModelParameter(
            id=other_parameter_id,
            model_version_id=context["other_model"].id,
            entity_kind="parameter",
            source_bucket="parameter_candidates",
            label="Other model input",
            submitted_role="hardcoded_input",
            validated_role="hardcoded_input",
            raw_value_json=3,
            validated_value_json=3,
            source_sheet="Inputs",
            source_cell="A2",
            formula_status="static_value",
            source_validation_status="validated",
            role_validation_status="validated",
            validation_status="validated",
            data_type="n",
            number_format="General",
        )
    )
    context["session"].commit()

    with pytest.raises(CalculationIntegrationError) as wrong_model:
        facade.calculate(
            context["model"].id,
            _calculation_request(
                prepared.graph_version_id,
                {
                    "target": {
                        "kind": "parameter",
                        "parameter_id": other_parameter_id,
                    },
                    "value": {"value_type": "number", "value": "4"},
                },
            ),
        )
    with pytest.raises(CalculationIntegrationError) as formula_backed:
        facade.calculate(
            context["model"].id,
            _calculation_request(
                prepared.graph_version_id,
                {
                    "target": {
                        "kind": "financial_series_value",
                        "financial_series_value_id": context["series_value"].id,
                    },
                    "value": {"value_type": "number", "value": "4"},
                },
            ),
        )

    assert wrong_model.value.code == "INVALID_OVERRIDE_TARGET"
    assert formula_backed.value.code == "FORMULA_OVERRIDE_FORBIDDEN"
    assert _run_row_counts(context["session"]) == (0, 0)


def test_calculation_rejects_duplicate_target_and_graph_mismatch(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )
    from apps.api.app.schemas import CalculationOverrideRequest, CalculationRequest

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    override = CalculationOverrideRequest.model_validate(
        {
            "target": {
                "kind": "parameter",
                "parameter_id": context["parameter"].id,
            },
            "value": {"value_type": "number", "value": "5"},
        }
    )
    duplicate_request = CalculationRequest.model_construct(
        graph_version_id=prepared.graph_version_id,
        overrides=[override, override],
        idempotency_key=None,
    )

    with pytest.raises(CalculationIntegrationError) as duplicate:
        facade.calculate(context["model"].id, duplicate_request)
    with pytest.raises(CalculationIntegrationError) as mismatch:
        facade.calculate(
            context["model"].id,
            _calculation_request(str(uuid.uuid4())),
        )

    assert duplicate.value.code == "DUPLICATE_OVERRIDE_TARGET"
    assert mismatch.value.code == "GRAPH_VERSION_MISMATCH"
    assert _run_row_counts(context["session"]) == (0, 0)


class _CalculationMustNotRun:
    def calculate_model(self, *_args, **_kwargs):
        raise AssertionError("GET run must not execute calculation")

    def compile_workbook(self, *_args, **_kwargs):
        raise AssertionError("GET run must not compile calculation")


def test_fresh_session_reloads_completed_baseline_and_override_without_rerun(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )
    override = facade.calculate(
        context["model"].id,
        _calculation_request(
            prepared.graph_version_id,
            {
                "target": {
                    "kind": "parameter",
                    "parameter_id": context["parameter"].id,
                },
                "value": {"value_type": "number", "value": "10"},
            },
        ),
    )
    expected = {
        baseline.calculation_run_id: baseline.model_dump(mode="json"),
        override.calculation_run_id: override.model_dump(mode="json"),
    }
    context["session"].close()

    restarted = context["session_factory"]()
    try:
        before = _calculation_artifact_counts(restarted)
        reloaded_facade = CalculationIntegrationService(
            restarted,
            ModelExtractionReadService(
                restarted,
                DatabaseWorkbookStorage(restarted),
            ),
            phase2_service=_CalculationMustNotRun(),
        )
        reloaded = {
            run_id: reloaded_facade.get_run(run_id).model_dump(mode="json")
            for run_id in expected
        }
        after = _calculation_artifact_counts(restarted)
    finally:
        restarted.close()

    assert reloaded == expected
    assert after == before
    assert reloaded[baseline.calculation_run_id]["versions"] == {
        "phase2_ir": "calc-ir-v2",
        "compiler": "formula-compiler-v3",
        "engine": "calc-engine-v3",
        "registry": "calc-functions-v3",
        "semantics": "excel-compatible-kpi-v1",
    }


def test_fresh_session_reloads_legacy_v2_run_versions_without_rerun(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )
    graph = context["session"].get(
        CalculationGraphVersionRecord,
        prepared.graph_version_id,
    )
    run = context["session"].get(
        CalculationRunRecord,
        baseline.calculation_run_id,
    )
    graph.compiler_version = "formula-compiler-v2"
    graph.function_registry_version = "calc-functions-v2"
    graph.semantics_profile = "excel-compatible-v2"
    run.engine_version = "calc-engine-v2"
    run.function_registry_version = "calc-functions-v2"
    run.semantics_profile = "excel-compatible-v2"
    context["session"].commit()
    expected_values = baseline.values
    context["session"].close()

    restarted = context["session_factory"]()
    try:
        before = _calculation_artifact_counts(restarted)
        reloaded = CalculationIntegrationService(
            restarted,
            ModelExtractionReadService(
                restarted,
                DatabaseWorkbookStorage(restarted),
            ),
            phase2_service=_CalculationMustNotRun(),
        ).get_run(baseline.calculation_run_id)
        after = _calculation_artifact_counts(restarted)
    finally:
        restarted.close()

    assert reloaded.status == baseline.status
    assert reloaded.values == expected_values
    assert reloaded.versions.model_dump(mode="json") == {
        "phase2_ir": "calc-ir-v2",
        "compiler": "formula-compiler-v2",
        "engine": "calc-engine-v2",
        "registry": "calc-functions-v2",
        "semantics": "excel-compatible-v2",
    }
    assert after == before


def test_fresh_session_reloads_projected_outputs_without_rerun_or_writes(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    baseline = facade.calculate(
        context["model"].id,
        _calculation_request(prepared.graph_version_id),
    )
    override = facade.calculate(
        context["model"].id,
        _calculation_request(
            prepared.graph_version_id,
            {
                "target": {
                    "kind": "parameter",
                    "parameter_id": context["parameter"].id,
                },
                "value": {"value_type": "number", "value": "10"},
            },
        ),
    )
    expected = {
        run_id: facade.get_run_outputs(run_id).model_dump(mode="json")
        for run_id in (
            baseline.calculation_run_id,
            override.calculation_run_id,
        )
    }
    context["session"].close()

    restarted = context["session_factory"]()
    try:
        before = _calculation_artifact_counts(restarted)
        reloaded_facade = CalculationIntegrationService(
            restarted,
            ModelExtractionReadService(
                restarted,
                DatabaseWorkbookStorage(restarted),
            ),
            phase2_service=_CalculationMustNotRun(),
        )
        reloaded = {
            run_id: reloaded_facade.get_run_outputs(run_id).model_dump(
                mode="json"
            )
            for run_id in expected
        }
        after = _calculation_artifact_counts(restarted)
    finally:
        restarted.close()

    assert reloaded == expected
    assert after == before


def test_persisted_running_and_failed_runs_reload_without_values(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )
    prepared = facade.prepare(context["model"].id)
    run_id = str(uuid.uuid4())
    repository = Phase2CalculationRepository(context["session"])
    repository.start_run(
        run_id,
        context["model"].id,
        prepared.graph_version_id,
        Phase2CalculationConfiguration(),
        normalized_override_hash="a" * 64,
        run_policy_hash="b" * 64,
        overrides=(),
        run_policy={"iteration_enabled": False},
    )
    context["session"].commit()
    counts_before = _run_row_counts(context["session"])

    running = facade.get_run(run_id)
    repository.mark_failed(run_id, "CALCULATION_ENGINE_V2_FAILED", "sanitized")
    context["session"].commit()
    failed = facade.get_run(run_id)

    assert running.status == "running"
    assert running.values == []
    assert running.summary.calculated_formula_cells == 0
    assert failed.status == "failed"
    assert failed.values == []
    assert failed.graph_version_id == prepared.graph_version_id
    assert failed.versions.compiler == "formula-compiler-v3"
    assert _run_row_counts(context["session"]) == counts_before


def test_get_run_has_stable_not_found_and_reload_failure_errors(
    integration_context,
) -> None:
    from apps.api.app.calculation_integration_service import (
        CalculationIntegrationError,
        CalculationIntegrationService,
    )

    context = integration_context
    facade = CalculationIntegrationService(
        context["session"], context["read_service"]
    )

    with pytest.raises(CalculationIntegrationError) as not_found:
        facade.get_run(str(uuid.uuid4()))

    assert not_found.value.code == "CALCULATION_RUN_NOT_FOUND"
    assert not_found.value.status_code == 404

    class _BrokenRunRepository:
        def load_run(self, _run_id):
            raise RuntimeError("database details must be sanitized")

    facade._phase2_repository = _BrokenRunRepository()
    with pytest.raises(CalculationIntegrationError) as reload_failed:
        facade.get_run(str(uuid.uuid4()))

    assert reload_failed.value.code == "CALCULATION_RUN_RELOAD_FAILED"
    assert reload_failed.value.status_code == 500
