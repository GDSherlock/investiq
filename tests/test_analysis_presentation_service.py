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


def _projected_unavailable(reason: str) -> dict[str, object]:
    return {
        "availability_status": "unavailable",
        "value": None,
        "unavailable_reason": reason,
        "execution_status": "derived_unavailable",
        "engine_error_code": None,
        "validation_status": "not_comparable",
        "warnings": [],
    }


def _scalar_output(role: str, value: str) -> dict[str, object]:
    return {
        "output_id": new_uuid(),
        "entity_kind": "scalar",
        "business_role": role,
        "label": role,
        "unit": "x",
        "scenario": None,
        "formula_cell_id": new_uuid(),
        "mapping_status": "mapped",
        "support_status": "supported",
        "number_format": "0.00x",
        "availability_status": "available",
        "baseline": _projected_number(value),
        "current": _projected_number(value),
    }


def _overview_projection(
    *,
    derived_baseline: str | None = None,
    derived_current: str | None = None,
    derived_unavailable_reason: str | None = None,
) -> CalculationRunOutputsResponse:
    run_id = new_uuid()
    unavailable_reason = (
        derived_unavailable_reason or "EQUITY_CASH_FLOW_UNAVAILABLE"
    )
    baseline = (
        _projected_number(derived_baseline)
        if derived_baseline is not None
        else _projected_unavailable(unavailable_reason)
    )
    current = (
        _projected_number(derived_current)
        if derived_current is not None
        else _projected_unavailable(unavailable_reason)
    )
    return CalculationRunOutputsResponse.model_validate(
        {
            "calculation_run_id": run_id,
            "model_version_id": new_uuid(),
            "graph_version_id": new_uuid(),
            "comparison_baseline_run_id": run_id,
            "outputs": [
                _scalar_output("equity_multiple", "9.9"),
                _scalar_output("debt_to_equity_ratio", "4.0"),
            ],
            "derived_kpis": [
                {
                    "role": "equity_multiple",
                    "label": "Equity ×",
                    "unit": "x",
                    "source_type": "derived",
                    "availability_status": (
                        "available"
                        if derived_baseline is not None
                        and derived_current is not None
                        else "unavailable"
                    ),
                    "source_ids": [new_uuid()],
                    "baseline": baseline,
                    "current": current,
                }
            ],
        }
    )


def _overview(projection: CalculationRunOutputsResponse):
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        return AnalysisPresentationService(
            session,
            _ProjectionService(projection),  # type: ignore[arg-type]
        ).overview(projection.calculation_run_id)
    finally:
        session.close()
        engine.dispose()


def test_overview_leverage_uses_derived_equity_multiple_only() -> None:
    projection = _overview_projection(
        derived_baseline="1.2",
        derived_current="1.8",
    )

    response = _overview(projection)

    leverage = next(kpi for kpi in response.kpis if kpi.slot == "leverage")
    assert leverage.role == "equity_multiple"
    assert leverage.label == "Equity ×"
    assert leverage.value == "1.8"
    assert leverage.display_value == "1.80x"
    assert leverage.source_type == "derived"
    assert leverage.source_ids == projection.derived_kpis[0].source_ids


def test_overview_does_not_fallback_when_derived_equity_multiple_is_unavailable() -> None:
    projection = _overview_projection(
        derived_unavailable_reason="EQUITY_CASH_OUTFLOW_ZERO",
    )

    response = _overview(projection)

    leverage = next(kpi for kpi in response.kpis if kpi.slot == "leverage")
    assert leverage.value is None
    assert leverage.display_value == "Unavailable"
    assert leverage.source_type == "unavailable"
    assert leverage.quality_status == "EQUITY_CASH_OUTFLOW_ZERO"
    assert leverage.source_ids == projection.derived_kpis[0].source_ids


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
                        "business_role": "unclassified",
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


