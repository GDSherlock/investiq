from __future__ import annotations

from pathlib import Path
import os
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.app.database import Base
from apps.api.app.calculation_rules.compiler import FormulaCompiler
from apps.api.app.calculation_rules.evaluator import SafeCalculationEvaluator, ScalarValue
from apps.api.app.calculation_rules.graph import CalculationGraphBuilder
from apps.api.app.calculation_rules.inventory import WorkbookFormulaInventory
from apps.api.app.calculation_rules.models import (
    CalculationRuleExtraction,
    FormulaCanonicalMapping,
    FormulaExecutionResultRecord,
    WorkbookFormulaCellRecord,
)
from apps.api.app.calculation_rules.repository import CalculationRuleRepository
from apps.api.app.calculation_rules.service import CalculationRuleExtractionService
from apps.api.app.calculation_rules.types import CalculationRuleExtractionConfiguration
from apps.api.app.model_extraction_read_service import ModelExtractionReadService
from apps.api.app.model_extraction_types import (
    ModelWorkbookMismatch,
    WorkbookIntegrityError,
)
from apps.api.app.workbook_storage import DatabaseWorkbookStorage
from tests.calculation_rule_test_support import create_materialized_rule_model
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


@pytest.fixture
def service_context(tmp_path: Path):
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "service.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    storage, workbook, model, parameter, series, series_value = (
        create_materialized_rule_model(session)
    )
    read_service = ModelExtractionReadService(session, storage)
    service = CalculationRuleExtractionService(session, read_service)
    try:
        yield (
            engine,
            session_factory,
            session,
            storage,
            workbook,
            model,
            parameter,
            series,
            series_value,
            service,
        )
    finally:
        session.close()
        engine.dispose()


def test_service_executes_maximum_valid_subgraphs_and_persists_lineage(
    service_context,
) -> None:
    (
        _engine,
        _factory,
        _session,
        _storage,
        workbook,
        model,
        parameter,
        series,
        series_value,
        service,
    ) = service_context

    result = service.extract_and_execute(model.id, workbook.id)

    assert result.status == "completed_with_warning"
    assert result.summary["formula_cells_total"] == 10
    assert result.summary["formula_cells_executable"] == 8
    assert result.summary["formula_cells_executed"] == 5
    assert result.summary["unsupported_formula_cells"] == 1
    assert result.summary["external_reference_cells"] == 1
    assert result.summary["cycles_detected"] == 1
    assert result.metrics["supported_formula_execution_rate"] == 1.0
    assert result.summary["metric_denominators"] == {
        "formula_cells_supported_by_whitelist": 8,
        "parsed_supported_acyclic_unblocked": 5,
        "comparable_executed_with_cache": 0,
        "internal_reference_tokens": 9,
        "eligible_canonical_mapping_occurrences": 19,
    }
    assert result.cells_by_address["Calc!B1"].execution.value == ScalarValue.number(5)
    assert result.cells_by_address["Calc!B2"].execution.value == ScalarValue.number(10)
    assert result.cells_by_address["Calc!B3"].execution.status == "not_executable"
    assert result.cells_by_address["Calc!B4"].execution.status == "blocked_by_dependency"
    assert result.cells_by_address["Calc!B5"].execution.status == "cycle"
    assert result.cells_by_address["Calc!B6"].execution.status == "cycle"
    assert result.cells_by_address["Calc!B7"].execution.status == "not_executable"
    assert result.cells_by_address["Calc!B8"].execution.value == ScalarValue.number(10)
    assert result.cells_by_address["Hidden!C1"].execution.value == ScalarValue.number(4)
    assert result.cells_by_address["Very Hidden!D1"].execution.value == ScalarValue.number(5)

    b2_output = next(
        mapping
        for mapping in result.cells_by_address["Calc!B2"].mappings
        if mapping.mapping_role == "output"
    )
    b8_input = next(
        mapping
        for mapping in result.cells_by_address["Calc!B8"].mappings
        if mapping.mapping_role == "input"
    )
    hidden_input = next(
        mapping
        for mapping in result.cells_by_address["Hidden!C1"].mappings
        if mapping.mapping_role == "input"
    )
    b1_input = next(
        mapping
        for mapping in result.cells_by_address["Calc!B1"].mappings
        if mapping.mapping_role == "input"
    )
    assert b2_output.entity_kind == "financial_series"
    assert b2_output.entity_id == series.id
    assert b2_output.financial_series_value_id == series_value.id
    assert b8_input.entity_id == series.id
    assert b1_input.entity_id == parameter.id
    assert "range_partially_mapped" in b1_input.warnings
    assert hidden_input.mapping_status == "unmapped"
    assert hidden_input.entity_id is None


