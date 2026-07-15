from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from apps.api.app.database import Base
from apps.api.app.model_extraction_repository import (
    ModelExtractionRepository,
    WorkbookVersionRepository,
)
from apps.api.app.model_extraction_read_service import ModelExtractionReadService
from apps.api.app.model_extraction_types import (
    AmbiguousSourceCellError,
    CanonicalFinancialSeries,
    CanonicalParameter,
    FinancialSeriesNotFound,
    InvalidCellAddress,
    ModelVersionNotReady,
    ModelWorkbookMismatch,
    ParameterResolution,
    FinancialSeriesValueResolution,
    FinancialEntityIdFactory,
    new_uuid,
)
from apps.api.app.workbook_storage import DatabaseWorkbookStorage
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sample_workbook_bytes,
    sqlite_file_url,
)


def _canonical_rows(
    model_version_id: str,
    *,
    parameter_sheet: str = "Assumptions",
    parameter_cell: str = "B4",
    value_cell: str = "B3",
):
    id_factory = FinancialEntityIdFactory(model_version_id)
    parameter_id = id_factory.parameter_id(parameter_sheet, parameter_cell)
    series_id = id_factory.series_id(
        "'P&L'!B2:C2",
        "'P&L'!B3:C3",
        "base",
        "Project Alpha",
        "USDm",
        "USD",
    )
    parameter = {
        "id": parameter_id,
        "model_version_id": model_version_id,
        "entity_kind": "parameter",
        "llm_candidate_alias": "candidate-1",
        "source_bucket": "parameter_candidates",
        "label": "Tax rate",
        "submitted_role": "assumption",
        "validated_role": "assumption",
        "raw_value_json": 0.2,
        "validated_value_json": 0.2,
        "source_sheet": parameter_sheet,
        "source_cell": parameter_cell,
        "formula_status": "static_value",
        "source_validation_status": "valid",
        "role_validation_status": "confirmed",
        "validation_status": "validated",
        "number_format": "0.0%",
    }
    series = {
        "id": series_id,
        "model_version_id": model_version_id,
        "entity_kind": "financial_series",
        "llm_series_alias": "series-1",
        "label": "Revenue",
        "category": "income_statement",
        "semantic_role": "financial_series",
        "unit": "USDm",
        "frequency": "annual",
        "orientation": "horizontal",
        "scenario": "base",
        "entity": "Project Alpha",
        "currency": "USD",
        "calculation_type": "mixed",
        "period_source_range": "'P&L'!B2:C2",
        "value_source_range": "'P&L'!B3:C3",
        "materialization_status": "materialized",
        "validation_status": "validated",
        "aliases_json": ["Sales"],
        "formula_pattern_json": {"formula_count": 1},
        "warnings_json": [],
    }
    values = [
        {
            "id": id_factory.value_id(series_id, 1),
            "financial_series_id": series_id,
            "period_index": 1,
            "raw_period_label_json": 2027,
            "display_period_label": "2027",
            "period_type": "annual",
            "year": 2027,
            "is_forecast": True,
            "value_json": 150.0,
            "period_source_sheet": "P&L",
            "period_source_cell": "C2",
            "value_source_sheet": "P&L",
            "value_source_cell": "C3",
            "exact_formula": None,
            "formula_status": "static_value",
            "cached_value_available": True,
            "cached_value_freshness": None,
            "number_format": "#,##0.0",
            "data_type": "n",
        },
        {
            "id": id_factory.value_id(series_id, 0),
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
            "value_source_cell": value_cell,
            "exact_formula": "=B10+B11",
            "formula_status": "formula_cached_value_available",
            "cached_value_available": True,
            "cached_value_freshness": "unknown",
            "number_format": "#,##0.0",
            "data_type": "f",
        },
    ]
    return parameter, series, values


