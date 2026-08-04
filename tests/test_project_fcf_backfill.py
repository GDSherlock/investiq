from __future__ import annotations

from sqlalchemy import func, select

from apps.api.app.database import Base
from apps.api.app.model_extraction_models import (
    FinancialSeries,
    FinancialSeriesValue,
    ModelSemanticBinding,
    ModelVersion,
    WorkbookVersion,
)
from apps.api.app.model_extraction_types import new_uuid
from apps.api.app.project_fcf_backfill import (
    apply_project_fcf_binding,
    preview_project_fcf_binding,
)
from tests.model_extraction_test_support import create_sqlite_session_factory


def _context():
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    workbook_id = new_uuid()
    model_id = new_uuid()
    series_id = new_uuid()
    session.add(
        WorkbookVersion(
            id=workbook_id,
            sha256="f" * 64,
            original_filename="project-fcf.xlsx",
            storage_type="database",
            storage_ref="workbooks/project-fcf.xlsx",
            content_bytes=b"x",
            file_size=1,
        )
    )
    session.add(
        ModelVersion(
            id=model_id,
            workbook_version_id=workbook_id,
            upload_filename="project-fcf.xlsx",
            status="materialized",
            validation_status="validated",
            submitted=True,
        )
    )
    session.add(
        FinancialSeries(
            id=series_id,
            model_version_id=model_id,
            entity_kind="financial_series",
            label="Project free cash flow",
            semantic_role="financial_series",
            business_role="cash_flow",
            unit="USDm",
            frequency="annual",
            orientation="horizontal",
            calculation_type="formula",
            period_source_range="Cash Flow!B1:C1",
            value_source_range="Cash Flow!B2:C2",
            materialization_status="materialized",
            validation_status="validated",
        )
    )
    for index, cell in enumerate(("B", "C")):
        session.add(
            FinancialSeriesValue(
                id=new_uuid(),
                financial_series_id=series_id,
                period_index=index,
                raw_period_label_json=2026 + index,
                display_period_label=str(2026 + index),
                period_type="year",
                year=2026 + index,
                value_json=10 + index,
                period_source_sheet="Cash Flow",
                period_source_cell=f"{cell}1",
                value_source_sheet="Cash Flow",
                value_source_cell=f"{cell}2",
                exact_formula=f"={cell}5+{cell}6",
                formula_status="formula_with_cached_value",
                cached_value_available=True,
            )
        )
    session.commit()
    return engine, session, model_id, series_id


def test_preview_is_read_only_and_apply_inserts_selected_binding() -> None:
    engine, session, model_id, series_id = _context()
    try:
        preview = preview_project_fcf_binding(session, model_id)
        assert preview.action == "insert"
        assert preview.selected_series_id == series_id
        assert session.scalar(select(func.count(ModelSemanticBinding.id))) == 0

        applied = apply_project_fcf_binding(session, model_id)
        session.commit()

        binding = session.scalar(
            select(ModelSemanticBinding).where(
                ModelSemanticBinding.model_version_id == model_id,
                ModelSemanticBinding.semantic_role == "project_free_cash_flow",
            )
        )
        assert applied.action == "insert"
        assert binding is not None
        assert binding.financial_series_id == series_id
        assert binding.binding_source == "extracted"
    finally:
        session.close()
        engine.dispose()


def test_apply_is_idempotent_and_preserves_reviewed_binding() -> None:
    engine, session, model_id, series_id = _context()
    try:
        session.add(
            ModelSemanticBinding(
                id=new_uuid(),
                model_version_id=model_id,
                semantic_role="project_free_cash_flow",
                financial_series_id=series_id,
                binding_source="reviewed",
                evidence_json={"reviewed": True},
            )
        )
        session.commit()

        result = apply_project_fcf_binding(session, model_id)
        session.commit()

        bindings = list(
            session.scalars(
                select(ModelSemanticBinding).where(
                    ModelSemanticBinding.model_version_id == model_id
                )
            )
        )
        assert result.action == "skip_existing"
        assert len(bindings) == 1
        assert bindings[0].binding_source == "reviewed"
        assert bindings[0].evidence_json == {"reviewed": True}
    finally:
        session.close()
        engine.dispose()


def test_preview_skips_model_without_eligible_project_fcf() -> None:
    engine, session, model_id, _series_id = _context()
    try:
        series = session.scalar(
            select(FinancialSeries).where(
                FinancialSeries.model_version_id == model_id
            )
        )
        assert series is not None
        series.label = "Cash flow"
        session.commit()

        result = preview_project_fcf_binding(session, model_id)

        assert result.action == "skip_no_candidate"
        assert result.selected_series_id is None
        assert session.scalar(select(func.count(ModelSemanticBinding.id))) == 0
    finally:
        session.close()
        engine.dispose()