def test_completed_request_is_idempotent_and_reloads_after_new_session(
    service_context,
) -> None:
    (
        _engine,
        session_factory,
        session,
        _storage,
        workbook,
        model,
        *_rest,
        service,
    ) = service_context
    first = service.extract_and_execute(model.id, workbook.id)
    counts_before = (
        session.scalar(select(func.count()).select_from(CalculationRuleExtraction)),
        session.scalar(select(func.count()).select_from(WorkbookFormulaCellRecord)),
        session.scalar(select(func.count()).select_from(FormulaCanonicalMapping)),
        session.scalar(select(func.count()).select_from(FormulaExecutionResultRecord)),
    )

    second = service.extract_and_execute(model.id, workbook.id)
    counts_after = (
        session.scalar(select(func.count()).select_from(CalculationRuleExtraction)),
        session.scalar(select(func.count()).select_from(WorkbookFormulaCellRecord)),
        session.scalar(select(func.count()).select_from(FormulaCanonicalMapping)),
        session.scalar(select(func.count()).select_from(FormulaExecutionResultRecord)),
    )
    session.close()
    restarted = session_factory()
    try:
        reloaded = CalculationRuleRepository(restarted).load_result(
            first.calculation_rule_extraction_id
        )
    finally:
        restarted.close()

    assert first.calculation_rule_extraction_id == second.calculation_rule_extraction_id
    # A finite range is one syntactic FormulaReference and therefore one
    # model-scoped mapping row; its per-cell coverage is carried in warnings.
    assert counts_before == counts_after == (1, 10, 20, 10)
    assert reloaded.status == first.status
    assert reloaded.summary == first.summary
    assert reloaded.cells_by_address["Calc!B2"].execution.value == ScalarValue.number(10)


def test_model_workbook_mismatch_fails_before_run_creation(service_context) -> None:
    (
        _engine,
        _factory,
        session,
        _storage,
        _workbook,
        model,
        *_rest,
        service,
    ) = service_context

    with pytest.raises(ModelWorkbookMismatch):
        service.extract_and_execute(model.id, str(uuid.uuid4()))

    assert session.scalar(select(func.count()).select_from(CalculationRuleExtraction)) == 0


def test_workbook_integrity_failure_fails_before_run_creation(service_context) -> None:
    (
        _engine,
        _factory,
        session,
        _storage,
        workbook,
        model,
        *_rest,
        service,
    ) = service_context
    workbook.content_bytes = b"tampered"
    session.commit()

    with pytest.raises(WorkbookIntegrityError):
        service.extract_and_execute(model.id, workbook.id)

    assert session.scalar(select(func.count()).select_from(CalculationRuleExtraction)) == 0


class _ExplodingInventory:
    def scan(self, _content_bytes, _workbook_version_id):
        raise RuntimeError("formula text must not be copied into task errors")


def test_task_failure_is_sanitized_and_same_identity_can_retry(service_context) -> None:
    (
        _engine,
        _factory,
        session,
        storage,
        workbook,
        model,
        *_rest,
        _service,
    ) = service_context
    read_service = ModelExtractionReadService(session, storage)
    failing = CalculationRuleExtractionService(
        session,
        read_service,
        inventory=_ExplodingInventory(),
    )

    with pytest.raises(RuntimeError):
        failing.extract_and_execute(model.id, workbook.id)

    failed = session.scalar(select(CalculationRuleExtraction))
    assert failed.status == "failed"
    assert failed.error_code == "CALCULATION_RULE_EXTRACTION_FAILED"
    assert failed.error_message == "Calculation rule extraction failed"

    retried = CalculationRuleExtractionService(
        session,
        read_service,
    ).extract_and_execute(model.id, workbook.id)
    assert retried.calculation_rule_extraction_id == failed.id
    assert retried.status == "completed_with_warning"


@pytest.mark.parametrize(
    ("relative_path", "formula_count", "supported_count"),
    [
        ("Financial_Model_Data.xlsx", 352, 351),
        ("experiments/workbook_agent_poc/fixtures/multilingual.xlsx", 3, 3),
        (
            "tests/fixtures/calculation_rules/01_solar_pv_project_finance.xlsx",
            735,
            651,
        ),
        (
            "tests/fixtures/calculation_rules/06_battery_storage_revenue_stack.xlsx",
            489,
            464,
        ),
    ],
)
def test_repository_workbook_corpus_compiles_graphs_and_executes_without_crash(
    relative_path: str,
    formula_count: int,
    supported_count: int,
) -> None:
    workbook_path = Path(__file__).parents[1] / relative_path
    configuration = CalculationRuleExtractionConfiguration()
    catalog = WorkbookFormulaInventory(configuration).scan(
        workbook_path.read_bytes(),
        str(uuid.uuid4()),
    )
    compilations = tuple(
        FormulaCompiler(configuration).compile(cell, catalog)
        for cell in catalog.formulas
    )
    plan = CalculationGraphBuilder(configuration).build(catalog, compilations)
    results = SafeCalculationEvaluator().execute(
        plan,
        catalog,
        compilations,
        configuration,
    )

    assert len(catalog.formulas) == formula_count
    assert sum(item.support_status == "supported" for item in compilations) == supported_count
    assert len(results) == formula_count
    assert all(item.parse_status != "syntax_error" for item in compilations)
    assert all(
        item.ir_json is not None
        for item in compilations
        if item.support_status == "supported"
    )


@pytest.mark.postgres
def test_postgres_service_matches_sqlite_dto_and_persistence_behavior() -> None:
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
        from alembic import command
        from alembic.config import Config

        config = Config(str(Path(__file__).parents[1] / "apps" / "api" / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")

        session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        session = session_factory()
        try:
            storage, workbook, model, *_canonical = create_materialized_rule_model(session)
            service = CalculationRuleExtractionService(
                session,
                ModelExtractionReadService(session, storage),
            )

            result = service.extract_and_execute(model.id, workbook.id)
            reloaded = CalculationRuleRepository(session).load_result(
                result.calculation_rule_extraction_id
            )

            assert reloaded.status == "completed_with_warning"
            assert reloaded.summary == result.summary
            assert reloaded.cells_by_address["Calc!B2"].execution.value == ScalarValue.number(10)
        finally:
            session.close()
    finally:
        engine.dispose()