def _create_model(
    session,
    *,
    materialize: bool = True,
    parameter_sheet: str = "Assumptions",
    parameter_cell: str = "B4",
    value_cell: str = "B3",
    snapshot: dict | None = None,
    empty_canonical: bool = False,
):
    storage = DatabaseWorkbookStorage(session)
    workbook_repository = WorkbookVersionRepository(session, storage)
    repository = ModelExtractionRepository(session)
    workbook_version = workbook_repository.get_or_create(
        sample_workbook_bytes(),
        "model.xlsx",
    )
    model_version = repository.create_model_version(workbook_version.id, "model.xlsx")
    session.commit()
    repository.save_extraction_snapshot(
        model_version.id,
        snapshot
        or {
            "final_extraction": {
                "parameter_candidates": [{"source_reference": "Assumptions!B4"}],
                "financial_series": [{"value_source_range": "'P&L'!B3:C3"}],
            }
        },
        submitted=True,
        stop_reason="submitted",
        validation_status="validated",
        driver_meta={"api_mode": "responses"},
        coverage={"score": 1.0},
        validation_summary={"validated": 1},
        validation_results={"parameters": [{"validation_status": "validated"}]},
    )
    session.commit()
    if materialize:
        parameter, series, values = _canonical_rows(
            model_version.id,
            parameter_sheet=parameter_sheet,
            parameter_cell=parameter_cell,
            value_cell=value_cell,
        )
        with session.begin():
            repository.persist_canonical_model(
                model_version.id,
                parameters=[] if empty_canonical else [parameter],
                financial_series=[] if empty_canonical else [series],
                financial_series_values=[] if empty_canonical else values,
                validation_status="validated",
            )
    return storage, workbook_version, model_version


@pytest.fixture
def reload_context(tmp_path: Path):
    database_path = tmp_path / "reload.db"
    engine, session_factory = create_sqlite_session_factory(sqlite_file_url(database_path))
    Base.metadata.create_all(engine)
    session = session_factory()
    storage, workbook_version, model_version = _create_model(session)
    try:
        yield engine, session_factory, session, storage, workbook_version, model_version
    finally:
        session.close()
        engine.dispose()


def test_reload_workbook_after_new_session_returns_verified_bytes(reload_context) -> None:
    _engine, session_factory, session, _storage, workbook_version, _model_version = reload_context
    expected = sample_workbook_bytes()
    session.close()
    restarted_session = session_factory()
    try:
        service = ModelExtractionReadService(
            restarted_session,
            DatabaseWorkbookStorage(restarted_session),
        )

        loaded = service.load_workbook_version(workbook_version.id)

        assert loaded.id == workbook_version.id
        assert loaded.content_bytes == expected
        assert loaded.sha256
        assert not hasattr(loaded, "storage_ref")
    finally:
        restarted_session.close()


def test_nonmaterialized_model_is_not_canonically_reloadable(tmp_path: Path) -> None:
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "not-ready.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        storage, _workbook_version, model_version = _create_model(
            session,
            materialize=False,
        )
        service = ModelExtractionReadService(session, storage)

        with pytest.raises(ModelVersionNotReady) as exc_info:
            service.list_parameters(model_version.id)

        assert exc_info.value.status == "extracted"
    finally:
        session.close()
        engine.dispose()


def test_list_financial_entities_returns_discriminated_parameter_and_series(
    reload_context,
) -> None:
    _engine, _factory, session, storage, _workbook, model_version = reload_context
    service = ModelExtractionReadService(session, storage)

    entities = service.list_financial_entities(model_version.id)

    assert len(entities) == 2
    assert any(isinstance(entity, CanonicalParameter) for entity in entities)
    assert any(isinstance(entity, CanonicalFinancialSeries) for entity in entities)
    assert {entity.entity_kind for entity in entities} == {"parameter", "financial_series"}
    assert all(entity.entity_ref.id == entity.id for entity in entities)


def test_series_values_are_ordered_by_series_and_period_index(reload_context) -> None:
    _engine, _factory, session, storage, _workbook, model_version = reload_context
    service = ModelExtractionReadService(session, storage)

    values = service.list_financial_series_values(model_version.id)

    assert [value.period_index for value in values] == [0, 1]
    assert values[0].value_json == 125.5
    assert values[0].exact_formula == "=B10+B11"
    assert values[0].value_source_cell == "B3"


