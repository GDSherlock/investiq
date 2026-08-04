import type {
  CalculationOutputAvailabilityStatus,
  CalculationOutputMappingStatus,
  CalculationProjectedOutputValue,
  CalculationRunOutputsResponse,
  CalculationTypedValue,
  CalculationSensitivityCase,
  CalculationSensitivityResponse,
} from './calculation-api-types';
import type { PersistedCalculationState } from './calculation-storage';
import type { SensitivityAssumption } from './sensitivity-analysis';

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
  engineErrorCode: string | null;
  validationStatus: string | null;
  warnings: string[];
}

export interface SensitivityDisplayKpi {
  outputId: string | null;
  businessRole: string;
  label: string;
  unit: string | null;
  numberFormat: string | null;
  availabilityStatus: CalculationOutputAvailabilityStatus;
  baseline: SensitivityProjectedValue;
  current: SensitivityProjectedValue;
  absoluteChange: number | null;
  percentageChange: number | null;
}

export interface SensitivityKpi extends SensitivityDisplayKpi {
  outputId: string;
  scenario: string | null;
  mappingStatus: CalculationOutputMappingStatus;
  supportStatus: string;
}

export interface SensitivityDerivedKpi extends SensitivityDisplayKpi {
  outputId: null;
  businessRole: 'equity_multiple';
  sourceIds: string[];
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
  derivedKpis: SensitivityDerivedKpi[];
  series: SensitivitySeries[];
}

export interface EstimatedSensitivityKpis {
  kpis: SensitivityKpi[];
  estimatedOutputIds: string[];
}

export interface EstimateSensitivityKpisInput {
  kpis: readonly SensitivityKpi[];
  analysis: CalculationSensitivityResponse | null;
  assumptions: readonly SensitivityAssumption[];
  analysisOverridesByTarget: Readonly<Record<string, string>>;
  previewOverridesByTarget: Readonly<Record<string, string>>;
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
    engineErrorCode: projected.engine_error_code,
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

function targetKey(
  target:
    | { kind: 'parameter'; parameter_id: string }
    | {
        kind: 'financial_series_value';
        financial_series_value_id: string;
      },
): string {
  return target.kind === 'parameter'
    ? `parameter:${target.parameter_id}`
    : `financial_series_value:${target.financial_series_value_id}`;
}

function caseOutputValue(
  sensitivityCase: CalculationSensitivityCase,
  outputId: string,
  selectedOutputId: string,
): number | null {
  const projected =
    sensitivityCase.outputs?.find(
      (output) => output.output_id === outputId,
    )?.value ??
    (outputId === selectedOutputId
      ? sensitivityCase.output
      : null);
  return projected === null ? null : numericValue(projected);
}

export function estimateSensitivityKpis({
  kpis,
  analysis,
  assumptions,
  analysisOverridesByTarget,
  previewOverridesByTarget,
}: EstimateSensitivityKpisInput): EstimatedSensitivityKpis {
  if (analysis === null) {
    return { kpis: [...kpis], estimatedOutputIds: [] };
  }
  const assumptionByTarget = new Map(
    assumptions.map((assumption) => [
      assumption.targetKey,
      assumption,
    ]),
  );
  const changedTargets = assumptions
    .map((assumption) => assumption.targetKey)
    .filter((key) => {
      const assumption = assumptionByTarget.get(key);
      if (assumption === undefined) {
        return false;
      }
      const anchor = Number(
        analysisOverridesByTarget[key] ?? assumption.currentValue,
      );
      const preview = Number(
        previewOverridesByTarget[key] ?? assumption.currentValue,
      );
      return (
        Number.isFinite(anchor) &&
        Number.isFinite(preview) &&
        anchor !== preview
      );
    });
  if (changedTargets.length === 0) {
    return { kpis: [...kpis], estimatedOutputIds: [] };
  }
  const driverByTarget = new Map(
    analysis.drivers.map((driver) => [
      targetKey(driver.target),
      driver,
    ]),
  );
  if (changedTargets.some((key) => !driverByTarget.has(key))) {
    return { kpis: [...kpis], estimatedOutputIds: [] };
  }
  const currentOutputById = new Map(
    (analysis.current_outputs ?? []).map((output) => [
      output.output_id,
      output.value,
    ]),
  );
  currentOutputById.set(
    analysis.selected_output.output_id,
    analysis.selected_output.current,
  );

  const estimatedOutputIds: string[] = [];
  const estimatedKpis = kpis.map((kpi) => {
    const anchorProjection = currentOutputById.get(kpi.outputId);
    const anchorValue =
      anchorProjection === undefined
        ? null
        : numericValue(anchorProjection);
    if (anchorValue === null) {
      return kpi;
    }
    let estimatedValue = anchorValue;
    for (const key of changedTargets) {
      const assumption = assumptionByTarget.get(key);
      const driver = driverByTarget.get(key);
      if (assumption === undefined || driver === undefined) {
        return kpi;
      }
      const anchorInput = Number(
        analysisOverridesByTarget[key] ?? assumption.currentValue,
      );
      const previewInput = Number(
        previewOverridesByTarget[key] ?? assumption.currentValue,
      );
      const lowInput = Number(driver.low_case.input_value.value);
      const highInput = Number(driver.high_case.input_value.value);
      const lowValue = caseOutputValue(
        driver.low_case,
        kpi.outputId,
        analysis.selected_output.output_id,
      );
      const highValue = caseOutputValue(
        driver.high_case,
        kpi.outputId,
        analysis.selected_output.output_id,
      );
      if (
        lowValue === null ||
        highValue === null ||
        !Number.isFinite(anchorInput) ||
        !Number.isFinite(previewInput)
      ) {
        return kpi;
      }
      const useLowSegment = previewInput <= anchorInput;
      const endpointInput = useLowSegment ? lowInput : highInput;
      const endpointValue = useLowSegment ? lowValue : highValue;
      const denominator = endpointInput - anchorInput;
      if (denominator === 0) {
        return kpi;
      }
      estimatedValue +=
        ((previewInput - anchorInput) / denominator) *
        (endpointValue - anchorValue);
    }
    if (!Number.isFinite(estimatedValue)) {
      return kpi;
    }
    const current = {
      ...kpi.current,
      availabilityStatus: 'available' as const,
      typedValue: {
        value_type: 'number' as const,
        value: String(estimatedValue),
      },
      numericValue: estimatedValue,
      unavailableReason: null,
      executionStatus: 'estimated',
      engineErrorCode: null,
      validationStatus: null,
      warnings: ['estimated_from_sensitivity_endpoints'],
    };
    const next = {
      ...kpi,
      availabilityStatus: 'available' as const,
      current,
      absoluteChange: absoluteChange(kpi.baseline, current),
      percentageChange: percentageChange(kpi.baseline, current),
    };
    estimatedOutputIds.push(kpi.outputId);
    return next;
  });
  return { kpis: estimatedKpis, estimatedOutputIds };
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
  const derivedKpis: SensitivityDerivedKpi[] = (
    response.derived_kpis ?? []
  ).map((item) => {
    const baseline = projectedValue(item.baseline);
    const current = projectedValue(item.current);
    return {
      outputId: null,
      businessRole: item.role,
      label: item.label,
      unit: item.unit,
      numberFormat: '0.00x',
      sourceIds: [...item.source_ids],
      availabilityStatus: item.availability_status,
      baseline,
      current,
      absoluteChange: absoluteChange(baseline, current),
      percentageChange: percentageChange(baseline, current),
    };
  });

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
    derivedKpis,
    series,
  };
}
