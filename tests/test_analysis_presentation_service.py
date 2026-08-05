from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from apps.api.app.analysis_presentation_service import AnalysisPresentationService
from apps.api.app.calculation_rules.phase2_models import (
    CalculationGraphVersionRecord,
    CalculationRunRecord,
)
from apps.api.app.database import Base
from apps.api.app.model_extraction_models import (
    CanonicalOutput,
    FinancialSeries,
    FinancialSeriesValue,
    ModelParameter,
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


_CAPEX_LABELS = (
    "Base EPC spend ($mm)",
    "Capex ($mm)",
    "Contingency ($mm)",
    "Cumulative capex ($mm)",
    "Total capex ($mm)",
)


def _persist_capex_candidates(session):
    workbook_id = new_uuid()
    model_id = new_uuid()
    run_id = new_uuid()
    graph_id = new_uuid()
    session.add(
        WorkbookVersion(
            id=workbook_id,
            sha256="a" * 64,
            original_filename="capex-ranking.xlsx",
            storage_type="database",
            storage_ref="workbooks/capex-ranking.xlsx",
            content_bytes=b"x",
            file_size=1,
        )
    )
    session.add(
        ModelVersion(
            id=model_id,
            workbook_version_id=workbook_id,
            upload_filename="capex-ranking.xlsx",
            status="materialized",
            validation_status="validated",
            submitted=True,
        )
    )
    ids = {label: new_uuid() for label in _CAPEX_LABELS}
    point_ids: dict[str, list[str]] = {}
    for row_number, label in enumerate(_CAPEX_LABELS, start=3):
        series_id = ids[label]
        session.add(
            FinancialSeries(
                id=series_id,
                model_version_id=model_id,
                entity_kind="financial_series",
                label=label,
                semantic_role="financial_series",
                business_role="total_capex",
                unit="$mm",
                frequency="annual",
                orientation="horizontal",
                calculation_type="formula",
                period_source_range="Capex!B1:C1",
                value_source_range=f"Capex!B{row_number}:C{row_number}",
                materialization_status="materialized_with_warning",
                validation_status="validated_with_warning",
            )
        )
        point_ids[label] = []
        for period_index, column in enumerate(("B", "C")):
            value_id = new_uuid()
            point_ids[label].append(value_id)
            session.add(
                FinancialSeriesValue(
                    id=value_id,
                    financial_series_id=series_id,
                    period_index=period_index,
                    raw_period_label_json=2027 + period_index,
                    display_period_label=str(2027 + period_index),
                    period_type="year",
                    year=2027 + period_index,
                    is_forecast=True,
                    value_json="50" if period_index == 0 else "60",
                    period_source_sheet="Capex",
                    period_source_cell=f"{column}1",
                    value_source_sheet="Capex",
                    value_source_cell=f"{column}{row_number}",
                    exact_formula=f"={column}10+{column}11",
                    formula_status="formula_with_cached_value",
                    cached_value_available=True,
                    cached_value_freshness="unknown",
                    number_format="$0.00",
                    data_type="number",
                )
            )
    session.commit()
    return model_id, run_id, graph_id, ids, point_ids


def _capex_projection(
    model_id: str,
    run_id: str,
    graph_id: str,
    ids: dict[str, str],
    point_ids: dict[str, list[str]],
    included_labels: tuple[str, ...],
) -> CalculationRunOutputsResponse:
    return CalculationRunOutputsResponse.model_validate(
        {
            "calculation_run_id": run_id,
            "model_version_id": model_id,
            "graph_version_id": graph_id,
            "comparison_baseline_run_id": run_id,
            "outputs": [
                {
                    "output_id": ids[label],
                    "entity_kind": "series",
                    "business_role": "total_capex",
                    "label": label,
                    "unit": "$mm",
                    "mapping_status": "mapped",
                    "support_status": "supported",
                    "availability_status": "available",
                    "points": [
                        {
                            "financial_series_value_id": point_ids[label][index],
                            "period_index": index,
                            "period": str(2027 + index),
                            "mapping_status": "mapped",
                            "support_status": "supported",
                            "availability_status": "available",
                            "baseline": _projected_number(value),
                            "current": _projected_number(value),
                        }
                        for index, value in enumerate(("50", "60"))
                    ],
                }
                for label in included_labels
            ],
        }
    )


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


def _capital_scalar(
    output_id: str,
    role: str,
    label: str,
    value: str,
    unit: str | None = "USDm",
) -> dict[str, object]:
    return {
        "output_id": output_id,
        "entity_kind": "scalar",
        "business_role": role,
        "label": label,
        "unit": unit,
        "scenario": None,
        "formula_cell_id": new_uuid(),
        "mapping_status": "mapped",
        "support_status": "supported",
        "number_format": "0.00",
        "availability_status": "available",
        "baseline": _projected_number(value),
        "current": _projected_number(value),
    }


def _persist_capital_model(session):
    workbook_id = new_uuid()
    model_id = new_uuid()
    graph_id = new_uuid()
    run_id = new_uuid()
    session.add(
        WorkbookVersion(
            id=workbook_id,
            sha256="e" * 64,
            original_filename="capital.xlsx",
            storage_type="database",
            storage_ref="workbooks/capital.xlsx",
            content_bytes=b"x",
            file_size=1,
        )
    )
    session.add(
        ModelVersion(
            id=model_id,
            workbook_version_id=workbook_id,
            upload_filename="capital.xlsx",
            status="materialized",
            validation_status="validated",
            submitted=True,
        )
    )
    session.flush()
    session.add(
        CalculationGraphVersionRecord(
            id=graph_id,
            workbook_version_id=workbook_id,
            compiler_version="test",
            ir_version="test",
            function_registry_version="test",
            semantics_profile="test",
            compiler_manifest_hash="1" * 64,
            content_fingerprint="2" * 64,
            node_count=0,
            edge_count=0,
            topological_layers_json=[],
            volatile_nodes_json=[],
        )
    )
    session.commit()
    return model_id, graph_id, run_id


def _persist_debt_share(
    session,
    model_id: str,
    value: str,
) -> str:
    parameter_id = new_uuid()
    session.add(
        ModelParameter(
            id=parameter_id,
            model_version_id=model_id,
            entity_kind="parameter",
            source_bucket="parameter_candidates",
            label="Debt share",
            business_role=None,
            submitted_role="assumption",
            validated_role="assumption",
            raw_value_json=value,
            validated_value_json=value,
            unit="%",
            source_sheet="Assumptions",
            source_cell="B4",
            formula_status="static_value",
            source_validation_status="valid",
            role_validation_status="confirmed",
            validation_status="validated",
        )
    )
    session.commit()
    return parameter_id


def _capital_overview(
    session,
    *,
    model_id: str,
    graph_id: str,
    run_id: str,
    outputs: list[dict[str, object]],
):
    projection = CalculationRunOutputsResponse.model_validate(
        {
            "calculation_run_id": run_id,
            "model_version_id": model_id,
            "graph_version_id": graph_id,
            "comparison_baseline_run_id": run_id,
            "outputs": outputs,
        }
    )
    response = AnalysisPresentationService(
        session,
        _ProjectionService(projection),  # type: ignore[arg-type]
    ).overview(run_id)
    return next(
        chart
        for chart in response.charts
        if chart.slot == "capital_structure"
    )


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


def test_capital_structure_prefers_model_debt_share() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        model_id, graph_id, run_id = _persist_capital_model(session)
        parameter_id = _persist_debt_share(session, model_id, "0.65")

        capital = _capital_overview(
            session,
            model_id=model_id,
            graph_id=graph_id,
            run_id=run_id,
            outputs=[],
        )

        assert capital.availability_status == "available"
        assert capital.source_type == "derived"
        assert capital.fallback_used == "model_debt_share"
        assert capital.unavailable_reason is None
        assert [(item.role, item.points[0].value) for item in capital.series] == [
            ("debt_ratio", "0.65"),
            ("equity_ratio", "0.35"),
        ]
        assert all(item.source_ids == [parameter_id] for item in capital.series)
    finally:
        session.close()
        engine.dispose()


def test_capital_structure_uses_current_debt_share_override() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        model_id, graph_id, run_id = _persist_capital_model(session)
        parameter_id = _persist_debt_share(session, model_id, "0.65")
        session.add(
            CalculationRunRecord(
                id=run_id,
                model_version_id=model_id,
                graph_version_id=graph_id,
                engine_version="test",
                function_registry_version="test",
                semantics_profile="test",
                normalized_override_hash="3" * 64,
                run_policy_hash="4" * 64,
                overrides_json=[
                    {
                        "target_kind": "parameter",
                        "target_id": parameter_id,
                        "typed_value": {"kind": "number", "number": "0.70"},
                    }
                ],
                run_policy_json={},
                status="completed",
            )
        )
        session.commit()

        capital = _capital_overview(
            session,
            model_id=model_id,
            graph_id=graph_id,
            run_id=run_id,
            outputs=[],
        )

        assert [(item.role, item.points[0].value) for item in capital.series] == [
            ("debt_ratio", "0.70"),
            ("equity_ratio", "0.30"),
        ]
    finally:
        session.close()
        engine.dispose()


def test_capital_structure_derives_debt_over_total_project_cost() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        model_id, graph_id, run_id = _persist_capital_model(session)
        debt_id = new_uuid()
        cost_id = new_uuid()
        session.add(
            CanonicalOutput(
                id=debt_id,
                model_version_id=model_id,
                entity_kind="canonical_output",
                label="Total debt",
                business_role="total_debt",
                submitted_role="formula_output",
                validated_role="formula_output",
                raw_value_json="70",
                unit="USDm",
                source_sheet="Funding",
                source_cell="B2",
                formula_status="formula_with_cached_value",
                source_validation_status="valid",
                role_validation_status="confirmed",
                validation_status="validated",
            )
        )
        session.flush()
        session.add(
            ModelSemanticBinding(
                id=new_uuid(),
                model_version_id=model_id,
                semantic_role="total_debt",
                canonical_output_id=debt_id,
                binding_source="extracted",
            )
        )
        session.commit()

        capital = _capital_overview(
            session,
            model_id=model_id,
            graph_id=graph_id,
            run_id=run_id,
            outputs=[
                _capital_scalar(debt_id, "unclassified", "Debt", "70"),
                _capital_scalar(
                    cost_id,
                    "total_project_cost",
                    "Total project cost",
                    "100",
                ),
            ],
        )

        assert capital.fallback_used == "debt_over_total_project_cost"
        assert [(item.role, item.points[0].value) for item in capital.series] == [
            ("debt_ratio", "0.7"),
            ("equity_ratio", "0.3"),
        ]
        assert capital.series[0].source_ids == [debt_id, cost_id]
    finally:
        session.close()
        engine.dispose()


def test_capital_structure_reports_stable_unavailable_reasons() -> None:
    cases = (
        ("-0.1", [], "CAPITAL_DEBT_SHARE_INVALID"),
        ("1.1", [], "CAPITAL_DEBT_SHARE_INVALID"),
        (None, [], "CAPITAL_DEBT_NOT_FOUND"),
        (
            None,
            [("total_debt", "Total debt", "70", "USDm")],
            "CAPITAL_PROJECT_COST_NOT_FOUND",
        ),
        (
            None,
            [
                ("total_debt", "Total debt", "70", "USDm"),
                ("total_project_cost", "Total project cost", "0", "USDm"),
            ],
            "CAPITAL_RATIO_OUT_OF_RANGE",
        ),
        (
            None,
            [
                ("total_debt", "Total debt", "110", "USDm"),
                ("total_project_cost", "Total project cost", "100", "USDm"),
            ],
            "CAPITAL_RATIO_OUT_OF_RANGE",
        ),
        (
            None,
            [
                ("total_debt", "Total debt", "70", "USDm"),
                ("total_project_cost", "Total project cost", "100", "USDm"),
                (
                    "total_project_cost",
                    "Total funding requirement",
                    "120",
                    "USDm",
                ),
            ],
            "CAPITAL_PROJECT_COST_AMBIGUOUS",
        ),
        (
            None,
            [
                ("total_debt", "Total debt", "70", "USDm"),
                ("total_project_cost", "Total project cost", "100", "EURm"),
            ],
            "CAPITAL_UNIT_MISMATCH",
        ),
    )
    for debt_share, output_specs, reason in cases:
        engine, session_factory = create_sqlite_session_factory()
        Base.metadata.create_all(engine)
        session = session_factory()
        try:
            model_id, graph_id, run_id = _persist_capital_model(session)
            if debt_share is not None:
                _persist_debt_share(session, model_id, debt_share)
            outputs = [
                _capital_scalar(new_uuid(), role, label, value, unit)
                for role, label, value, unit in output_specs
            ]

            capital = _capital_overview(
                session,
                model_id=model_id,
                graph_id=graph_id,
                run_id=run_id,
                outputs=outputs,
            )

            assert capital.availability_status == "unavailable"
            assert capital.series == []
            assert capital.unavailable_reason == reason
        finally:
            session.close()
            engine.dispose()


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


def test_cash_flow_capex_uses_ranked_persisted_series_without_writing_binding() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        model_id, run_id, graph_id, ids, point_ids = _persist_capex_candidates(
            session
        )
        projection = _capex_projection(
            model_id,
            run_id,
            graph_id,
            ids,
            point_ids,
            ("Capex ($mm)", "Total capex ($mm)"),
        )

        response = AnalysisPresentationService(
            session,
            _ProjectionService(projection),  # type: ignore[arg-type]
        ).cash_flow(run_id)

        capex = next(
            chart
            for chart in response.charts
            if chart.slot == "capex_construction_profile"
        )
        assert capex.availability_status == "available"
        assert capex.series[0].role == "capex"
        assert capex.series[0].label == "Capex ($mm)"
        assert capex.series[0].source_ids == [ids["Capex ($mm)"]]
        assert [point.value for point in capex.series[0].points] == [
            "50",
            "60",
        ]
        assert [point.source_ids for point in capex.series[0].points] == [
            [point_ids["Capex ($mm)"][0]],
            [point_ids["Capex ($mm)"][1]],
        ]
        assert session.scalar(
            select(func.count())
            .select_from(ModelSemanticBinding)
            .where(ModelSemanticBinding.model_version_id == model_id)
        ) == 0
    finally:
        session.close()
        engine.dispose()


def test_cash_flow_capex_reviewed_binding_wins_over_read_time_ranking() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        model_id, run_id, graph_id, ids, point_ids = _persist_capex_candidates(
            session
        )
        reviewed_id = ids["Total capex ($mm)"]
        session.add(
            ModelSemanticBinding(
                id=new_uuid(),
                model_version_id=model_id,
                semantic_role="capex",
                financial_series_id=reviewed_id,
                binding_source="reviewed",
                evidence_json={"review_method": "canonical_uuid"},
            )
        )
        session.commit()
        projection = _capex_projection(
            model_id,
            run_id,
            graph_id,
            ids,
            point_ids,
            ("Capex ($mm)", "Total capex ($mm)"),
        )

        response = AnalysisPresentationService(
            session,
            _ProjectionService(projection),  # type: ignore[arg-type]
        ).cash_flow(run_id)

        capex = next(
            chart
            for chart in response.charts
            if chart.slot == "capex_construction_profile"
        )
        assert capex.series[0].label == "Total capex ($mm)"
        assert capex.series[0].source_ids == [reviewed_id]
    finally:
        session.close()
        engine.dispose()


def test_cash_flow_capex_stays_unavailable_when_ranked_series_is_not_projected() -> None:
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        model_id, run_id, graph_id, ids, point_ids = _persist_capex_candidates(
            session
        )
        projection = _capex_projection(
            model_id,
            run_id,
            graph_id,
            ids,
            point_ids,
            ("Total capex ($mm)",),
        )

        response = AnalysisPresentationService(
            session,
            _ProjectionService(projection),  # type: ignore[arg-type]
        ).cash_flow(run_id)

        capex = next(
            chart
            for chart in response.charts
            if chart.slot == "capex_construction_profile"
        )
        assert capex.availability_status == "unavailable"
        assert capex.series == []
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
