import type {
  AnalysisKpi,
  CalculationRunOutputsResponse,
  CalculationSensitivityResponse,
  OverviewAnalysisResponse,
} from './calculation-api-types';
import type {
  SensitivityAssumption,
  SensitivityTornadoRow,
} from './sensitivity-analysis';
import type { SensitivityKpi } from './sensitivity-output-adapter';

export const FIXED_DASHBOARD_SLOT_KEYS = [
  'irr',
  'npv',
  'payback',
  'dscr',
  'equity_multiple',
] as const;

export type FixedDashboardSlotKey =
  (typeof FIXED_DASHBOARD_SLOT_KEYS)[number];

interface FixedDashboardSlotDefinition {
  key: FixedDashboardSlotKey;
  label: string;
  roles: readonly string[];
  sourceLabels: readonly string[];
}

const FIXED_DASHBOARD_SLOT_DEFINITIONS: readonly FixedDashboardSlotDefinition[] = [
  {
    key: 'irr',
    label: 'IRR',
    roles: ['project_irr', 'equity_irr'],
    sourceLabels: ['Project IRR', 'Equity IRR'],
  },
  {
    key: 'npv',
    label: 'NPV',
    roles: ['npv'],
    sourceLabels: ['NPV'],
  },
  {
    key: 'payback',
    label: 'Payback',
    roles: ['payback_period'],
    sourceLabels: ['Payback'],
  },
  {
    key: 'dscr',
    label: 'DSCR',
    roles: ['average_dscr', 'minimum_dscr'],
    sourceLabels: ['Average DSCR', 'Minimum DSCR'],
  },
  {
    key: 'equity_multiple',
    label: 'Equity ×',
    roles: ['equity_multiple'],
    sourceLabels: ['Equity Multiple'],
  },
];

const OVERVIEW_SLOTS_BY_FIXED_SLOT: Readonly<
  Record<FixedDashboardSlotKey, readonly string[]>
> = {
  irr: ['primary_return'],
  npv: ['npv'],
  payback: ['payback_period'],
  dscr: ['average_dscr', 'minimum_dscr'],
  equity_multiple: ['leverage'],
};

export interface FixedDashboardKpiSlot {
  key: FixedDashboardSlotKey;
  label: string;
  displayLabel: string;
  sourceLabel: string | null;
  kpi: SensitivityKpi | null;
  unavailable: boolean;
  unavailableDetail: string | null;
}

export interface FixedDashboardViewModel {
  slots: FixedDashboardKpiSlot[];
  irrOutputId: string | null;
}

export interface FixedDashboardDriverPromotionInput {
  assumptions: readonly SensitivityAssumption[];
  currentDriverKeys: readonly string[];
  changedTargetKey: string;
  impactsByTarget: Readonly<Record<string, number | null | undefined>>;
  maxDrivers?: number;
}

export type FixedDashboardCalculationMode =
  | 'sensitivity'
  | 'calculation';

function isAvailableNumericKpi(kpi: SensitivityKpi): boolean {
  return (
    kpi.current.availabilityStatus === 'available' &&
    kpi.current.numericValue !== null
  );
}

function resolveSlot(
  definition: FixedDashboardSlotDefinition,
  kpis: readonly SensitivityKpi[],
): FixedDashboardKpiSlot {
  let diagnosticCandidate:
    | { kpi: SensitivityKpi; roleIndex: number }
    | null = null;
  for (let index = 0; index < definition.roles.length; index += 1) {
    const role = definition.roles[index];
    const roleCandidates = kpis.filter(
      (candidate) => candidate.businessRole === role,
    );
    const kpi = roleCandidates.find(isAvailableNumericKpi);
    if (kpi !== undefined) {
      const sourceLabel = definition.sourceLabels[index];
      const usesFallback = index > 0;
      return {
        key: definition.key,
        label: definition.label,
        displayLabel: usesFallback
          ? `${definition.label} · ${sourceLabel}`
          : definition.label,
        sourceLabel: usesFallback ? sourceLabel : null,
        kpi,
        unavailable: false,
        unavailableDetail: null,
      };
    }
    if (diagnosticCandidate === null && roleCandidates[0] !== undefined) {
      diagnosticCandidate = {
        kpi: roleCandidates[0],
        roleIndex: index,
      };
    }
  }
  if (diagnosticCandidate !== null) {
    const { kpi, roleIndex } = diagnosticCandidate;
    const sourceLabel = definition.sourceLabels[roleIndex];
    const usesFallback = roleIndex > 0;
    const unavailableDetail = Array.from(
      new Set(
        [
          kpi.current.unavailableReason,
          kpi.current.executionStatus,
          kpi.current.engineErrorCode,
          kpi.current.validationStatus,
          ...kpi.current.warnings,
          kpi.supportStatus === 'supported' ? null : kpi.supportStatus,
        ].filter(
          (detail): detail is string =>
            detail !== null && detail.trim().length > 0,
        ),
      ),
    ).join(' · ');
    return {
      key: definition.key,
      label: definition.label,
      displayLabel: usesFallback
        ? `${definition.label} · ${sourceLabel}`
        : definition.label,
      sourceLabel: usesFallback ? sourceLabel : null,
      kpi,
      unavailable: true,
      unavailableDetail: unavailableDetail || 'Unavailable canonical output',
    };
  }
  return {
    key: definition.key,
    label: definition.label,
    displayLabel: definition.label,
    sourceLabel: null,
    kpi: null,
    unavailable: true,
    unavailableDetail: null,
  };
}

