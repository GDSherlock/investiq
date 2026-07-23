import type {
  CalculationOutputAvailabilityStatus,
  CalculationOutputMappingStatus,
  CalculationProjectedOutputValue,
  CalculationRunOutputsResponse,
  CalculationTypedValue,
} from './calculation-api-types';
import type { PersistedCalculationState } from './calculation-storage';

const KPI_ROLE_ORDER = [
  'project_irr',
  'equity_irr',
  'npv',
  'minimum_dscr',
  'average_dscr',
  'payback_period',
  'equity_multiple',
  'total_project_cost',
  'total_capex',
  'total_debt',
  'peak_debt',
  'average_ebitda_margin',
] as const;

const SERIES_ROLE_ORDER = [
  'revenue',
  'opex',
  'fixed_opex',
  'variable_opex',
  'ebitda',
  'cfads',
  'cash_flow',
  'equity_cash_flow',
  'debt_service',
  'debt_balance',
  'opening_debt',
  'closing_debt',
  'principal_repayment',
  'interest_expense',
  'tax',
  'net_generation',
  'power_price',
] as const;

const kpiRoleRank = new Map(
  KPI_ROLE_ORDER.map((role, index) => [role, index]),
);
const seriesRoleRank = new Map(
  SERIES_ROLE_ORDER.map((role, index) => [role, index]),
);

export interface SensitivityProjectedValue {
  availabilityStatus: 'available' | 'unavailable';
  typedValue: CalculationTypedValue | null;
  numericValue: number | null;
  unavailableReason: string | null;
  executionStatus: string | null;
  validationStatus: string | null;
  warnings: string[];
}

export interface SensitivityKpi {
  outputId: string;
  businessRole: string;
  label: string;
  unit: string | null;
  scenario: string | null;
  mappingStatus: CalculationOutputMappingStatus;
  supportStatus: string;
  numberFormat: string | null;
  availabilityStatus: CalculationOutputAvailabilityStatus;
  baseline: SensitivityProjectedValue;
  current: SensitivityProjectedValue;
  absoluteChange: number | null;
  percentageChange: number | null;
}

export interface SensitivitySeriesPoint {
  financialSeriesValueId: string;
  periodIndex: number;
  period: string | null;
  mappingStatus: Exclude<CalculationOutputMappingStatus, 'partial'>;
  supportStatus: string;
  numberFormat: string | null;
  availabilityStatus: CalculationOutputAvailabilityStatus;
  baseline: SensitivityProjectedValue;
  current: SensitivityProjectedValue;
  absoluteChange: number | null;
}

export interface SensitivitySeries {
  outputId: string;
  businessRole: string;
  label: string;
  unit: string | null;
  scenario: string | null;
  mappingStatus: CalculationOutputMappingStatus;
  supportStatus: string;
  availabilityStatus: CalculationOutputAvailabilityStatus;
  points: SensitivitySeriesPoint[];
  changedPointCount: number;
  maxAbsoluteChange: number | null;
  unavailableBaselinePointCount: number;
  unavailableBaselineReasons: string[];
  unavailableCurrentPointCount: number;
  unavailableCurrentReasons: string[];
}

export interface SensitivityOutputView {
  calculationRunId: string;
  modelVersionId: string;
  graphVersionId: string;
  baseRunId: string | null;
  comparisonBaselineRunId: string;
  hasOverride: boolean;
  kpis: SensitivityKpi[];
  series: SensitivitySeries[];
}

function numericValue(
  projected: CalculationProjectedOutputValue,
): number | null {
  if (
    projected.availability_status !== 'available' ||
    projected.value?.value_type !== 'number'
  ) {
    return null;
  }
  const parsed = Number(projected.value.value);
  return Number.isFinite(parsed) ? parsed : null;
}

function projectedValue(
  projected: CalculationProjectedOutputValue,
): SensitivityProjectedValue {
  return {
    availabilityStatus: projected.availability_status,
    typedValue: projected.value,
    numericValue: numericValue(projected),
    unavailableReason: projected.unavailable_reason,
    executionStatus: projected.execution_status,
    validationStatus: projected.validation_status,
    warnings: [...projected.warnings],
  };
}

function absoluteChange(
  baseline: SensitivityProjectedValue,
  current: SensitivityProjectedValue,
): number | null {
  if (baseline.numericValue === null || current.numericValue === null) {
    return null;
  }
  return current.numericValue - baseline.numericValue;
}

