"""Canonical persisted read models for the Overview and Cash Flow pages."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analysis_output_resolver import (
    normalized_analysis_label,
    resolve_analysis_output,
    resolve_analysis_parameter,
)
from .calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from .calculation_rules.phase2_models import CalculationRunRecord
from .model_extraction_models import (
    FinancialSeries,
    FinancialSeriesValue,
    ModelParameter,
    ModelSemanticBinding,
    ModelVersion,
)
from .semantic_binding_service import rank_financial_series_binding
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


def _row_dict(row: Any) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
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
        kpis.append(self._derived_equity_multiple_kpi(projection))
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

        capital = self._capital_structure_chart(projection)

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
            output = self._resolve_projected_output(
                projection,
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

    def _derived_equity_multiple_kpi(
        self,
        projection: CalculationRunOutputsResponse,
    ) -> AnalysisKpiItem:
        derived = next(
            (
                item
                for item in projection.derived_kpis
                if item.role == "equity_multiple"
            ),
            None,
        )
        if derived is not None:
            value = self._number(derived.current)
            if value is not None:
                return AnalysisKpiItem(
                    slot="leverage",
                    role="equity_multiple",
                    label="Equity ×",
                    value=value,
                    unit="x",
                    display_value=self._display_value(
                        "equity_multiple",
                        value,
                        "x",
                    ),
                    benchmark=None,
                    status="not_assessed",
                    source_type="derived",
                    availability_status="available",
                    quality_status=(
                        derived.current.validation_status or "derived"
                    ),
                    validation_status=derived.current.validation_status,
                    calculation_run_id=projection.calculation_run_id,
                    source_ids=derived.source_ids,
                )
        unavailable_reason = (
            derived.current.unavailable_reason
            if derived is not None
            else "EQUITY_CASH_FLOW_NOT_FOUND"
        )
        return AnalysisKpiItem(
            slot="leverage",
            role="equity_multiple",
            label="Equity ×",
            value=None,
            unit="x",
            display_value="Unavailable",
            benchmark=None,
            status="unavailable",
            source_type="unavailable",
            availability_status="unavailable",
            quality_status=unavailable_reason or "unavailable",
            validation_status=(
                derived.current.validation_status
                if derived is not None
                else None
            ),
            calculation_run_id=projection.calculation_run_id,
            source_ids=derived.source_ids if derived is not None else [],
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
        return resolve_analysis_parameter(parameters, role)

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
        output = self._resolve_projected_output(
            projection,
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

    def _resolve_projected_output(
        self,
        projection: CalculationRunOutputsResponse,
        role: str,
        *,
        entity_kind: str,
    ) -> CalculationRunScalarOutputItem | CalculationRunSeriesOutputItem | None:
        binding = self._session.scalar(
            select(ModelSemanticBinding).where(
                ModelSemanticBinding.model_version_id == projection.model_version_id,
                ModelSemanticBinding.semantic_role == role,
            )
        )
        if binding is None:
            if role == "capex" and entity_kind == "series":
                return self._ranked_capex_output(projection)
            return resolve_analysis_output(
                projection.outputs,
                role,
                entity_kind=entity_kind,
            )

        bound_output_id = (
            binding.canonical_output_id or binding.financial_series_id
        )
        if bound_output_id is None:
            return None
        output = next(
            (
                item
                for item in projection.outputs
                if item.output_id == bound_output_id
            ),
            None,
        )
        if entity_kind == "scalar":
            return output if isinstance(output, CalculationRunScalarOutputItem) else None
        return output

    def _ranked_capex_output(
        self,
        projection: CalculationRunOutputsResponse,
    ) -> CalculationRunSeriesOutputItem | None:
        series_rows = list(
            self._session.scalars(
                select(FinancialSeries)
                .where(
                    FinancialSeries.model_version_id
                    == projection.model_version_id,
                    FinancialSeries.business_role.in_(
                        ("capex", "total_capex")
                    ),
                )
                .order_by(FinancialSeries.id)
            )
        )
        series_ids = [series.id for series in series_rows]
        value_rows = (
            list(
                self._session.scalars(
                    select(FinancialSeriesValue)
                    .where(
                        FinancialSeriesValue.financial_series_id.in_(
                            series_ids
                        )
                    )
                    .order_by(
                        FinancialSeriesValue.financial_series_id,
                        FinancialSeriesValue.period_index,
                    )
                )
            )
            if series_ids
            else []
        )
        ranked = rank_financial_series_binding(
            projection.model_version_id,
            "capex",
            financial_series=[_row_dict(row) for row in series_rows],
            financial_series_values=[_row_dict(row) for row in value_rows],
        )
        selected_id = ranked.get("financial_series_id") if ranked else None
        output = next(
            (
                item
                for item in projection.outputs
                if item.output_id == selected_id
            ),
            None,
        )
        return (
            output
            if isinstance(output, CalculationRunSeriesOutputItem)
            else None
        )

    def _capital_structure_chart(
        self,
        projection: CalculationRunOutputsResponse,
    ) -> AnalysisChartItem:
        debt_share = self._parameter_for_role(
            projection.model_version_id,
            "debt_ratio",
        )
        if debt_share is not None:
            value = self._current_parameter_value(
                projection.calculation_run_id,
                debt_share.id,
                debt_share.validated_value_json,
            )
            ratio = self._finite_decimal(value)
            if ratio is None or ratio < 0 or ratio > 1:
                return self._capital_unavailable("CAPITAL_DEBT_SHARE_INVALID")
            return self._capital_ratio_chart(
                ratio,
                [debt_share.id],
                "model_debt_share",
            )

        debt_output = self._resolve_projected_output(
            projection,
            "total_debt",
            entity_kind="scalar",
        )
        if not isinstance(debt_output, CalculationRunScalarOutputItem):
            return self._capital_unavailable("CAPITAL_DEBT_NOT_FOUND")
        debt = self._finite_decimal(self._number(debt_output.current))
        if debt is None:
            return self._capital_unavailable("CAPITAL_DEBT_NOT_FOUND")

        cost_candidates = [
            output
            for output in projection.outputs
            if isinstance(output, CalculationRunScalarOutputItem)
            and output.business_role == "total_project_cost"
            and normalized_analysis_label(output.label)
            in {"total project cost", "total funding requirement"}
        ]
        if not cost_candidates:
            return self._capital_unavailable("CAPITAL_PROJECT_COST_NOT_FOUND")
        resolved_costs = [
            (
                output,
                self._finite_decimal(self._number(output.current)),
                self._normalized_unit(output.unit),
            )
            for output in cost_candidates
        ]
        if any(value is None for _output, value, _unit in resolved_costs):
            return self._capital_unavailable(
                "CAPITAL_PROJECT_COST_AMBIGUOUS"
                if len(resolved_costs) > 1
                else "CAPITAL_PROJECT_COST_NOT_FOUND"
            )
        cost_values = {
            value
            for _output, value, _unit in resolved_costs
            if value is not None
        }
        cost_units = {
            unit
            for _output, _value, unit in resolved_costs
            if unit
        }
        if len(cost_values) != 1 or len(cost_units) > 1:
            return self._capital_unavailable("CAPITAL_PROJECT_COST_AMBIGUOUS")
        cost = next(iter(cost_values))
        cost_unit = next(iter(cost_units), "")
        debt_unit = self._normalized_unit(debt_output.unit)
        if debt_unit and cost_unit and debt_unit != cost_unit:
            return self._capital_unavailable("CAPITAL_UNIT_MISMATCH")
        if cost <= 0 or debt < 0 or debt > cost:
            return self._capital_unavailable("CAPITAL_RATIO_OUT_OF_RANGE")
        return self._capital_ratio_chart(
            debt / cost,
            [debt_output.output_id]
            + [output.output_id for output, _value, _unit in resolved_costs],
            "debt_over_total_project_cost",
        )

    @staticmethod
    def _finite_decimal(value: str | None) -> Decimal | None:
        if value is None:
            return None
        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError):
            return None
        return number if number.is_finite() else None

    @staticmethod
    def _normalized_unit(unit: str | None) -> str:
        return " ".join((unit or "").casefold().split())

    @staticmethod
    def _capital_unavailable(reason: str) -> AnalysisChartItem:
        return AnalysisChartItem(
            slot="capital_structure",
            title="Capital structure",
            availability_status="unavailable",
            source_type="unavailable",
            unavailable_reason=reason,
        )

    @staticmethod
    def _capital_ratio_chart(
        debt_ratio: Decimal,
        source_ids: list[str],
        fallback_used: str,
    ) -> AnalysisChartItem:
        ratios = (
            ("debt_ratio", "Debt", debt_ratio),
            ("equity_ratio", "Equity", Decimal("1") - debt_ratio),
        )
        series = [
            AnalysisSeriesItem(
                role=role,
                label=label,
                unit="%",
                source_type="derived",
                availability_status="available",
                source_ids=source_ids,
                points=[
                    AnalysisSeriesPointItem(
                        period_index=0,
                        period="Capital structure",
                        value=str(value),
                        availability_status="available",
                        validation_status="derived",
                        source_ids=source_ids,
                    )
                ],
            )
            for role, label, value in ratios
        ]
        return AnalysisChartItem(
            slot="capital_structure",
            title="Capital structure",
            availability_status="available",
            source_type="derived",
            fallback_used=fallback_used,
            series=series,
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