/**
 * Builds the presentation contract for the fixed sensitivity dashboard.
 * The legacy persisted output selection is deliberately ignored: IRR always
 * resolves through the controlled business-role contract.
 */
export function resolveFixedDashboardViewModel(
  kpis: readonly SensitivityKpi[],
  _legacySelectedOutputId: string | null = null,
): FixedDashboardViewModel {
  void _legacySelectedOutputId;
  const slots = FIXED_DASHBOARD_SLOT_DEFINITIONS.map((definition) =>
    resolveSlot(definition, kpis),
  );
  const irrSlot = slots.find((slot) => slot.key === 'irr');
  return {
    slots,
    irrOutputId:
      irrSlot !== undefined && !irrSlot.unavailable
        ? irrSlot.kpi?.outputId ?? null
        : null,
  };
}

/**
 * Aligns only the fixed dashboard's displayed KPI sources with Overview.
 * The calculation-facing IRR output identity remains unchanged.
 */
export function alignDashboardSlotsWithOverview(
  dashboard: FixedDashboardViewModel,
  sensitivityKpis: readonly SensitivityKpi[],
  overviewKpis: readonly AnalysisKpi[],
): FixedDashboardViewModel {
  const sensitivityByOutputId = new Map(
    sensitivityKpis.map((kpi) => [kpi.outputId, kpi]),
  );
  const overviewBySlot = new Map(overviewKpis.map((kpi) => [kpi.slot, kpi]));

  const slots = dashboard.slots.map((slot) => {
    const overviewKpi = OVERVIEW_SLOTS_BY_FIXED_SLOT[slot.key]
      .map((overviewSlot) => overviewBySlot.get(overviewSlot))
      .find((candidate) => candidate?.source_ids[0] !== undefined);
    const sourceOutputId = overviewKpi?.source_ids[0];

    if (sourceOutputId === undefined) {
      return {
        ...slot,
        kpi: null,
        unavailable: true,
        unavailableDetail: 'Unavailable canonical output',
      };
    }

    const selectedKpi = sensitivityByOutputId.get(sourceOutputId);
    if (selectedKpi === undefined) {
      return {
        ...slot,
        kpi: null,
        unavailable: true,
        unavailableDetail:
          'Overview source output is missing from this calculation run',
      };
    }

    if (!isAvailableNumericKpi(selectedKpi)) {
      const unavailableDetail = Array.from(
        new Set(
          [
            selectedKpi.current.unavailableReason,
            selectedKpi.current.executionStatus,
            selectedKpi.current.engineErrorCode,
            selectedKpi.current.validationStatus,
            ...selectedKpi.current.warnings,
            selectedKpi.supportStatus === 'supported'
              ? null
              : selectedKpi.supportStatus,
          ].filter(
            (detail): detail is string =>
              detail !== null && detail.trim().length > 0,
          ),
        ),
      ).join(' · ');
      return {
        ...slot,
        kpi: selectedKpi,
        unavailable: true,
        unavailableDetail: unavailableDetail || 'Unavailable canonical output',
      };
    }

    return {
      ...slot,
      kpi: selectedKpi,
      unavailable: false,
      unavailableDetail: null,
    };
  });

  return {
    slots,
    irrOutputId: dashboard.irrOutputId,
  };
}

