from __future__ import annotations

import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.app.database import Base
from apps.api.app.calculation_rules.evaluator import SafeCalculationEvaluator, ScalarValue
from apps.api.app.calculation_rules.phase2_models import (
    CalculationGraphVersionRecord,
    CalculationRunRecord,
    CalculationRunValueRecord,
)
from apps.api.app.model_extraction_read_service import ModelExtractionReadService
from tests.calculation_rule_test_support import create_materialized_rule_model
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


@pytest.fixture
def service_context(tmp_path: Path):
    from apps.api.app.calculation_rules.phase2_service import (
        InternalCalculationEngineService,
    )

    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "phase2-service.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    storage, workbook, model, parameter, series, series_value = (
        create_materialized_rule_model(session)
    )
    read_service = ModelExtractionReadService(session, storage)
    service = InternalCalculationEngineService(session, read_service)
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
            "service": service,
        }
    finally:
        session.close()
        engine.dispose()


def test_compile_workbook_is_idempotent_and_additive(
    service_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.app.calculation_rules.inventory import (
        WorkbookFormulaInventory,
    )
    from apps.api.app.calculation_rules.phase2_types import (
        Phase2CalculationConfiguration,
    )

    context = service_context
    inventory = WorkbookFormulaInventory(Phase2CalculationConfiguration())
    scan_count = 0
    original_scan = inventory.scan

    def count_scan(*args, **kwargs):
        nonlocal scan_count
        scan_count += 1
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(inventory, "scan", count_scan)
    context["service"]._inventory = inventory

    first = context["service"].compile_workbook(context["workbook"].id)
    second = context["service"].compile_workbook(context["workbook"].id)

    assert scan_count == 1
    assert first.graph_version_id == second.graph_version_id
    assert first.ir_version == "calc-ir-v2"
    assert first.compiler_version == "formula-compiler-v4"
    assert first.function_registry_version == "calc-functions-v4"
    assert first.formula_cells_total == 10
    assert first.formula_cells_supported == 9
    assert first.formula_cells_unsupported == 1
    assert context["session"].scalar(
        select(func.count()).select_from(CalculationGraphVersionRecord)
    ) == 1


def test_phase2_cold_run_executes_countif_and_preserves_maximum_valid_output(
    service_context,
) -> None:
    context = service_context

    result = context["service"].calculate_model(context["model"].id)

    assert result.ir_version == "calc-ir-v2"
    assert result.status == "completed_with_warning"
    assert result.cells_by_address["Calc!B1"].value == ScalarValue.number(5)
    assert result.cells_by_address["Calc!B2"].value == ScalarValue.number(10)
    assert result.cells_by_address["Calc!B3"].value == ScalarValue.number(2)
    assert result.cells_by_address["Calc!B4"].value == ScalarValue.number(3)
    assert result.cells_by_address["Calc!B5"].status == "cycle"
    assert result.cells_by_address["Calc!B6"].status == "cycle"
    assert result.cells_by_address["Calc!B7"].status == "not_executable"
    assert result.cells_by_address["Calc!B8"].value == ScalarValue.number(10)
    assert result.summary["formula_cells_total"] == 10
    assert result.summary["calculated_formula_cells"] == 7
    assert result.summary["reused_formula_cells"] == 0
    assert result.summary["cycle_formula_cells"] == 2
    assert result.summary["unsupported_formula_cells"] == 1


def test_parameter_override_dirties_dependents_and_reuses_independent_cells(
    service_context,
) -> None:
    from apps.api.app.calculation_rules.phase2_types import CalculationOverride

    context = service_context
    baseline = context["service"].calculate_model(context["model"].id)
    changed = context["service"].calculate_model(
        context["model"].id,
        overrides=(CalculationOverride.parameter(context["parameter"].id, 10),),
    )

    assert changed.calculation_run_id != baseline.calculation_run_id
    assert changed.base_run_id == baseline.calculation_run_id
    assert changed.cells_by_address["Calc!B1"].value == ScalarValue.number(13)
    assert changed.cells_by_address["Calc!B2"].value == ScalarValue.number(26)
    assert changed.cells_by_address["Calc!B3"].value == ScalarValue.number(2)
    assert changed.cells_by_address["Calc!B4"].value == ScalarValue.number(3)
    assert changed.cells_by_address["Calc!B8"].value == ScalarValue.number(26)
    assert changed.cells_by_address["Hidden!C1"].status == "reused"
    assert changed.cells_by_address["Very Hidden!D1"].status == "reused"
    assert changed.summary["calculated_formula_cells"] == 5
    assert changed.summary["reused_formula_cells"] == 2


def test_cell_override_uses_same_dirty_contract_and_is_idempotent(
    service_context,
) -> None:
    from apps.api.app.calculation_rules.phase2_types import CalculationOverride

    context = service_context
    context["service"].calculate_model(context["model"].id)
    override = CalculationOverride.cell("Inputs", "A1", 7)

    first = context["service"].calculate_model(
        context["model"].id,
        overrides=(override,),
    )
    counts_before = (
        context["session"].scalar(select(func.count()).select_from(CalculationRunRecord)),
        context["session"].scalar(
            select(func.count()).select_from(CalculationRunValueRecord)
        ),
    )
    second = context["service"].calculate_model(
        context["model"].id,
        overrides=(override,),
    )
    counts_after = (
        context["session"].scalar(select(func.count()).select_from(CalculationRunRecord)),
        context["session"].scalar(
            select(func.count()).select_from(CalculationRunValueRecord)
        ),
    )

    assert first.calculation_run_id == second.calculation_run_id
    assert first.cells_by_address["Calc!B2"].value == ScalarValue.number(20)
    assert counts_before == counts_after == (2, 20)


def test_invalid_overrides_fail_before_run_creation(service_context) -> None:
    from apps.api.app.calculation_rules.phase2_types import CalculationOverride

    context = service_context
    with pytest.raises(ValueError, match="Formula text is not an allowed override"):
        CalculationOverride.parameter(context["parameter"].id, "=1+1")
    with pytest.raises(ValueError, match="Canonical parameter was not found"):
        context["service"].calculate_model(
            context["model"].id,
            overrides=(CalculationOverride.parameter(str(uuid.uuid4()), 10),),
        )

    assert context["session"].scalar(
        select(func.count()).select_from(CalculationRunRecord)
    ) == 0


class _ExplodingEvaluator(SafeCalculationEvaluator):
    def execute(self, *_args, **_kwargs):
        raise RuntimeError("=secret formula text must not be persisted")


def test_unexpected_evaluation_failure_is_sanitized_and_retryable(
    service_context,
) -> None:
    from apps.api.app.calculation_rules.phase2_service import (
        InternalCalculationEngineService,
    )

    context = service_context
    failing = InternalCalculationEngineService(
        context["session"],
        context["read_service"],
        evaluator=_ExplodingEvaluator(),
    )

    with pytest.raises(RuntimeError):
        failing.calculate_model(context["model"].id)

    failed = context["session"].scalar(select(CalculationRunRecord))
    assert failed.status == "failed"
    assert failed.error_code == "CALCULATION_ENGINE_V2_FAILED"
    assert failed.error_message == "Phase 2 calculation failed"

    retried = context["service"].calculate_model(context["model"].id)
    assert retried.calculation_run_id == failed.id
    assert retried.status == "completed_with_warning"


@pytest.mark.postgres
def test_postgres_phase2_run_persists_and_round_trips() -> None:
    from alembic import command
    from alembic.config import Config

    from apps.api.app.calculation_rules.phase2_repository import (
        Phase2CalculationRepository,
    )
    from apps.api.app.calculation_rules.phase2_service import (
        InternalCalculationEngineService,
    )

    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL acceptance tests")
    if "test" not in (make_url(database_url).database or "").lower():
        pytest.fail("TEST_POSTGRES_URL must identify an isolated test database")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            for table_name in (
                "calculation_run_values",
                "calculation_runs",
                "calculation_rule_dependencies",
                "calculation_rule_members",
                "grouped_calculation_rules",
                "calculation_graph_components",
                "calculation_graph_versions",
                "workbook_named_expressions",
                "formula_execution_results",
                "formula_canonical_mappings",
                "formula_references",
                "executable_formula_rules",
                "workbook_formula_cells",
                "calculation_rule_extractions",
                "canonical_outputs",
                "financial_series_values",
                "financial_series",
                "model_parameters",
                "model_versions",
                "workbook_versions",
                "alembic_version",
            ):
                connection.exec_driver_sql(
                    f'DROP TABLE IF EXISTS "{table_name}" CASCADE'
                )

        config = Config(
            str(Path(__file__).parents[1] / "apps" / "api" / "alembic.ini")
        )
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")

        session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        session = session_factory()
        try:
            storage, workbook, model, *_canonical = create_materialized_rule_model(
                session
            )
            service = InternalCalculationEngineService(
                session,
                ModelExtractionReadService(session, storage),
            )

            result = service.calculate_model(model.id)
            session.expire_all()
            reloaded = Phase2CalculationRepository(session).load_completed_run(
                result.calculation_run_id
            )

            assert reloaded is not None
            assert reloaded.status == "completed_with_warning"
            assert reloaded.values_by_address["Calc!B3"].value == ScalarValue.number(2)
            assert session.scalar(
                select(func.count()).select_from(CalculationGraphVersionRecord)
            ) == 1
            assert session.scalar(
                select(func.count()).select_from(CalculationRunRecord)
            ) == 1
            assert session.scalar(
                select(func.count()).select_from(CalculationRunValueRecord)
            ) == 10
        finally:
            session.close()
    finally:
        engine.dispose()
