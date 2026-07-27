from __future__ import annotations

from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError

from apps.api.app.database import Base
from apps.api.app.calculation_rules.compiler import FormulaCompiler
from apps.api.app.calculation_rules.evaluator import ScalarValue
from apps.api.app.calculation_rules.graph import CalculationGraphBuilder
from apps.api.app.calculation_rules.inventory import WorkbookFormulaInventory
from apps.api.app.calculation_rules.phase2_graph import VersionedCalculationGraphBuilder
from apps.api.app.calculation_rules.phase2_grouping import BusinessRuleGrouper
from apps.api.app.calculation_rules.phase2_registry import PHASE2_FUNCTION_REGISTRY
from apps.api.app.calculation_rules.phase2_types import (
    CalculationRunPolicy,
    Phase2CalculationConfiguration,
    canonical_hash,
)
from apps.api.app.calculation_rules.repository import CalculationRuleRepository
from apps.api.app.workbook_storage import WorkbookStorageLocation
from tests.calculation_rule_test_support import create_materialized_rule_model
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


PHASE2_TABLES = {
    "workbook_named_expressions",
    "calculation_graph_versions",
    "calculation_graph_components",
    "grouped_calculation_rules",
    "calculation_rule_members",
    "calculation_rule_dependencies",
    "calculation_runs",
    "calculation_run_values",
}


@pytest.fixture
def persistence_context(tmp_path: Path):
    from apps.api.app.calculation_rules import phase2_models as _phase2_models
    from apps.api.app.calculation_rules.phase2_repository import (
        Phase2CalculationRepository,
    )

    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "phase2.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    storage, workbook, model, *_canonical = create_materialized_rule_model(session)
    configuration = Phase2CalculationConfiguration()
    catalog = WorkbookFormulaInventory(configuration).scan(
        storage.load(
            WorkbookStorageLocation(workbook.storage_type, workbook.storage_ref)
        ),
        workbook.id,
    )
    compilations = tuple(
        FormulaCompiler(
            configuration,
            function_registry=PHASE2_FUNCTION_REGISTRY,
        ).compile(cell, catalog)
        for cell in catalog.formulas
    )
    CalculationRuleRepository(session).save_compilation(
        catalog,
        compilations,
        configuration,
    )
    session.commit()
    base_graph = CalculationGraphBuilder(configuration).build(catalog, compilations)
    graph = VersionedCalculationGraphBuilder(configuration).build(
        catalog,
        compilations,
        base_graph,
    )
    groups = BusinessRuleGrouper(configuration).group(
        model.id,
        catalog,
        compilations,
    )
    repository = Phase2CalculationRepository(session)
    try:
        yield {
            "engine": engine,
            "session_factory": session_factory,
            "session": session,
            "workbook": workbook,
            "model": model,
            "configuration": configuration,
            "catalog": catalog,
            "compilations": compilations,
            "graph": graph,
            "groups": groups,
            "repository": repository,
        }
    finally:
        session.close()
        engine.dispose()


def test_metadata_contains_exact_eight_additive_phase2_tables() -> None:
    from apps.api.app.calculation_rules import phase2_models as _phase2_models

    assert PHASE2_TABLES <= set(Base.metadata.tables)
    assert {
        "calculation_rule_extractions",
        "workbook_formula_cells",
        "executable_formula_rules",
        "formula_references",
        "formula_canonical_mappings",
        "formula_execution_results",
    } <= set(Base.metadata.tables)


def test_run_status_constraint_rejects_unknown_state(persistence_context) -> None:
    from apps.api.app.calculation_rules.phase2_models import CalculationRunRecord

    context = persistence_context
    repository = context["repository"]
    repository.save_graph(context["graph"], context["configuration"])
    context["session"].commit()
    context["session"].add(
        CalculationRunRecord(
            id=str(uuid.uuid4()),
            model_version_id=context["model"].id,
            graph_version_id=context["graph"].id,
            base_run_id=None,
            engine_version="calc-engine-v2",
            function_registry_version="calc-functions-v2",
            semantics_profile="excel-compatible-v2",
            normalized_override_hash="0" * 64,
            run_policy_hash="1" * 64,
            overrides_json=[],
            run_policy_json={"iteration_enabled": False},
            status="invented",
        )
    )

    with pytest.raises(IntegrityError):
        context["session"].commit()
    context["session"].rollback()


