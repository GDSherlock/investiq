"""Service and persistence tests for deterministic calculation API integration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

import pytest

from apps.api.app.calculation_rules.models import CalculationRuleExtraction
from apps.api.app.calculation_rules.phase2_repository import Phase2CalculationRepository
from apps.api.app.calculation_rules.phase2_service import InternalCalculationEngineService
from apps.api.app.calculation_rules.phase2_types import Phase2CalculationConfiguration
from apps.api.app.calculation_rules.repository import CalculationRuleRepository
from apps.api.app.calculation_rules.types import (
    CalculationRuleExtractionConfiguration,
    FormulaIdFactory,
)
from apps.api.app.database import Base
from apps.api.app.model_extraction_models import ModelVersion
from apps.api.app.model_extraction_read_service import ModelExtractionReadService
from apps.api.app.model_extraction_types import ModelExtractionPersistenceError, new_uuid
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
