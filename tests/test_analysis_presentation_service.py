from __future__ import annotations

from datetime import datetime, timezone

from apps.api.app.analysis_presentation_service import AnalysisPresentationService
from apps.api.app.database import Base
from apps.api.app.model_extraction_models import (
    FinancialSeries,
    ModelSemanticBinding,
    ModelVersion,
    WorkbookVersion,
)
from apps.api.app.model_extraction_types import new_uuid
from apps.api.app.schemas import CalculationRunOutputsResponse
from tests.model_extraction_test_support import create_sqlite_session_factory


class _ProjectionService:
    def __init__(self, projection: CalculationRunOutputsResponse) -> None:
        self._projection = projection

    def get_run_outputs(self, _run_id: str) -> CalculationRunOutputsResponse:
        return self._projection


def _projected_number(value: str | None) -> dict[str, object]:
    if value is None:
        return {
            "availability_status": "unavailable",
            "value": None,
            "unavailable_reason": "blocked_by_dependency",
            "validation_status": "not_comparable",
        }
    return {
        "availability_status": "available",
        "value": {"value_type": "number", "value": value},
        "validation_status": "matched",
    }


def test_cumulative_cash_flow_propagates_a_missing_annual_value() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        workbook_id = new_uuid()
        model_id = new_uuid()
        series_id = new_uuid()
        run_id = new_uuid()
        graph_id = new_uuid()
        session.add(
            WorkbookVersion(
                id=workbook_id,
                sha256="b" * 64,
                original_filename="cash-flow.xlsx",
                storage_type="database",
                storage_ref="workbooks/cash-flow.xlsx",
                content_bytes=b"x",
                file_size=1,
            )
        )
        session.add(
            ModelVersion(
                id=model_id,
                workbook_version_id=workbook_id,
                upload_filename="cash-flow.xlsx",
                status="materialized",
                validation_status="validated",
                submitted=True,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            FinancialSeries(
                id=series_id,
                model_version_id=model_id,
                entity_kind="financial_series",
                label="Project FCF",
                semantic_role="financial_series",
                business_role="project_free_cash_flow",
                unit="USDm",
                frequency="annual",
                orientation="horizontal",
                calculation_type="formula",
                period_source_range="Cash Flow!B1:D1",
                value_source_range="Cash Flow!B2:D2",
                materialization_status="materialized",
                validation_status="validated",
            )
        )
        session.flush()
        session.add(
            ModelSemanticBinding(
                id=new_uuid(),
                model_version_id=model_id,
                semantic_role="project_free_cash_flow",
                financial_series_id=series_id,
                binding_source="reviewed",
            )
        )
        session.commit()
        points = [
            {
                "financial_series_value_id": new_uuid(),
                "period_index": index,
                "period": str(2026 + index),
                "mapping_status": "mapped",
                "support_status": "supported",
                "availability_status": (
                    "available" if value is not None else "unavailable"
                ),
                "baseline": _projected_number(value),
                "current": _projected_number(value),
            }
            for index, value in enumerate(("10", None, "5"))
        ]
        projection = CalculationRunOutputsResponse.model_validate(
            {
                "calculation_run_id": run_id,
                "model_version_id": model_id,
                "graph_version_id": graph_id,
                "comparison_baseline_run_id": run_id,
                "outputs": [
                    {
                        "output_id": series_id,
                        "entity_kind": "series",
                        "business_role": "project_free_cash_flow",
                        "label": "Project FCF",
                        "unit": "USDm",
                        "mapping_status": "partial",
                        "support_status": "supported",
                        "availability_status": "partial",
                        "points": points,
                    }
                ],
            }
        )
        service = AnalysisPresentationService(
            session,
            _ProjectionService(projection),  # type: ignore[arg-type]
        )

        response = service.cash_flow(run_id)

        cumulative = next(
            chart
            for chart in response.charts
            if chart.slot == "cumulative_cash_flow"
        )
        assert cumulative.availability_status == "partial"
        assert [point.value for point in cumulative.series[0].points] == [
            "10",
            None,
            None,
        ]
    finally:
        session.close()
        engine.dispose()


def test_overview_operating_trajectory_uses_explicit_revenue_cfads_fallback() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        workbook_id = new_uuid()
        model_id = new_uuid()
        run_id = new_uuid()
        graph_id = new_uuid()
        session.add(
            WorkbookVersion(
                id=workbook_id,
                sha256="c" * 64,
                original_filename="overview.xlsx",
                storage_type="database",
                storage_ref="workbooks/overview.xlsx",
                content_bytes=b"x",
                file_size=1,
            )
        )
        session.add(
            ModelVersion(
                id=model_id,
                workbook_version_id=workbook_id,
                upload_filename="overview.xlsx",
                status="materialized",
                validation_status="validated",
                submitted=True,
            )
        )
        output_rows = []
        projection_rows = []
        for offset, role in enumerate(("revenue", "cfads")):
            series_id = new_uuid()
            output_rows.append(
                FinancialSeries(
                    id=series_id,
                    model_version_id=model_id,
                    entity_kind="financial_series",
                    label=role.upper(),
                    semantic_role="financial_series",
                    business_role=role,
                    unit="USDm",
                    frequency="annual",
                    orientation="horizontal",
                    calculation_type="formula",
                    period_source_range=f"Cash Flow!B{offset + 1}:C{offset + 1}",
                    value_source_range=f"Cash Flow!B{offset + 3}:C{offset + 3}",
                    materialization_status="materialized",
                    validation_status="validated",
                )
            )
            projection_rows.append(
                {
                    "output_id": series_id,
                    "entity_kind": "series",
                    "business_role": role,
                    "label": role.upper(),
                    "unit": "USDm",
                    "mapping_status": "mapped",
                    "support_status": "supported",
                    "availability_status": "available",
                    "points": [
                        {
                            "financial_series_value_id": new_uuid(),
                            "period_index": index,
                            "period": str(2026 + index),
                            "mapping_status": "mapped",
                            "support_status": "supported",
                            "availability_status": "available",
                            "baseline": _projected_number(value),
                            "current": _projected_number(value),
                        }
                        for index, value in enumerate(("10", "12"))
                    ],
                }
            )
            session.add(
                ModelSemanticBinding(
                    id=new_uuid(),
                    model_version_id=model_id,
                    semantic_role=role,
                    financial_series_id=series_id,
                    binding_source="reviewed",
                )
            )
        session.add_all(output_rows)
        session.commit()
        projection = CalculationRunOutputsResponse.model_validate(
            {
                "calculation_run_id": run_id,
                "model_version_id": model_id,
                "graph_version_id": graph_id,
                "comparison_baseline_run_id": run_id,
                "outputs": projection_rows,
            }
        )
        service = AnalysisPresentationService(
            session,
            _ProjectionService(projection),  # type: ignore[arg-type]
        )

        response = service.overview(run_id)

        trajectory = next(
            chart
            for chart in response.charts
            if chart.slot == "operating_trajectory"
        )
        assert trajectory.availability_status == "available"
        assert trajectory.fallback_used == "revenue+cfads"
        assert [series.role for series in trajectory.series] == [
            "revenue",
            "cfads",
        ]
    finally:
        session.close()
        engine.dispose()
