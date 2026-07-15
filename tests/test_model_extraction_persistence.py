from __future__ import annotations

from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from apps.api.app.database import Base
from apps.api.app.model_extraction_models import (
    FinancialSeries,
    FinancialSeriesValue,
    ModelParameter,
    ModelVersion,
)
from apps.api.app.model_extraction_repository import (
    ModelExtractionRepository,
    WorkbookVersionRepository,
)
from apps.api.app.model_extraction_types import (
    CanonicalPersistenceStateError,
    FinancialEntityIdFactory,
    FinancialEntityRef,
    new_uuid,
)
from apps.api.app.workbook_storage import DatabaseWorkbookStorage
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sample_workbook_bytes,
)


@pytest.fixture
def persistence_context():
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    storage = DatabaseWorkbookStorage(session)
    workbook_repository = WorkbookVersionRepository(session, storage)
    repository = ModelExtractionRepository(session)
    workbook_version = workbook_repository.get_or_create(
        sample_workbook_bytes(),
        "model.xlsx",
    )
    model_version = repository.create_model_version(
        workbook_version.id,
        "model.xlsx",
    )
    session.commit()
    repository.save_extraction_snapshot(
        model_version.id,
        {"final_extraction": {"parameter_candidates": [], "financial_series": []}},
        submitted=True,
        stop_reason="submitted",
        validation_status="validated",
        validation_results={"parameters": [], "financial_series": []},
    )
    session.commit()
    try:
        yield session, repository, model_version
    finally:
        session.close()
        engine.dispose()


def _canonical_rows(model_version_id: str):
    id_factory = FinancialEntityIdFactory(model_version_id)
    parameter_id = id_factory.parameter_id("Assumptions", "B4")
    series_id = id_factory.series_id(
        period_source_range="'P&L'!B2:D2",
        value_source_range="'P&L'!B3:D3",
        scenario="base",
        entity="Project Alpha",
        unit="USDm",
        currency="USD",
    )
    parameter = {
        "id": parameter_id,
        "model_version_id": model_version_id,
        "entity_kind": "parameter",
        "llm_candidate_alias": "llm-parameter-7",
        "source_bucket": "parameter_candidates",
        "label": "Tax rate",
        "category": "tax",
        "canonical_name": "tax_rate",
        "submitted_role": "assumption",
        "validated_role": "assumption",
        "raw_value_json": 0.2,
        "validated_value_json": 0.2,
        "unit": "%",
        "scenario": "base",
        "period_json": 2026,
        "source_sheet": "Assumptions",
        "source_cell": "B4",
        "exact_formula": None,
        "formula_status": "static_value",
        "source_validation_status": "valid",
        "role_validation_status": "confirmed",
        "validation_status": "validated",
        "data_type": "n",
        "number_format": "0.0%",
        "llm_confidence": 0.82,
        "validation_confidence": 1.0,
        "reasoning_summary": "Explicit tax assumption",
        "validation_warnings_json": [],
    }
    series = {
        "id": series_id,
        "model_version_id": model_version_id,
        "entity_kind": "financial_series",
        "llm_series_alias": "llm-series-3",
        "label": "Revenue",
        "category": "income_statement",
        "semantic_role": "financial_series",
        "unit": "USDm",
        "frequency": "annual",
        "orientation": "horizontal",
        "scenario": "base",
        "entity": "Project Alpha",
        "currency": "USD",
        "calculation_type": "formula",
        "period_source_range": "'P&L'!B2:D2",
        "value_source_range": "'P&L'!B3:D3",
        "label_source_sheet": "P&L",
        "label_source_cell": "A3",
        "materialization_status": "materialized",
        "validation_status": "validated",
        "aliases_json": ["Sales"],
        "formula_pattern_json": {"formula_count": 1, "consistent": True},
        "warnings_json": [],
        "reasoning_summary": "Revenue row",
        "llm_confidence": 0.9,
    }
    value = {
        "id": id_factory.value_id(series_id, 0),
        "financial_series_id": series_id,
        "period_index": 0,
        "raw_period_label_json": 2026,
        "display_period_label": "2026",
        "period_type": "annual",
        "year": 2026,
        "quarter": None,
        "month": None,
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
    }
    return parameter, series, value


def test_parameter_and_series_ids_share_financial_entity_factory() -> None:
    model_version_id = new_uuid()
    factory = FinancialEntityIdFactory(model_version_id)

    parameter_id = factory.parameter_id("Assumptions", "B4")
    series_id = factory.series_id("P&L!B2:D2", "P&L!B3:D3", None, None, None, None)

    assert UUID(parameter_id).version == 5
    assert UUID(series_id).version == 5
    assert parameter_id != series_id
    assert FinancialEntityRef(
        id=parameter_id,
        model_version_id=model_version_id,
        entity_kind="parameter",
        label="Tax rate",
    ).entity_kind == "parameter"
    assert FinancialEntityRef(
        id=series_id,
        model_version_id=model_version_id,
        entity_kind="financial_series",
        label="Revenue",
    ).entity_kind == "financial_series"