export function overviewMatchesSensitivityOutputs(
  overview: OverviewAnalysisResponse,
  outputs: CalculationRunOutputsResponse,
): boolean {
  return (
    overview.calculation_run_id === outputs.calculation_run_id &&
    overview.model_version_id === outputs.model_version_id &&
    overview.graph_version_id === outputs.graph_version_id
  );
}

export function resolveFixedDashboardCalculationMode(
  irrOutputId: string | null,
  driverCount: number,
): FixedDashboardCalculationMode {
  return irrOutputId === null || driverCount === 0
    ? 'calculation'
    : 'sensitivity';
}

export function resolveFixedDashboardAnalysis(
  analysis: CalculationSensitivityResponse | null,
  resolvedIrrOutputId: string | null,
): CalculationSensitivityResponse | null {
  return analysis?.selected_output.output_id === resolvedIrrOutputId
    ? analysis
    : null;
}

export function resolveFixedDashboardTwoWayUnavailableReason(
  analysis: CalculationSensitivityResponse | null,
): string | null {
  if (
    analysis === null ||
    analysis.two_way !== null ||
    !analysis.warnings.includes('TOP_IMPACT_TWO_WAY_UNAVAILABLE')
  ) {
    return null;
  }
  return 'TOP_IMPACT_TWO_WAY_UNAVAILABLE: Fewer than two drivers returned usable IRR impacts, so no two-way matrix was generated.';
}

export function visibleFixedDashboardAssumptions(
  assumptions: readonly SensitivityAssumption[],
  expanded: boolean,
  defaultVisibleCount = 8,
): SensitivityAssumption[] {
  return expanded
    ? [...assumptions]
    : assumptions.slice(0, defaultVisibleCount);
}

export function orderFixedDashboardAssumptions(
  assumptions: readonly SensitivityAssumption[],
  tornadoRows: readonly Pick<SensitivityTornadoRow, 'targetKey' | 'impact'>[] | null,
): SensitivityAssumption[] {
  if (tornadoRows === null) {
    return [...assumptions];
  }
  const impacts = new Map<string, number | null>();
  for (const row of tornadoRows) {
    impacts.set(row.targetKey, row.impact);
  }
  return assumptions
    .map((assumption, index) => ({ assumption, index }))
    .sort((left, right) => {
      const leftImpact = impacts.get(left.assumption.targetKey);
      const rightImpact = impacts.get(right.assumption.targetKey);
      const leftRank = leftImpact === null || leftImpact === undefined ? -1 : leftImpact;
      const rightRank = rightImpact === null || rightImpact === undefined ? -1 : rightImpact;
      return rightRank - leftRank || left.index - right.index;
    })
    .map(({ assumption }) => assumption);
}

function cappedKnownDriverKeys(
  assumptions: readonly SensitivityAssumption[],
  currentDriverKeys: readonly string[],
  maxDrivers: number,
): string[] {
  const known = new Set(assumptions.map((assumption) => assumption.targetKey));
  const uniqueCurrent = Array.from(new Set(currentDriverKeys)).filter((key) =>
    known.has(key),
  );
  return (
    uniqueCurrent.length > 0
      ? uniqueCurrent.slice(0, maxDrivers)
      : assumptions.slice(0, maxDrivers).map((assumption) => assumption.targetKey)
  );
}

export function promoteFixedDashboardDriver({
  assumptions,
  currentDriverKeys,
  changedTargetKey,
  impactsByTarget,
  maxDrivers = 12,
}: FixedDashboardDriverPromotionInput): string[] {
  const max = Math.min(Math.max(maxDrivers, 0), 12);
  if (max === 0 || !assumptions.some((assumption) => assumption.targetKey === changedTargetKey)) {
    return [];
  }
  const drivers = cappedKnownDriverKeys(assumptions, currentDriverKeys, max);
  if (drivers.includes(changedTargetKey)) {
    return drivers;
  }
  if (drivers.length < max) {
    return [...drivers, changedTargetKey];
  }

  const impactCandidates = drivers
    .map((targetKey, index) => ({
      targetKey,
      index,
      impact: impactsByTarget[targetKey],
    }))
    .filter(
      (candidate): candidate is { targetKey: string; index: number; impact: number } =>
        typeof candidate.impact === 'number' && Number.isFinite(candidate.impact),
    );
  const evictionIndex =
    impactCandidates.length > 0
      ? impactCandidates.reduce((lowest, candidate) =>
          candidate.impact < lowest.impact ? candidate : lowest,
        ).index
      : drivers.length - 1;
  return drivers
    .filter((_targetKey, index) => index !== evictionIndex)
    .concat(changedTargetKey);
}
