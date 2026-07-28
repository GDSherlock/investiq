"""Canonical persisted read models for the Overview and Cash Flow pages."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analysis_output_resolver import (
    normalized_analysis_label,
    resolve_analysis_output,
)
from .calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from .calculation_rules.phase2_models import CalculationRunRecord
from .model_extraction_models import ModelParameter, ModelVersion
from .schemas import (
    AnalysisBenchmarkItem,
    AnalysisChartItem,
    AnalysisKpiItem,
    AnalysisSeriesItem,
    AnalysisSeriesPointItem,
    CalculationProjectedValueItem,
    CalculationRunOutputsResponse,
    CalculationRunScalarOutputItem,
    CalculationRunSeriesOutputItem,
    CashFlowAnalysisResponse,
    ModelDiagnosticsResponse,
    OverviewAnalysisResponse,
)


_KPI_SLOTS = (
    ("primary_return", ("project_irr", "equity_irr"), "Return"),
    ("npv", ("project_npv", "equity_npv"), "NPV"),
    ("payback_period", ("payback_period",), "Payback period"),
    ("minimum_dscr", ("minimum_dscr",), "Minimum DSCR"),
    ("average_dscr", ("average_dscr",), "Average DSCR"),
    (
        "leverage",
        ("equity_multiple", "debt_to_equity_ratio"),
        "Equity multiple",
    ),
)

_CASH_FLOW_CHARTS = (
    (
        "annual_project_free_cash_flow",
        "Annual project free cash flow",
        ("project_free_cash_flow",),
    ),
    (
        "annual_equity_cash_flow",
        "Annual equity cash flow",
        ("equity_cash_flow",),
    ),
    (
        "cfads_vs_debt_service",
        "CFADS vs debt service",
        ("cfads", "debt_service"),
    ),
    (
        "dscr_vs_covenant",
        "DSCR vs covenant",
        ("dscr", "dscr_covenant"),
    ),
    ("cumulative_cash_flow", "Cumulative cash flow", ()),
    (
        "debt_balance_profile",
        "Debt balance profile",
        ("closing_debt",),
    ),
    (
        "capex_construction_profile",
        "Capex construction profile",
        ("capex",),
    ),
    (
        "interest_and_principal_profile",
        "Interest and principal profile",
        ("interest_expense", "principal_repayment"),
    ),
)

_PARAMETER_LABEL_ALIASES = {
    "discount_rate": frozenset({"discount rate", "wacc"}),
    "project_irr_hurdle": frozenset(
        {"project irr hurdle", "project irr hurdle rate"}
    ),
    "equity_irr_hurdle": frozenset(
        {"equity irr hurdle", "equity irr hurdle rate"}
    ),
    "dscr_covenant": frozenset(
        {"dscr covenant", "minimum dscr covenant"}
    ),
}


class AnalysisPresentationService:
    def __init__(
        self,
        session: Session,
        calculation_service: CalculationIntegrationService,
    ) -> None:
        self._session = session
        self._calculation_service = calculation_service

    def overview(self, calculation_run_id: str) -> OverviewAnalysisResponse:
        projection = self._calculation_service.get_run_outputs(calculation_run_id)
        kpis = [
            self._kpi(
                projection,
                slot=slot,
                roles=roles,
                default_label=label,
            )
            for slot, roles, label in _KPI_SLOTS
        ]
        charts = self._overview_charts(projection)
        return OverviewAnalysisResponse(
            calculation_run_id=projection.calculation_run_id,
            model_version_id=projection.model_version_id,
            graph_version_id=projection.graph_version_id,
            kpis=kpis,
            charts=charts,
        )

    def cash_flow(self, calculation_run_id: str) -> CashFlowAnalysisResponse:
        projection = self._calculation_service.get_run_outputs(calculation_run_id)
        charts: list[AnalysisChartItem] = []
        for slot, title, roles in _CASH_FLOW_CHARTS:
            if slot == "cumulative_cash_flow":
                charts.append(
                    self._cumulative_chart(projection, slot, title)
                )
                continue
            series = [
                item
                for role in roles
                if (
                    item := self._series_for_role(
                        projection,
                        role,
                    )
                )
                is not None
            ]
            charts.append(self._chart(slot, title, series))
        return CashFlowAnalysisResponse(
            calculation_run_id=projection.calculation_run_id,
            model_version_id=projection.model_version_id,
            graph_version_id=projection.graph_version_id,
            charts=charts,
        )

    def diagnostics(self, model_version_id: str) -> ModelDiagnosticsResponse:
        model = self._session.get(ModelVersion, model_version_id)
        if model is None:
            raise CalculationIntegrationError(
                "MODEL_VERSION_NOT_FOUND",
                "Model version was not found.",
                status_code=404,
                resource_id=model_version_id,
            )
        validation_results = model.validation_results_json
        errors = 0
        if isinstance(validation_results, list):
            errors = sum(
                1
                for item in validation_results
                if isinstance(item, dict)
                and (
                    item.get("validation_status") == "rejected"
                    or item.get("error_code")
                )
            )
        coverage = model.coverage_json if isinstance(model.coverage_json, dict) else {}
        raw_sheets = coverage.get("sheets", [])
        detected_sheets = []
        if isinstance(raw_sheets, list):
            for sheet in raw_sheets:
                if isinstance(sheet, str):
                    detected_sheets.append(sheet)
                elif isinstance(sheet, dict) and isinstance(sheet.get("name"), str):
                    detected_sheets.append(sheet["name"])
        return ModelDiagnosticsResponse(
            model_version_id=model.id,
            status=model.status,
            validation_status=model.validation_status,
            submitted=model.submitted,
            stop_reason=model.stop_reason,
            error_code=model.error_code,
            coverage=coverage,
            validation_summary=(
                model.validation_summary_json
                if isinstance(model.validation_summary_json, dict)
                else {}
            ),
            time_series_summary=(
                model.time_series_summary_json
                if isinstance(model.time_series_summary_json, dict)
                else {}
            ),
            detected_sheets=detected_sheets,
            error_count=errors,
        )

    def _overview_charts(
        self,
        projection: CalculationRunOutputsResponse,
    ) -> list[AnalysisChartItem]:
        revenue = self._series_for_role(projection, "revenue")
        ebitda = self._series_for_role(projection, "ebitda")
        cfads = self._series_for_role(projection, "cfads")
        if revenue is not None and ebitda is not None:
            operating = self._chart(
                "operating_trajectory",
                "Operating trajectory",
                [revenue, ebitda],
            )
        elif revenue is not None and cfads is not None:
            operating = self._chart(
                "operating_trajectory",
                "Operating trajectory",
                [revenue, cfads],
                fallback_used="revenue+cfads",
            )
        else:
            operating = self._chart(
                "operating_trajectory",
                "Operating trajectory",
                [],
            )

        debt_ratio = self._series_for_role(projection, "debt_ratio")
        equity_ratio = self._series_for_role(projection, "equity_ratio")
        if debt_ratio is not None and equity_ratio is not None:
            capital = self._chart(
                "capital_structure",
                "Capital structure",
                [debt_ratio, equity_ratio],
            )
        else:
            total_debt = self._series_for_role(
                projection,
                "total_debt",
            )
            total_equity = self._series_for_role(
                projection,
                "total_equity",
            )
            capital = self._chart(
                "capital_structure",
                "Capital structure",
                (
                    [total_debt, total_equity]
                    if total_debt is not None and total_equity is not None
                    else []
                ),
                fallback_used=(
                    "debt_amount+equity_amount"
                    if total_debt is not None and total_equity is not None
                    else None
                ),
            )

        dscr = self._series_for_role(projection, "dscr")
        covenant = self._series_for_role(
            projection,
            "dscr_covenant",
        )
        coverage_series = [item for item in (dscr, covenant) if item is not None]
        debt_coverage = self._chart(
            "debt_coverage",
            "Debt coverage",
            coverage_series if dscr is not None else [],
            fallback_used="dscr_only" if dscr is not None and covenant is None else None,
        )

        project_fcf = self._series_for_role(
            projection,
            "project_free_cash_flow",
        )
        project_cash_series = [
            item for item in (project_fcf, cfads) if item is not None
        ]
        fallback_used = None
        if not project_cash_series:
            operating_cash = self._series_for_role(
                projection,
                "operating_cash_flow",
            )
            if operating_cash is not None:
                project_cash_series = [operating_cash]
                fallback_used = "operating_cash_flow"
        project_cash = self._chart(
            "project_cash_generation",
            "Project cash generation",
            project_cash_series,
            fallback_used=fallback_used,
        )
        return [operating, capital, debt_coverage, project_cash]

    def _kpi(
        self,
        projection: CalculationRunOutputsResponse,
        *,
        slot: str,
        roles: tuple[str, ...],
        default_label: str,
    ) -> AnalysisKpiItem:
        for role in roles:
            output = resolve_analysis_output(
                projection.outputs,
                role,
                entity_kind="scalar",
            )
            if not isinstance(output, CalculationRunScalarOutputItem):
                continue
            value = self._number(output.current)
            if value is None:
                continue
            benchmark = self._benchmark(projection, role)
            return AnalysisKpiItem(
                slot=slot,
                role=role,
                label=self._role_label(role, output.label),
                value=value,
                unit=output.unit,
                display_value=self._display_value(role, value, output.unit),
                benchmark=benchmark,
                status=self._comparison_status(role, value, benchmark),
                source_type="calculated",
                availability_status="available",
                quality_status=(
                    output.current.validation_status or "not_comparable"
                ),
                validation_status=output.current.validation_status,
                calculation_run_id=projection.calculation_run_id,
                source_ids=[output.output_id],
            )
        return AnalysisKpiItem(
            slot=slot,
            role=roles[0],
            label=default_label,
            value=None,
            unit=None,
            display_value="Unavailable",
            benchmark=None,
            status="unavailable",
            source_type="unavailable",
            availability_status="unavailable",
            quality_status="unavailable",
            validation_status=None,
            calculation_run_id=projection.calculation_run_id,
            source_ids=[],
        )

    def _benchmark(
        self,
        projection: CalculationRunOutputsResponse,
        role: str,
    ) -> AnalysisBenchmarkItem | None:
        benchmark_role = {
            "project_irr": "project_irr_hurdle",
            "equity_irr": "equity_irr_hurdle",
            "project_npv": "discount_rate",
            "equity_npv": "discount_rate",
            "minimum_dscr": "dscr_covenant",
            "average_dscr": "dscr_covenant",
        }.get(role)
        if benchmark_role is None:
            return None
        parameter = self._parameter_for_role(
            projection.model_version_id,
            benchmark_role,
        )
        if parameter is None:
            return None
        value = self._current_parameter_value(
            projection.calculation_run_id,
            parameter.id,
            parameter.validated_value_json,
        )
        if value is None:
            return None
        return AnalysisBenchmarkItem(
            role=benchmark_role,
            value=value,
            display_value=self._display_value(benchmark_role, value, None),
            source_ids=[parameter.id],
        )

    def _parameter_for_role(
        self,
        model_version_id: str,
        role: str,
    ) -> ModelParameter | None:
        parameters = list(
            self._session.scalars(
                select(ModelParameter).where(
                    ModelParameter.model_version_id == model_version_id
                )
            )
        )
        direct = [
            parameter
            for parameter in parameters
            if parameter.business_role == role
        ]
        if len(direct) == 1:
            return direct[0]
        if direct:
            return None
        aliases = _PARAMETER_LABEL_ALIASES.get(role, frozenset())
        legacy = [
            parameter
            for parameter in parameters
            if parameter.business_role is None
            and normalized_analysis_label(parameter.label) in aliases
        ]
        return legacy[0] if len(legacy) == 1 else None

    def _current_parameter_value(
        self,
        calculation_run_id: str,
        parameter_id: str,
        baseline_value: Any,
    ) -> str | None:
        run = self._session.get(CalculationRunRecord, calculation_run_id)
        if run is not None:
            for override in run.overrides_json or []:
                if (
                    override.get("target_kind") == "parameter"
                    and override.get("target_id") == parameter_id
                ):
                    typed = override.get("typed_value")
                    if isinstance(typed, dict) and typed.get("kind") == "number":
                        return str(typed.get("number"))
        if isinstance(baseline_value, bool) or not isinstance(
            baseline_value,
            (int, float, str),
        ):
            return None
        try:
            return str(Decimal(str(baseline_value)))
        except InvalidOperation:
            return None

    def _series_for_role(
        self,
        projection: CalculationRunOutputsResponse,
        role: str,
    ) -> AnalysisSeriesItem | None:
        output = resolve_analysis_output(
            projection.outputs,
            role,
            entity_kind="series",
        )
        if isinstance(output, CalculationRunScalarOutputItem):
            value = self._number(output.current)
            if value is None:
                return None
            return AnalysisSeriesItem(
                role=role,
                label=output.label,
                unit=output.unit,
                source_type="calculated",
                availability_status="available",
                source_ids=[output.output_id],
                points=[
                    AnalysisSeriesPointItem(
                        period_index=0,
                        period=None,
                        value=value,
                        availability_status="available",
                        validation_status=output.current.validation_status,
                        source_ids=[output.output_id],
                    )
                ],
            )
        if not isinstance(output, CalculationRunSeriesOutputItem):
            return None
        points = [
            AnalysisSeriesPointItem(
                period_index=point.period_index,
                period=point.period,
                value=self._number(point.current),
                availability_status=(
                    "available"
                    if self._number(point.current) is not None
                    else "unavailable"
                ),
                validation_status=point.current.validation_status,
                source_ids=[point.financial_series_value_id],
            )
            for point in output.points
        ]
        available = sum(point.value is not None for point in points)
        status = (
            "unavailable"
            if available == 0
            else "available"
            if available == len(points)
            else "partial"
        )
        return AnalysisSeriesItem(
            role=role,
            label=output.label,
            unit=output.unit,
            source_type="calculated",
            availability_status=status,
            source_ids=[output.output_id],
            points=points,
        )

    def _cumulative_chart(
        self,
        projection: CalculationRunOutputsResponse,
        slot: str,
        title: str,
    ) -> AnalysisChartItem:
        source = self._series_for_role(
            projection,
            "project_free_cash_flow",
        )
        if source is None or source.availability_status == "unavailable":
            return AnalysisChartItem(
                slot=slot,
                title=title,
                availability_status="unavailable",
                source_type="unavailable",
            )
        running = Decimal("0")
        points: list[AnalysisSeriesPointItem] = []
        incomplete = False
        for point in source.points:
            if point.value is None:
                incomplete = True
            if incomplete:
                points.append(
                    AnalysisSeriesPointItem(
                        period_index=point.period_index,
                        period=point.period,
                        value=None,
                        availability_status="unavailable",
                        validation_status=point.validation_status,
                        source_ids=point.source_ids,
                    )
                )
                continue
            running += Decimal(point.value)
            points.append(
                AnalysisSeriesPointItem(
                    period_index=point.period_index,
                    period=point.period,
                    value=str(running),
                    availability_status="available",
                    validation_status=point.validation_status,
                    source_ids=point.source_ids,
                )
            )
        derived = AnalysisSeriesItem(
            role="cumulative_cash_flow",
            label="Cumulative cash flow",
            unit=source.unit,
            source_type="derived",
            availability_status="partial" if incomplete else "available",
            source_ids=source.source_ids,
            points=points,
        )
        return AnalysisChartItem(
            slot=slot,
            title=title,
            availability_status=derived.availability_status,
            source_type="derived",
            series=[derived],
        )

    @staticmethod
    def _chart(
        slot: str,
        title: str,
        series: list[AnalysisSeriesItem],
        *,
        fallback_used: str | None = None,
    ) -> AnalysisChartItem:
        if not series:
            return AnalysisChartItem(
                slot=slot,
                title=title,
                availability_status="unavailable",
                source_type="unavailable",
                fallback_used=fallback_used,
            )
        statuses = {item.availability_status for item in series}
        status = (
            "available"
            if statuses == {"available"}
            else "unavailable"
            if statuses == {"unavailable"}
            else "partial"
        )
        return AnalysisChartItem(
            slot=slot,
            title=title,
            availability_status=status,
            source_type="calculated",
            fallback_used=fallback_used,
            series=series,
        )

    @staticmethod
    def _number(projected: CalculationProjectedValueItem) -> str | None:
        value = projected.value
        if (
            projected.availability_status != "available"
            or value is None
            or value.value_type != "number"
        ):
            return None
        return value.value

    @staticmethod
    def _role_label(role: str, fallback: str) -> str:
        return {
            "project_irr": "Project IRR",
            "equity_irr": "Equity IRR",
            "project_npv": "Project NPV",
            "equity_npv": "Equity NPV",
            "minimum_dscr": "Minimum DSCR",
            "average_dscr": "Average DSCR",
            "payback_period": "Payback period",
            "equity_multiple": "Equity multiple",
            "debt_to_equity_ratio": "Debt / Equity ratio",
        }.get(role, fallback)

    @staticmethod
    def _display_value(role: str, value: str, unit: str | None) -> str:
        number = Decimal(value)
        if role in {
            "project_irr",
            "equity_irr",
            "discount_rate",
            "project_irr_hurdle",
            "equity_irr_hurdle",
        }:
            return f"{number * 100:.1f}%"
        if role in {
            "minimum_dscr",
            "average_dscr",
            "dscr_covenant",
            "equity_multiple",
            "debt_to_equity_ratio",
        }:
            return f"{number:.2f}x"
        if role == "payback_period":
            return f"{number:.1f} yrs"
        suffix = f" {unit}" if unit else ""
        return f"{number.normalize()}{suffix}"

    @staticmethod
    def _comparison_status(
        role: str,
        value: str,
        benchmark: AnalysisBenchmarkItem | None,
    ) -> str:
        if benchmark is None:
            return "not_assessed"
        current = Decimal(value)
        target = Decimal(benchmark.value)
        if role in {
            "project_irr",
            "equity_irr",
            "minimum_dscr",
            "average_dscr",
        }:
            return "above_hurdle" if current >= target else "below_hurdle"
        return "not_assessed"