def test_llm_alias_changes_do_not_change_backend_ids() -> None:
    model_version_id = new_uuid()
    factory = FinancialEntityIdFactory(model_version_id)
    first_parameter = {"llm_alias": "candidate-a", "sheet": "Inputs", "cell": "b4"}
    second_parameter = {"llm_alias": "candidate-b", "sheet": "Inputs", "cell": "B4"}
    first_series = {"llm_alias": "series-a", "period": "P&L!B2:D2", "value": "P&L!B3:D3"}
    second_series = {"llm_alias": "series-b", "period": "P&L!B2:D2", "value": "P&L!B3:D3"}

    assert factory.parameter_id(
        first_parameter["sheet"], first_parameter["cell"]
    ) == factory.parameter_id(second_parameter["sheet"], second_parameter["cell"])
    assert factory.series_id(
        first_series["period"], first_series["value"], "base", None, "USDm", "USD"
    ) == factory.series_id(
        second_series["period"], second_series["value"], "base", None, "USDm", "USD"
    )


def test_repository_persists_parameter_series_and_aligned_values(persistence_context) -> None:
    session, repository, model_version = persistence_context
    parameter, series, value = _canonical_rows(model_version.id)

    with session.begin():
        repository.persist_canonical_model(
            model_version.id,
            parameters=[parameter],
            financial_series=[series],
            financial_series_values=[value],
            validation_status="validated",
        )

    persisted_model = session.get(ModelVersion, model_version.id)
    assert persisted_model.status == "materialized"
    assert session.scalar(select(ModelParameter.id)) == parameter["id"]
    assert session.scalar(select(FinancialSeries.id)) == series["id"]
    persisted_value = session.scalar(select(FinancialSeriesValue))
    assert persisted_value.id == value["id"]
    assert persisted_value.period_index == 0
    assert persisted_value.exact_formula == "=B10+B11"


def test_parameter_source_cell_conflict_rolls_back_all_canonical_rows(
    persistence_context,
) -> None:
    session, repository, model_version = persistence_context
    parameter, series, value = _canonical_rows(model_version.id)
    duplicate = deepcopy(parameter)
    duplicate["id"] = new_uuid()
    duplicate["llm_candidate_alias"] = "conflicting-candidate"

    with pytest.raises(IntegrityError):
        with session.begin():
            repository.persist_canonical_model(
                model_version.id,
                parameters=[parameter, duplicate],
                financial_series=[series],
                financial_series_values=[value],
                validation_status="validated",
            )

    assert session.scalar(select(func.count()).select_from(ModelParameter)) == 0
    assert session.scalar(select(func.count()).select_from(FinancialSeries)) == 0
    assert session.scalar(select(func.count()).select_from(FinancialSeriesValue)) == 0
    assert session.get(ModelVersion, model_version.id).status == "extracted"


def test_value_period_index_conflict_rolls_back_all_canonical_rows(
    persistence_context,
) -> None:
    session, repository, model_version = persistence_context
    parameter, series, value = _canonical_rows(model_version.id)
    duplicate = deepcopy(value)
    duplicate["id"] = new_uuid()
    duplicate["period_source_cell"] = "C2"
    duplicate["value_source_cell"] = "C3"

    with pytest.raises(IntegrityError):
        with session.begin():
            repository.persist_canonical_model(
                model_version.id,
                parameters=[parameter],
                financial_series=[series],
                financial_series_values=[value, duplicate],
                validation_status="validated",
            )

    assert session.scalar(select(func.count()).select_from(ModelParameter)) == 0
    assert session.scalar(select(func.count()).select_from(FinancialSeries)) == 0
    assert session.scalar(select(func.count()).select_from(FinancialSeriesValue)) == 0
    assert session.get(ModelVersion, model_version.id).status == "extracted"


def test_private_snapshot_loader_is_not_a_public_read_dto(persistence_context) -> None:
    _session, repository, model_version = persistence_context

    snapshot = repository._load_snapshot_for_retry(model_version.id)

    assert snapshot == {
        "final_extraction": {"parameter_candidates": [], "financial_series": []}
    }
    assert not hasattr(repository, "load_snapshot_for_retry")


def test_materialized_model_cannot_be_rewritten(persistence_context) -> None:
    session, repository, model_version = persistence_context
    parameter, series, value = _canonical_rows(model_version.id)
    with session.begin():
        repository.persist_canonical_model(
            model_version.id,
            parameters=[parameter],
            financial_series=[series],
            financial_series_values=[value],
            validation_status="validated",
        )

    with pytest.raises(CanonicalPersistenceStateError, match="materialized"):
        with session.begin():
            repository.persist_canonical_model(
                model_version.id,
                parameters=[parameter],
                financial_series=[series],
                financial_series_values=[value],
                validation_status="validated",
            )