def test_cash_flow_charts_use_persisted_project_fcf_binding() -> None:
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
                sha256="d" * 64,
                original_filename="bound-cash-flow.xlsx",
                storage_type="database",
                storage_ref="workbooks/bound-cash-flow.xlsx",
                content_bytes=b"x",
                file_size=1,
            )
        )
        session.add(
            ModelVersion(
                id=model_id,
                workbook_version_id=workbook_id,
                upload_filename="bound-cash-flow.xlsx",
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
                label="Project FCF",
                semantic_role="financial_series",
                business_role="cash_flow",
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
                binding_source="extracted",
                evidence_json={"selection_method": "deterministic_best_match"},
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
                "availability_status": "available",
                "baseline": _projected_number(value),
                "current": _projected_number(value),
            }
            for index, value in enumerate(("-10", "4", "9"))
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
                        "business_role": "unclassified",
                        "label": "Project FCF",
                        "unit": "USDm",
                        "mapping_status": "mapped",
                        "support_status": "supported",
                        "availability_status": "available",
                        "points": points,
                    }
                ],
            }
        )

        response = AnalysisPresentationService(
            session,
            _ProjectionService(projection),  # type: ignore[arg-type]
        ).cash_flow(run_id)

        annual = next(
            chart
            for chart in response.charts
            if chart.slot == "annual_project_free_cash_flow"
        )
        cumulative = next(
            chart
            for chart in response.charts
            if chart.slot == "cumulative_cash_flow"
        )
        assert [point.value for point in annual.series[0].points] == [
            "-10",
            "4",
            "9",
        ]
        assert [point.value for point in cumulative.series[0].points] == [
            "-10",
            "-6",
            "3",
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
                    "business_role": "unclassified",
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
        project_cash_generation = next(
            chart
            for chart in response.charts
            if chart.slot == "project_cash_generation"
        )
        assert project_cash_generation.availability_status == "available"
        assert [series.role for series in project_cash_generation.series] == ["cfads"]
        assert [point.value for point in project_cash_generation.series[0].points] == [
            "10",
            "12",
        ]
    finally:
        session.close()
        engine.dispose()


def test_overview_resolves_cfads_from_direct_role_without_label_alias() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        run_id = new_uuid()
        model_id = new_uuid()
        graph_id = new_uuid()
        projection_rows = []
        for role, business_role, label in (
            ("revenue", "unclassified", "REVENUE"),
            ("cfads", "cfads", "Cash available for lenders"),
        ):
            projection_rows.append(
                {
                    "output_id": new_uuid(),
                    "entity_kind": "series",
                    "business_role": business_role,
                    "label": label,
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
        assert trajectory.fallback_used == "revenue+cfads"
        assert [series.role for series in trajectory.series] == [
            "revenue",
            "cfads",
        ]
        assert trajectory.series[1].label == "Cash available for lenders"
    finally:
        session.close()
        engine.dispose()


def test_overview_prefers_persisted_best_match_bindings_for_ambiguous_series() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        workbook_id = new_uuid()
        model_id = new_uuid()
        run_id = new_uuid()
        graph_id = new_uuid()
        selected_revenue_id = new_uuid()
        alias_revenue_id = new_uuid()
        ebitda_id = new_uuid()
        dscr_id = new_uuid()
        session.add(
            WorkbookVersion(
                id=workbook_id,
                sha256="d" * 64,
                original_filename="bound-overview.xlsx",
                storage_type="database",
                storage_ref="workbooks/bound-overview.xlsx",
                content_bytes=b"x",
                file_size=1,
            )
        )
        session.add(
            ModelVersion(
                id=model_id,
                workbook_version_id=workbook_id,
                upload_filename="bound-overview.xlsx",
                status="materialized",
                validation_status="validated",
                submitted=True,
            )
        )

        series_specs = (
            (selected_revenue_id, "Revenue", "revenue", "P&L!B3:C3"),
            (alias_revenue_id, "Revenue", "revenue", "P&L!B4:C4"),
            (ebitda_id, "EBITDA", "ebitda", "P&L!B5:C5"),
            (dscr_id, "DSCR", "minimum_dscr", "Debt!B6:C6"),
        )
        session.add_all(
            [
                FinancialSeries(
                    id=series_id,
                    model_version_id=model_id,
                    entity_kind="financial_series",
                    label=label,
                    semantic_role="financial_series",
                    business_role=business_role,
                    unit="x" if label == "DSCR" else "USDm",
                    frequency="annual",
                    orientation="horizontal",
                    calculation_type="formula",
                    period_source_range="P&L!B2:C2",
                    value_source_range=value_range,
                    materialization_status="materialized",
                    validation_status="validated",
                )
                for series_id, label, business_role, value_range in series_specs
            ]
        )
        session.flush()
        session.add_all(
            [
                ModelSemanticBinding(
                    id=new_uuid(),
                    model_version_id=model_id,
                    semantic_role="revenue",
                    financial_series_id=selected_revenue_id,
                    binding_source="extracted",
                    evidence_json={"selection_method": "deterministic_best_match"},
                ),
                ModelSemanticBinding(
                    id=new_uuid(),
                    model_version_id=model_id,
                    semantic_role="dscr",
                    financial_series_id=dscr_id,
                    binding_source="extracted",
                    evidence_json={"selection_method": "deterministic_best_match"},
                ),
            ]
        )
        session.commit()

        projection_rows = []
        for series_id, label, business_role, _value_range in series_specs:
            projection_rows.append(
                {
                    "output_id": series_id,
                    "entity_kind": "series",
                    "business_role": business_role,
                    "label": label,
                    "unit": "x" if label == "DSCR" else "USDm",
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

        operating = next(
            chart for chart in response.charts if chart.slot == "operating_trajectory"
        )
        assert operating.availability_status == "available"
        assert [series.source_ids for series in operating.series] == [
            [selected_revenue_id],
            [ebitda_id],
        ]
        debt_coverage = next(
            chart for chart in response.charts if chart.slot == "debt_coverage"
        )
        assert debt_coverage.availability_status == "available"
        assert debt_coverage.fallback_used == "dscr_only"
        assert debt_coverage.series[0].source_ids == [dscr_id]
        assert debt_coverage.series[0].role == "dscr"
    finally:
        session.close()
        engine.dispose()