def test_source_cell_resolves_parameter(reload_context) -> None:
    _engine, _factory, session, storage, _workbook, model_version = reload_context
    service = ModelExtractionReadService(session, storage)

    resolution = service.resolve_entity_by_source_cell(
        model_version.id,
        "Assumptions",
        "b4",
    )

    assert isinstance(resolution, ParameterResolution)
    assert resolution.entity.entity_kind == "parameter"
    assert resolution.parameter.source_cell == "B4"


def test_source_cell_resolves_series_value_with_parent_entity_ref(reload_context) -> None:
    _engine, _factory, session, storage, _workbook, model_version = reload_context
    service = ModelExtractionReadService(session, storage)

    resolution = service.resolve_entity_by_source_cell(model_version.id, "P&L", "B3")

    assert isinstance(resolution, FinancialSeriesValueResolution)
    assert resolution.entity.entity_kind == "financial_series"
    assert resolution.entity.id == resolution.series.id
    assert resolution.value.period_index == 0


def test_unmapped_source_cell_returns_none(reload_context) -> None:
    _engine, _factory, session, storage, _workbook, model_version = reload_context
    service = ModelExtractionReadService(session, storage)

    assert service.resolve_entity_by_source_cell(model_version.id, "P&L", "Z99") is None


def test_invalid_a1_address_is_rejected(reload_context) -> None:
    _engine, _factory, session, storage, _workbook, model_version = reload_context
    service = ModelExtractionReadService(session, storage)

    with pytest.raises(InvalidCellAddress):
        service.resolve_entity_by_source_cell(model_version.id, "P&L", "B0")


def test_cross_type_source_collision_raises_ambiguity(tmp_path: Path) -> None:
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "ambiguous.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        storage, _workbook, model_version = _create_model(
            session,
            parameter_sheet="P&L",
            parameter_cell="B4",
            value_cell="B4",
        )
        service = ModelExtractionReadService(session, storage)

        with pytest.raises(AmbiguousSourceCellError):
            service.resolve_entity_by_source_cell(model_version.id, "P&L", "B4")
    finally:
        session.close()
        engine.dispose()


def test_read_dtos_expose_no_snapshot_telemetry_or_validation_json(reload_context) -> None:
    _engine, _factory, session, storage, workbook_version, model_version = reload_context
    service = ModelExtractionReadService(session, storage)

    model_data = service.load_model_version(model_version.id)
    workbook_data = service.load_workbook_version(workbook_version.id)
    public_fields = {field.name for field in fields(model_data)} | {
        field.name for field in fields(workbook_data)
    }

    assert "extraction_snapshot_json" not in public_fields
    assert "validation_results_json" not in public_fields
    assert "driver_meta_json" not in public_fields
    assert "coverage_json" not in public_fields
    assert "storage_ref" not in public_fields


def test_missing_canonical_row_never_falls_back_to_snapshot(tmp_path: Path) -> None:
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "no-fallback.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        storage, _workbook, model_version = _create_model(
            session,
            materialize=True,
            empty_canonical=True,
            snapshot={
                "final_extraction": {
                    "parameter_candidates": [
                        {
                            "label": "Snapshot-only parameter",
                            "source_reference": "Inputs!A1",
                        }
                    ]
                }
            },
        )
        service = ModelExtractionReadService(session, storage)

        assert service.list_parameters(model_version.id) == []
        assert service.resolve_entity_by_source_cell(model_version.id, "Inputs", "A1") is None
    finally:
        session.close()
        engine.dispose()


def test_unknown_series_filter_raises_not_found(reload_context) -> None:
    _engine, _factory, session, storage, _workbook, model_version = reload_context
    service = ModelExtractionReadService(session, storage)

    with pytest.raises(FinancialSeriesNotFound):
        service.list_financial_series_values(model_version.id, new_uuid())


def test_model_workbook_mismatch_is_explicit(reload_context) -> None:
    _engine, _factory, session, storage, _workbook, model_version = reload_context
    service = ModelExtractionReadService(session, storage)

    with pytest.raises(ModelWorkbookMismatch):
        service.load_model_version(
            model_version.id,
            expected_workbook_version_id=new_uuid(),
        )
