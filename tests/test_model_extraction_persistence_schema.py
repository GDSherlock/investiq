from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import IntegrityError

from apps.api.app.database import Base
from apps.api.app.model_extraction_models import (
    FinancialSeries,
    FinancialSeriesValue,
    ModelParameter,
    ModelVersion,
    WorkbookVersion,
)
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    new_id,
    sqlite_file_url,
    utcnow,
)


def _workbook(**overrides) -> WorkbookVersion:
    digest = overrides.pop("sha256", "a" * 64)
    values = {
        "id": new_id(),
        "sha256": digest,
        "original_filename": "model.xlsx",
        "storage_type": "database",
        "storage_ref": f"workbooks/sha256/{digest}.xlsx",
        "content_bytes": b"workbook-bytes",
        "file_size": len(b"workbook-bytes"),
        "created_at": utcnow(),
    }
    values.update(overrides)
    return WorkbookVersion(**values)


def _model_version(workbook_id: str, **overrides) -> ModelVersion:
    values = {
        "id": new_id(),
        "workbook_version_id": workbook_id,
        "upload_filename": "model.xlsx",
        "status": "extracting",
        "validation_status": "not_run",
        "submitted": False,
        "created_at": utcnow(),
    }
    values.update(overrides)
    return ModelVersion(**values)


def _parameter(model_version_id: str, **overrides) -> ModelParameter:
    values = {
        "id": new_id(),
        "model_version_id": model_version_id,
        "entity_kind": "parameter",
        "llm_candidate_alias": "candidate-1",
        "source_bucket": "parameter_candidates",
        "label": "Tax rate",
        "submitted_role": "assumption",
        "validated_role": "assumption",
        "raw_value_json": 0.2,
        "validated_value_json": 0.2,
        "source_sheet": "Assumptions",
        "source_cell": "B4",
        "formula_status": "static_value",
        "source_validation_status": "valid",
        "role_validation_status": "confirmed",
        "validation_status": "validated",
        "created_at": utcnow(),
    }
    values.update(overrides)
    return ModelParameter(**values)


def _series(model_version_id: str, **overrides) -> FinancialSeries:
    values = {
        "id": new_id(),
        "model_version_id": model_version_id,
        "entity_kind": "financial_series",
        "llm_series_alias": "revenue-series",
        "label": "Revenue",
        "semantic_role": "financial_series",
        "orientation": "horizontal",
        "calculation_type": "formula",
        "period_source_range": "'P&L'!B2:D2",
        "value_source_range": "'P&L'!B3:D3",
        "materialization_status": "materialized",
        "validation_status": "validated",
        "created_at": utcnow(),
    }
    values.update(overrides)
    return FinancialSeries(**values)


def _series_value(series_id: str, **overrides) -> FinancialSeriesValue:
    values = {
        "id": new_id(),
        "financial_series_id": series_id,
        "period_index": 0,
        "raw_period_label_json": 2026,
        "display_period_label": "2026",
        "period_type": "annual",
        "year": 2026,
        "is_forecast": True,
        "value_json": 125.5,
        "period_source_sheet": "P&L",
        "period_source_cell": "B2",
        "value_source_sheet": "P&L",
        "value_source_cell": "B3",
        "exact_formula": "=B10+B11",
        "formula_status": "formula_cached_value_available",
        "cached_value_available": True,
        "cached_value_freshness": "unknown",
        "number_format": "#,##0.0",
        "data_type": "f",
        "created_at": utcnow(),
    }
    values.update(overrides)
    return FinancialSeriesValue(**values)


@pytest.fixture
def schema_session():
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        yield engine, session
    finally:
        session.close()
        engine.dispose()


def test_metadata_creates_all_model_extraction_tables(schema_session) -> None:
    engine, _session = schema_session

    assert {
        "workbook_versions",
        "model_versions",
        "model_parameters",
        "financial_series",
        "financial_series_values",
    } <= set(inspect(engine).get_table_names())


def test_workbook_sha256_is_unique(schema_session) -> None:
    _engine, session = schema_session
    session.add_all([_workbook(), _workbook(id=new_id(), storage_ref="another-ref")])

    with pytest.raises(IntegrityError):
        session.commit()


def test_database_storage_requires_content_bytes(schema_session) -> None:
    _engine, session = schema_session
    session.add(_workbook(content_bytes=None))

    with pytest.raises(IntegrityError):
        session.commit()


def test_model_version_requires_existing_workbook(schema_session) -> None:
    _engine, session = schema_session
    session.add(_model_version(new_id()))

    with pytest.raises(IntegrityError):
        session.commit()


def test_parameter_entity_kind_is_checked(schema_session) -> None:
    _engine, session = schema_session
    workbook = _workbook()
    model_version = _model_version(workbook.id)
    session.add_all([workbook, model_version])
    session.flush()
    session.add(_parameter(model_version.id, entity_kind="financial_series"))

    with pytest.raises(IntegrityError):
        session.commit()


def test_financial_series_entity_kind_is_checked(schema_session) -> None:
    _engine, session = schema_session
    workbook = _workbook()
    model_version = _model_version(workbook.id)
    session.add_all([workbook, model_version])
    session.flush()
    session.add(_series(model_version.id, entity_kind="parameter"))

    with pytest.raises(IntegrityError):
        session.commit()


def test_period_index_is_unique_within_series(schema_session) -> None:
    _engine, session = schema_session
    workbook = _workbook()
    model_version = _model_version(workbook.id)
    series = _series(model_version.id)
    session.add_all([workbook, model_version, series])
    session.flush()
    session.add_all(
        [
            _series_value(series.id),
            _series_value(
                series.id,
                id=new_id(),
                value_source_cell="C3",
                period_source_cell="C2",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_model_version_cascades_children_but_not_workbook(schema_session) -> None:
    _engine, session = schema_session
    workbook = _workbook()
    model_version = _model_version(workbook.id)
    parameter = _parameter(model_version.id)
    series = _series(model_version.id)
    value = _series_value(series.id)
    session.add_all([workbook, model_version, parameter, series, value])
    session.commit()

    session.execute(delete(ModelVersion).where(ModelVersion.id == model_version.id))
    session.commit()

    assert session.scalar(select(WorkbookVersion.id)) == workbook.id
    assert session.scalar(select(ModelParameter.id)) is None
    assert session.scalar(select(FinancialSeries.id)) is None
    assert session.scalar(select(FinancialSeriesValue.id)) is None


def test_alembic_upgrades_empty_sqlite_database_to_persistence_head(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    database_path = tmp_path / "migration.db"
    config_path = Path(__file__).parents[1] / "apps" / "api" / "alembic.ini"
    config = Config(str(config_path))
    config.set_main_option("sqlalchemy.url", sqlite_file_url(database_path))

    command.upgrade(config, "head")

    engine, _session_factory = create_sqlite_session_factory(sqlite_file_url(database_path))
    try:
        assert {
            "workbook_versions",
            "model_versions",
            "model_parameters",
            "financial_series",
            "financial_series_values",
        } <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