def test_repository_is_idempotent_and_run_reloads_after_restart(
    persistence_context,
) -> None:
    from apps.api.app.calculation_rules.phase2_models import (
        CalculationGraphComponentRecord,
        CalculationGraphVersionRecord,
        CalculationRunRecord,
        CalculationRunValueRecord,
        GroupedCalculationRuleRecord,
    )
    from apps.api.app.calculation_rules.phase2_repository import (
        CalculationRunValueData,
        Phase2CalculationRepository,
    )

    context = persistence_context
    session = context["session"]
    repository = context["repository"]
    repository.save_graph(context["graph"], context["configuration"])
    repository.save_groups(context["graph"].id, context["groups"])
    session.commit()
    counts_before = (
        session.scalar(select(func.count()).select_from(CalculationGraphVersionRecord)),
        session.scalar(select(func.count()).select_from(CalculationGraphComponentRecord)),
        session.scalar(select(func.count()).select_from(GroupedCalculationRuleRecord)),
    )
    repository.save_graph(context["graph"], context["configuration"])
    repository.save_groups(context["graph"].id, context["groups"])
    session.commit()
    counts_after = (
        session.scalar(select(func.count()).select_from(CalculationGraphVersionRecord)),
        session.scalar(select(func.count()).select_from(CalculationGraphComponentRecord)),
        session.scalar(select(func.count()).select_from(GroupedCalculationRuleRecord)),
    )
    assert counts_after == counts_before

    run_id = str(uuid.uuid4())
    repository.start_run(
        run_id,
        context["model"].id,
        context["graph"].id,
        context["configuration"],
        normalized_override_hash="2" * 64,
        run_policy_hash="3" * 64,
        overrides=(),
        run_policy={"iteration_enabled": False},
    )
    first_formula = context["catalog"].formulas[0]
    first_compilation = next(
        item
        for item in context["compilations"]
        if item.formula_cell_id == first_formula.id
    )
    value = CalculationRunValueData(
        id=str(uuid.uuid4()),
        calculation_run_id=run_id,
        formula_cell_id=first_formula.id,
        expression_id=first_compilation.expression_id,
        execution_status="executed",
        value=ScalarValue.number(10),
        engine_error_code=None,
        reused_from_run_id=None,
        direct_input_trace=(),
        validation_status="not_comparable",
        warnings=(),
    )
    repository.replace_run_values(run_id, (value,))
    repository.complete_run(
        run_id,
        status="completed",
        summary={"calculated": 1, "reused": 0},
        warnings=(),
    )
    session.commit()
    assert session.scalar(select(func.count()).select_from(CalculationRunRecord)) == 1
    assert session.scalar(select(func.count()).select_from(CalculationRunValueRecord)) == 1

    session.close()
    restarted = context["session_factory"]()
    try:
        loaded = Phase2CalculationRepository(restarted).load_run(run_id)
    finally:
        restarted.close()

    assert loaded.calculation_run_id == run_id
    assert loaded.status == "completed"
    assert loaded.summary == {"calculated": 1, "reused": 0}
    assert loaded.values[0].value == ScalarValue.number(10)
    assert loaded.values[0].cell_address == first_formula.ref.cell_address


def test_repository_finds_completed_zero_override_run_with_exact_versions_and_policy(
    persistence_context,
) -> None:
    context = persistence_context
    repository = context["repository"]
    configuration = context["configuration"]
    run_policy = CalculationRunPolicy().to_payload()
    run_id = str(uuid.uuid4())
    repository.save_graph(context["graph"], configuration)
    repository.start_run(
        run_id,
        context["model"].id,
        context["graph"].id,
        configuration,
        normalized_override_hash=canonical_hash([]),
        run_policy_hash=canonical_hash(run_policy),
        overrides=(),
        run_policy=run_policy,
    )
    repository.complete_run(
        run_id,
        status="completed",
        summary={},
        warnings=(),
    )
    context["session"].commit()

    found = repository.find_completed_zero_override_run(
        context["model"].id,
        context["graph"].id,
        engine_version=configuration.engine_version,
        function_registry_version=configuration.function_registry_version,
        semantics_profile=configuration.semantics_profile,
        run_policy_hash=canonical_hash(run_policy),
    )

    assert found is not None
    assert found.calculation_run_id == run_id


def test_repository_rejects_nonempty_override_from_zero_baseline_lookup(
    persistence_context,
) -> None:
    from apps.api.app.calculation_rules.phase2_models import CalculationRunRecord

    context = persistence_context
    repository = context["repository"]
    configuration = context["configuration"]
    run_policy = CalculationRunPolicy().to_payload()
    override_payload = [
        {
            "target_kind": "parameter",
            "target_id": str(uuid.uuid4()),
            "sheet_name": None,
            "cell_address": None,
            "value_type": "number",
            "value": 10.0,
        }
    ]
    run_id = str(uuid.uuid4())
    repository.save_graph(context["graph"], configuration)
    repository.start_run(
        run_id,
        context["model"].id,
        context["graph"].id,
        configuration,
        normalized_override_hash=canonical_hash(override_payload),
        run_policy_hash=canonical_hash(run_policy),
        overrides=override_payload,
        run_policy=run_policy,
    )
    repository.complete_run(
        run_id,
        status="completed",
        summary={},
        warnings=(),
    )
    context["session"].commit()
    corrupt_row = context["session"].get(CalculationRunRecord, run_id)
    corrupt_row.normalized_override_hash = canonical_hash([])
    context["session"].commit()

    found = repository.find_completed_zero_override_run(
        context["model"].id,
        context["graph"].id,
        engine_version=configuration.engine_version,
        function_registry_version=configuration.function_registry_version,
        semantics_profile=configuration.semantics_profile,
        run_policy_hash=canonical_hash(run_policy),
    )

    assert found is None


def test_alembic_upgrades_downgrades_and_reupgrades_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "phase2-migration.db"
    config = Config(str(Path(__file__).parents[1] / "apps" / "api" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")
    script = ScriptDirectory.from_config(config)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        assert script.get_current_head() == "20260727_0006"
        assert PHASE2_TABLES <= set(inspect(engine).get_table_names())
        assert "canonical_outputs" in inspect(engine).get_table_names()
        assert (
            "calculation_sensitivity_analyses"
            in inspect(engine).get_table_names()
        )

        command.downgrade(config, "20260715_0003")
        downgraded = set(inspect(engine).get_table_names())
        assert not (PHASE2_TABLES & downgraded)
        assert "calculation_sensitivity_analyses" not in downgraded
        assert "calculation_rule_extractions" in downgraded

        command.upgrade(config, "head")
        assert PHASE2_TABLES <= set(inspect(engine).get_table_names())
        assert "canonical_outputs" in inspect(engine).get_table_names()
        assert (
            "calculation_sensitivity_analyses"
            in inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()
