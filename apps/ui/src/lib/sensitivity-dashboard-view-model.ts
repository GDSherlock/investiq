import type { SensitivityAssumption, SensitivityTornadoRow } from './sensitivity-analysis';
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

export interface FixedDashboardKpiSlot {
  key: FixedDashboardSlotKey;
  label: string;
  displayLabel: string;
  sourceLabel: string | null;
  kpi: SensitivityKpi | null;
  unavailable: boolean;
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
  for (let index = 0; index < definition.roles.length; index += 1) {
    const role = definition.roles[index];
    const kpi = kpis.find(
      (candidate) =>
        candidate.businessRole === role && isAvailableNumericKpi(candidate),
    );
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
      };
    }
  }
  return {
    key: definition.key,
    label: definition.label,
    displayLabel: definition.label,
    sourceLabel: null,
    kpi: null,
    unavailable: true,
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
  return {
    slots,
    irrOutputId:
      slots.find((slot) => slot.key === 'irr')?.kpi?.outputId ?? null,
  };
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