function percentageChange(
  baseline: SensitivityProjectedValue,
  current: SensitivityProjectedValue,
): number | null {
  const delta = absoluteChange(baseline, current);
  if (
    delta === null ||
    baseline.numericValue === null ||
    baseline.numericValue === 0
  ) {
    return null;
  }
  return (delta / Math.abs(baseline.numericValue)) * 100;
}

function semanticSort(
  left: { businessRole: string; label: string; outputId: string },
  right: { businessRole: string; label: string; outputId: string },
  rank: Map<string, number>,
): number {
  const leftRank = rank.get(left.businessRole) ?? Number.MAX_SAFE_INTEGER;
  const rightRank = rank.get(right.businessRole) ?? Number.MAX_SAFE_INTEGER;
  return (
    leftRank - rightRank ||
    left.label.localeCompare(right.label) ||
    left.outputId.localeCompare(right.outputId)
  );
}

export function selectSensitivityRunId(
  state: PersistedCalculationState,
): string | null {
  return state.overrideRunId ?? state.baselineRunId;
}

export function buildSensitivityOutputView(
  response: CalculationRunOutputsResponse,
): SensitivityOutputView {
  const kpis: SensitivityKpi[] = [];
  const series: SensitivitySeries[] = [];

  for (const output of response.outputs) {
    if (output.entity_kind === 'scalar') {
      const baseline = projectedValue(output.baseline);
      const current = projectedValue(output.current);
      kpis.push({
        outputId: output.output_id,
        businessRole: output.business_role,
        label: output.label,
        unit: output.unit,
        scenario: output.scenario,
        mappingStatus: output.mapping_status,
        supportStatus: output.support_status,
        numberFormat: output.number_format,
        availabilityStatus: output.availability_status,
        baseline,
        current,
        absoluteChange: absoluteChange(baseline, current),
        percentageChange: percentageChange(baseline, current),
      });
      continue;
    }

    const points: SensitivitySeriesPoint[] = output.points
      .map((point) => {
        const baseline = projectedValue(point.baseline);
        const current = projectedValue(point.current);
        return {
          financialSeriesValueId: point.financial_series_value_id,
          periodIndex: point.period_index,
          period: point.period,
          mappingStatus: point.mapping_status,
          supportStatus: point.support_status,
          numberFormat: point.number_format,
          availabilityStatus: point.availability_status,
          baseline,
          current,
          absoluteChange: absoluteChange(baseline, current),
        };
      })
      .sort(
        (left, right) =>
          left.periodIndex - right.periodIndex ||
          left.financialSeriesValueId.localeCompare(
            right.financialSeriesValueId,
          ),
      );
    const changes = points
      .map((point) => point.absoluteChange)
      .filter((change): change is number => change !== null && change !== 0);
    const unavailableBaselinePoints = points.filter(
      (point) => point.baseline.availabilityStatus === 'unavailable',
    );
    const unavailableBaselineReasons = Array.from(
      new Set(
        unavailableBaselinePoints.map(
          (point) =>
            point.baseline.unavailableReason ??
            point.baseline.executionStatus ??
            point.supportStatus,
        ),
      ),
    ).sort();
    const unavailableCurrentPoints = points.filter(
      (point) => point.current.availabilityStatus === 'unavailable',
    );
    const unavailableCurrentReasons = Array.from(
      new Set(
        unavailableCurrentPoints.map(
          (point) =>
            point.current.unavailableReason ??
            point.current.executionStatus ??
            point.supportStatus,
        ),
      ),
    ).sort();
    series.push({
      outputId: output.output_id,
      businessRole: output.business_role,
      label: output.label,
      unit: output.unit,
      scenario: output.scenario,
      mappingStatus: output.mapping_status,
      supportStatus: output.support_status,
      availabilityStatus: output.availability_status,
      points,
      changedPointCount: changes.length,
      maxAbsoluteChange:
        changes.length > 0
          ? Math.max(...changes.map((change) => Math.abs(change)))
          : null,
      unavailableBaselinePointCount: unavailableBaselinePoints.length,
      unavailableBaselineReasons,
      unavailableCurrentPointCount: unavailableCurrentPoints.length,
      unavailableCurrentReasons,
    });
  }

  kpis.sort((left, right) => semanticSort(left, right, kpiRoleRank));
  series.sort((left, right) => semanticSort(left, right, seriesRoleRank));

  return {
    calculationRunId: response.calculation_run_id,
    modelVersionId: response.model_version_id,
    graphVersionId: response.graph_version_id,
    baseRunId: response.base_run_id,
    comparisonBaselineRunId: response.comparison_baseline_run_id,
    hasOverride:
      response.calculation_run_id !==
      response.comparison_baseline_run_id,
    kpis,
    series,
  };
}
