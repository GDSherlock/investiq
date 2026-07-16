"""Service and persistence tests for deterministic calculation API integration."""

from __future__ import annotations

from datetime import datetime, timezone
import json
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


@pytest.fixture
def integration_context(tmp_path: Path):
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "calculation-integration.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    storage, workbook, model, parameter, series, series_value = (
        create_materialized_rule_model(session)
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
    assert graph.compiler_version == "formula-compiler-v2"
    assert graph.function_registry_version == "calc-functions-v2"
    assert graph.semantics_profile == "excel-compatible-v2"


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
    assert readiness.versions.compiler == "formula-compiler-v2"
    assert readiness.versions.engine == "calc-engine-v2"
    assert readiness.versions.registry == "calc-functions-v2"
    assert readiness.versions.semantics == "excel-compatible-v2"
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


def test_phase1_preparation_failure_preserves_canonical_state_and_retry_converges(
    integration_context,
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

    with pytest.raises(CalculationIntegrationError) as captured:
        CalculationIntegrationService(
            context["session"],
            context["read_service"],
            phase1_service=failing_phase1,
        ).prepare(context["model"].id)

    failed = context["session"].scalar(select(CalculationRuleExtraction))
    assert captured.value.code == "CALCULATION_PREPARATION_FAILED"
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
    assert _canonical_fingerprint(
        context["session"], context["model"].id
    ) == canonical_before


def test_phase2_preparation_failure_preserves_phase1_and_retry_converges(
    integration_context,
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

    with pytest.raises(CalculationIntegrationError) as captured:
        CalculationIntegrationService(
            context["session"],
            context["read_service"],
            phase2_service=failing_phase2,
        ).prepare(context["model"].id)

    phase1 = context["session"].scalar(select(CalculationRuleExtraction))
    assert captured.value.code == "CALCULATION_PREPARATION_FAILED"
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
