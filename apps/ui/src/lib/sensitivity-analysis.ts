import {
  getCalculationInputs,
  getCalculationRunOutputs,
} from './api';
import type {
  CalculationNumberValue,
  CalculationOverrideTarget,
  CalculationProjectedOutputValue,
  CalculationRunOutputsResponse,
  CalculationSensitivityRequest,
  CalculationSensitivityResponse,
} from './calculation-api-types';
import {
  CALCULATION_STORAGE_KEYS,
  type PersistedCalculationState,
  type StorageLike,
} from './calculation-storage';
import type { SensitivityKpi } from './sensitivity-output-adapter';

interface ParsedDecimal {
  sign: -1 | 0 | 1;
  digits: string;
  scale: number;
}

export interface SensitivityAssumption {
  targetKey: string;
  target: CalculationOverrideTarget;
  label: string;
  category: string | null;
  unit: string | null;
  scenario: string | null;
  period: string | null;
  currentValue: string;
}

export interface SensitivityRequestBuildInput {
  graphVersionId: string;
  outputId: string;
  assumptions: SensitivityAssumption[];
  overridesByTarget: Record<string, string>;
  tornadoDriverKeys: string[];
  rowDriverKey: string | null;
  columnDriverKey: string | null;
}

export interface SensitivityTornadoRow {
  targetKey: string;
  label: string;
  unit: string | null;
  lowInputValue: string;
  highInputValue: string;
  lowValue: number | null;
  currentValue: number | null;
  highValue: number | null;
  lowDelta: number | null;
  highDelta: number | null;
  impact: number | null;
  lowRunId: string;
  highRunId: string;
  unavailableReason: string | null;
  warnings: string[];
}

export interface SensitivityMatrixCell {
  rowValue: string;
  columnValue: string;
  calculationRunId: string | null;
  numericValue: number | null;
  unavailableReason: string | null;
  warnings: string[];
}

export interface SensitivityMatrixRow {
  value: string;
  cells: SensitivityMatrixCell[];
}

export interface SensitivityMatrixView {
  rowTargetKey: string;
  columnTargetKey: string;
  rowLabel: string;
  columnLabel: string;
  rowValues: string[];
  columnValues: string[];
  rows: SensitivityMatrixRow[];
}

export interface SensitivityResponseGuard {
  requestRevision: number;
  currentRevision: number;
  modelVersionId: string;
  graphVersionId: string;
  outputId: string;
}

export interface SensitivityIdentity {
  modelVersionId: string;
  graphVersionId: string;
}

export interface SensitivitySelectionInput {
  assumptions: SensitivityAssumption[];
  overridesByTarget: Record<string, string>;
  storedTornadoDriverKeys: string[] | null;
  storedRowDriverKey: string | null;
  storedColumnDriverKey: string | null;
  maxDrivers: number;
}

export class SensitivityCatalogIdentityError extends Error {
  readonly identityKind: 'model' | 'graph';

  constructor(identityKind: 'model' | 'graph') {
    super(
      `Calculation input page does not match the requested ${identityKind}.`,
    );
    this.name = 'SensitivityCatalogIdentityError';
    this.identityKind = identityKind;
  }
}

export function isSensitivityCatalogIdentityError(
  error: unknown,
): error is SensitivityCatalogIdentityError {
  return error instanceof SensitivityCatalogIdentityError;
}

function parseDecimal(value: string): ParsedDecimal | null {
  const normalized = value.trim();
  if (!Number.isFinite(Number(normalized))) {
    return null;
  }
  const match = normalized
    .match(/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);
  if (match === null) {
    return null;
  }
  const fraction = match[3] ?? '';
  const exponent = Number(match[4] ?? '0');
  if (!Number.isSafeInteger(exponent)) {
    return null;
  }

  let digits = `${match[2]}${fraction}`.replace(/^0+/, '') || '0';
  let scale = fraction.length - exponent;
  if (scale < 0) {
    digits += '0'.repeat(-scale);
    scale = 0;
  }
  while (
    digits !== '0' &&
    scale > 0 &&
    digits.endsWith('0')
  ) {
    digits = digits.slice(0, -1);
    scale -= 1;
  }
  if (digits === '0') {
    return { sign: 0, digits, scale: 0 };
  }
  return {
    sign: match[1] === '-' ? -1 : 1,
    digits,
    scale,
  };
}

function formatDecimal(decimal: ParsedDecimal): string {
  if (decimal.sign === 0 || decimal.digits === '0') {
    return '0';
  }
  if (decimal.scale === 0) {
    return `${decimal.sign < 0 ? '-' : ''}${decimal.digits}`;
  }
  const padded = decimal.digits.padStart(decimal.scale + 1, '0');
  const whole = padded.slice(0, -decimal.scale);
  const fraction = padded.slice(-decimal.scale);
  return `${decimal.sign < 0 ? '-' : ''}${whole}.${fraction}`;
}

function multiplyDigits(digits: string, multiplier: number): string {
  let carry = 0;
  let result = '';
  for (let index = digits.length - 1; index >= 0; index -= 1) {
    const product = Number(digits[index]) * multiplier + carry;
    result = `${product % 10}${result}`;
    carry = Math.floor(product / 10);
  }
  while (carry > 0) {
    result = `${carry % 10}${result}`;
    carry = Math.floor(carry / 10);
  }
  return result.replace(/^0+/, '') || '0';
}

function divideDigits(
  digits: string,
  divisor: number,
): { quotient: string; remainder: number } {
  let remainder = 0;
  let quotient = '';
  for (const digit of digits) {
    const value = remainder * 10 + Number(digit);
    quotient += String(Math.floor(value / divisor));
    remainder = value % divisor;
  }
  return {
    quotient: quotient.replace(/^0+/, '') || '0',
    remainder,
  };
}

function multiplyDecimal(
  value: string,
  numerator: number,
  denominator: number,
): string {
  const parsed = parseDecimal(value);
  if (
    parsed === null ||
    !Number.isSafeInteger(numerator) ||
    !Number.isSafeInteger(denominator) ||
    numerator < 0 ||
    denominator <= 0
  ) {
    throw new Error('Sensitivity values must be finite numeric strings.');
  }
  let digits = multiplyDigits(parsed.digits, numerator);
  let scale = parsed.scale;
  let division = divideDigits(digits, denominator);
  while (division.remainder !== 0) {
    digits += '0';
    scale += 1;
    division = divideDigits(digits, denominator);
  }
  return formatDecimal({
    sign: parsed.sign,
    digits: division.quotient,
    scale,
  });
}

function decimalEquals(left: string, right: string): boolean {
  const leftDecimal = parseDecimal(left);
  const rightDecimal = parseDecimal(right);
  if (leftDecimal === null || rightDecimal === null) {
    return false;
  }
  const scale = Math.max(leftDecimal.scale, rightDecimal.scale);
  return (
    leftDecimal.sign === rightDecimal.sign &&
    leftDecimal.digits.padEnd(
      leftDecimal.digits.length + scale - leftDecimal.scale,
      '0',
    ) ===
      rightDecimal.digits.padEnd(
        rightDecimal.digits.length + scale - rightDecimal.scale,
        '0',
      )
  );
}

function numberValue(value: string): CalculationNumberValue {
  const normalized = value.trim();
  if (parseDecimal(normalized) === null) {
    throw new Error('Sensitivity values must be finite numeric strings.');
  }
  return { value_type: 'number', value: normalized };
}

export function sensitivityTargetKey(
  target: CalculationOverrideTarget,
): string {
  return target.kind === 'parameter'
    ? `parameter:${target.parameter_id}`
    : `financial_series_value:${target.financial_series_value_id}`;
}

function numericProjection(
  projection: CalculationProjectedOutputValue,
): number | null {
  if (
    projection.availability_status !== 'available' ||
    projection.value?.value_type !== 'number'
  ) {
    return null;
  }
  const numericValue = Number(projection.value.value);
  return Number.isFinite(numericValue) ? numericValue : null;
}

function projectionUnavailableReason(
  projection: CalculationProjectedOutputValue,
): string | null {
  return projection.availability_status === 'unavailable'
    ? projection.unavailable_reason ??
        projection.engine_error_code ??
        projection.execution_status ??
        'Unavailable'
    : null;
}

export async function loadAllEditableNumericParameters(
  modelVersionId: string,
  getInputs: typeof getCalculationInputs = getCalculationInputs,
  expectedGraphVersionId?: string,
): Promise<SensitivityAssumption[]> {
  const assumptions: SensitivityAssumption[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | undefined;

  while (true) {
    const page = await getInputs(modelVersionId, {
      targetKind: 'parameter',
      editableOnly: true,
      limit: 100,
      ...(cursor === undefined ? {} : { cursor }),
    });
    if (page.model_version_id !== modelVersionId) {
      throw new SensitivityCatalogIdentityError('model');
    }
    if (
      expectedGraphVersionId !== undefined &&
      page.graph_version_id !== expectedGraphVersionId
    ) {
      throw new SensitivityCatalogIdentityError('graph');
    }
    for (const input of page.inputs) {
      if (
        input.target_kind !== 'parameter' ||
        input.editable !== true ||
        input.current_value.value_type !== 'number'
      ) {
        continue;
      }
      const target: CalculationOverrideTarget = {
        kind: 'parameter',
        parameter_id: input.target_id,
      };
      assumptions.push({
        targetKey: sensitivityTargetKey(target),
        target,
        label: input.label,
        category: input.category,
        unit: input.unit,
        scenario: input.scenario,
        period: input.period,
        currentValue: input.current_value.value,
      });
    }
    if (page.next_cursor === null) {
      break;
    }
    if (seenCursors.has(page.next_cursor)) {
      throw new Error('Calculation input pagination returned a repeated cursor.');
    }
    seenCursors.add(page.next_cursor);
    cursor = page.next_cursor;
  }

  assumptions.sort(
    (left, right) =>
      (left.category ?? '').localeCompare(right.category ?? '') ||
      left.label.localeCompare(right.label) ||
      left.targetKey.localeCompare(right.targetKey),
  );
  return assumptions;
}

export function deriveSliderSpec(
  decimalValue: string,
):
  | { kind: 'range'; min: string; max: string; step: string }
  | { kind: 'number' } {
  const parsed = parseDecimal(decimalValue);
  if (parsed === null) {
    throw new Error('Sensitivity values must be finite numeric strings.');
  }
  if (parsed.sign === 0) {
    return { kind: 'number' };
  }
  const lowerFactor = parsed.sign < 0 ? 6 : 4;
  const upperFactor = parsed.sign < 0 ? 4 : 6;
  const absoluteValue = formatDecimal({
    sign: 1,
    digits: parsed.digits,
    scale: parsed.scale,
  });
  return {
    kind: 'range',
    min: multiplyDecimal(decimalValue, lowerFactor, 5),
    max: multiplyDecimal(decimalValue, upperFactor, 5),
    step: multiplyDecimal(absoluteValue, 1, 250),
  };
}

function scaledDecimalInteger(
  decimal: ParsedDecimal,
  scale: number,
): bigint {
  const unsigned = BigInt(
    decimal.digits.padEnd(
      decimal.digits.length + scale - decimal.scale,
      '0',
    ),
  );
  return decimal.sign < 0 ? -unsigned : unsigned;
}

function absoluteBigInt(value: bigint): bigint {
  return value < BigInt(0) ? -value : value;
}

function greatestCommonDivisor(
  left: bigint,
  right: bigint,
): bigint {
  let dividend = absoluteBigInt(left);
  let divisor = absoluteBigInt(right);
  while (divisor !== BigInt(0)) {
    const remainder = dividend % divisor;
    dividend = divisor;
    divisor = remainder;
  }
  return dividend;
}

export function deriveSliderControlStep(
  slider: { min: string; max: string; step: string },
  decimalValue: string,
): string | null {
  const minimum = parseDecimal(slider.min);
  const maximum = parseDecimal(slider.max);
  const suggestedStep = parseDecimal(slider.step);
  const value = parseDecimal(decimalValue);
  if (
    minimum === null ||
    maximum === null ||
    suggestedStep === null ||
    suggestedStep.sign === 0 ||
    value === null
  ) {
    throw new Error('Sensitivity values must be finite numeric strings.');
  }

  const scale = Math.max(
    minimum.scale,
    maximum.scale,
    suggestedStep.scale,
    value.scale,
  );
  const minimumInteger = scaledDecimalInteger(minimum, scale);
  const maximumInteger = scaledDecimalInteger(maximum, scale);
  const valueInteger = scaledDecimalInteger(value, scale);
  if (
    valueInteger < minimumInteger ||
    valueInteger > maximumInteger
  ) {
    return null;
  }
  const suggestedStepInteger = absoluteBigInt(
    scaledDecimalInteger(suggestedStep, scale),
  );
  const offset = absoluteBigInt(valueInteger - minimumInteger);
  const exactStepInteger =
    offset === BigInt(0)
      ? suggestedStepInteger
      : greatestCommonDivisor(suggestedStepInteger, offset);
  if (
    suggestedStepInteger / exactStepInteger >
    BigInt(10_000)
  ) {
    return null;
  }
  const exactStep = parseDecimal(
    formatDecimal({
      sign: 1,
      digits: exactStepInteger.toString(),
      scale,
    }),
  );
  if (exactStep === null || exactStep.sign === 0) {
    throw new Error('Sensitivity slider step must be positive.');
  }
  return formatDecimal(exactStep);
}

export function resolveSensitivitySelections({
  assumptions,
  overridesByTarget,
  storedTornadoDriverKeys,
  storedRowDriverKey,
  storedColumnDriverKey,
  maxDrivers,
}: SensitivitySelectionInput): {
  tornadoDriverKeys: string[];
  rowDriverKey: string | null;
  columnDriverKey: string | null;
} {
  const rangeCapableKeys = assumptions
    .filter(
      (assumption) =>
        deriveSliderSpec(
          currentAssumptionValue(assumption, overridesByTarget),
        ).kind === 'range',
    )
    .map((assumption) => assumption.targetKey);
  const rangeCapable = new Set(rangeCapableKeys);
  const storedDriversValid =
    storedTornadoDriverKeys !== null &&
    storedTornadoDriverKeys.length > 0 &&
    storedTornadoDriverKeys.length <= maxDrivers &&
    new Set(storedTornadoDriverKeys).size ===
      storedTornadoDriverKeys.length &&
    storedTornadoDriverKeys.every((targetKey) =>
      rangeCapable.has(targetKey),
    );
  const tornadoDriverKeys = (
    storedDriversValid
      ? storedTornadoDriverKeys
      : rangeCapableKeys.slice(0, maxDrivers)
  ).slice(0, maxDrivers);

  const rowDriverKey =
    storedRowDriverKey !== null && rangeCapable.has(storedRowDriverKey)
      ? storedRowDriverKey
      : rangeCapableKeys[0] ?? null;
  const columnDriverKey =
    storedColumnDriverKey !== null &&
    storedColumnDriverKey !== rowDriverKey &&
    rangeCapable.has(storedColumnDriverKey)
      ? storedColumnDriverKey
      : rangeCapableKeys.find(
          (targetKey) => targetKey !== rowDriverKey,
        ) ?? null;

  return { tornadoDriverKeys, rowDriverKey, columnDriverKey };
}

export function retainEligibleSensitivityDrivers(
  assumptions: SensitivityAssumption[],
  overridesByTarget: Record<string, string>,
  currentDriverKeys: string[],
): string[] {
  const eligibleKeys = assumptions
    .filter(
      (assumption) =>
        deriveSliderSpec(
          currentAssumptionValue(assumption, overridesByTarget),
        ).kind === 'range',
    )
    .map((assumption) => assumption.targetKey);
  const eligible = new Set(eligibleKeys);
  const retained = Array.from(new Set(currentDriverKeys)).filter(
    (targetKey) => eligible.has(targetKey),
  );
  return retained.length > 0 ? retained : eligibleKeys.slice(0, 1);
}

export function canRetainSensitivityIdentity(
  activeIdentity: SensitivityIdentity | null,
  persisted: PersistedCalculationState,
): boolean {
  return (
    activeIdentity !== null &&
    persisted.modelVersionId === activeIdentity.modelVersionId &&
    persisted.graphVersionId === activeIdentity.graphVersionId
  );
}

export function formatSensitivityDelta(
  value: number,
  unit: string | null,
  numberFormat: string | null,
): string {
  const percentage =
    unit?.trim() === '%' || numberFormat?.includes('%') === true;
  const displayedValue = percentage ? value * 100 : value;
  const sign = displayedValue > 0 ? '+' : '';
  const formatted = displayedValue.toLocaleString('en-US', {
    maximumFractionDigits: 4,
    minimumFractionDigits: 0,
  });
  if (percentage) {
    return `${sign}${formatted} pp`;
  }
  return `${sign}${formatted}${unit ? ` ${unit}` : ''}`;
}

export function selectDefaultSensitivityOutput(
  kpis: SensitivityKpi[],
): string | null {
  const availableKpis = kpis.filter(
    (kpi) =>
      kpi.current.availabilityStatus === 'available' &&
      kpi.current.numericValue !== null,
  );
  const kpiByRole = new Map<string, SensitivityKpi>();
  for (const kpi of availableKpis) {
    if (!kpiByRole.has(kpi.businessRole)) {
      kpiByRole.set(kpi.businessRole, kpi);
    }
  }
  for (const role of ['project_irr', 'equity_irr', 'npv']) {
    const kpi = kpiByRole.get(role);
    if (kpi !== undefined) {
      return kpi.outputId;
    }
  }
  return availableKpis[0]?.outputId ?? null;
}

function currentAssumptionValue(
  assumption: SensitivityAssumption,
  overridesByTarget: Record<string, string>,
): string {
  const override = overridesByTarget[assumption.targetKey];
  if (override === undefined) {
    return assumption.currentValue;
  }
  numberValue(override);
  return override.trim();
}

function axisValues(value: string): CalculationNumberValue[] {
  return [
    multiplyDecimal(value, 4, 5),
    multiplyDecimal(value, 9, 10),
    multiplyDecimal(value, 1, 1),
    multiplyDecimal(value, 11, 10),
    multiplyDecimal(value, 6, 5),
  ].map(numberValue);
}

export function buildSensitivityRequest(
  input: SensitivityRequestBuildInput,
): CalculationSensitivityRequest {
  const assumptionsByTarget = new Map(
    input.assumptions.map((assumption) => [
      assumption.targetKey,
      assumption,
    ]),
  );
  const current_overrides = input.assumptions.flatMap((assumption) => {
    const override = input.overridesByTarget[assumption.targetKey];
    if (
      override === undefined ||
      decimalEquals(override, assumption.currentValue)
    ) {
      return [];
    }
    return [{ target: assumption.target, value: numberValue(override) }];
  });

  const uniqueDriverKeys = Array.from(
    new Set(input.tornadoDriverKeys),
  ).slice(0, 12);
  const drivers = uniqueDriverKeys.flatMap((targetKey) => {
    const assumption = assumptionsByTarget.get(targetKey);
    if (assumption === undefined) {
      return [];
    }
    const value = currentAssumptionValue(
      assumption,
      input.overridesByTarget,
    );
    const slider = deriveSliderSpec(value);
    if (slider.kind !== 'range') {
      return [];
    }
    return [
      {
        target: assumption.target,
        low: numberValue(slider.min),
        high: numberValue(slider.max),
      },
    ];
  });

  let two_way: CalculationSensitivityRequest['two_way'] = null;
  if (
    input.rowDriverKey !== null &&
    input.columnDriverKey !== null &&
    input.rowDriverKey !== input.columnDriverKey
  ) {
    const row = assumptionsByTarget.get(input.rowDriverKey);
    const column = assumptionsByTarget.get(input.columnDriverKey);
    if (row !== undefined && column !== undefined) {
      const rowValue = currentAssumptionValue(
        row,
        input.overridesByTarget,
      );
      const columnValue = currentAssumptionValue(
        column,
        input.overridesByTarget,
      );
      const rowDecimal = parseDecimal(rowValue);
      const columnDecimal = parseDecimal(columnValue);
      if (
        rowDecimal !== null &&
        columnDecimal !== null &&
        rowDecimal.sign !== 0 &&
        columnDecimal.sign !== 0
      ) {
        two_way = {
          row: { target: row.target, values: axisValues(rowValue) },
          column: {
            target: column.target,
            values: axisValues(columnValue),
          },
        };
      }
    }
  }

  return {
    graph_version_id: input.graphVersionId,
    output_id: input.outputId,
    current_overrides,
    drivers,
    two_way,
  };
}

export function buildTornadoRows(
  response: CalculationSensitivityResponse,
  assumptionsByTarget: ReadonlyMap<string, SensitivityAssumption>,
): SensitivityTornadoRow[] {
  const currentValue = numericProjection(response.selected_output.current);
  return response.drivers
    .map((driver, index) => {
      const targetKey = sensitivityTargetKey(driver.target);
      const assumption = assumptionsByTarget.get(targetKey);
      const lowValue = numericProjection(driver.low_case.output);
      const highValue = numericProjection(driver.high_case.output);
      const lowDelta =
        lowValue === null || currentValue === null
          ? null
          : lowValue - currentValue;
      const highDelta =
        highValue === null || currentValue === null
          ? null
          : highValue - currentValue;
      const endpointImpacts = [lowDelta, highDelta].filter(
        (value): value is number => value !== null,
      );
      const unavailableReason =
        projectionUnavailableReason(response.selected_output.current) ??
        projectionUnavailableReason(driver.low_case.output) ??
        projectionUnavailableReason(driver.high_case.output);
      return {
        row: {
          targetKey,
          label: assumption?.label ?? targetKey,
          unit: response.selected_output.unit,
          lowInputValue: driver.low_case.input_value.value,
          highInputValue: driver.high_case.input_value.value,
          lowValue,
          currentValue,
          highValue,
          lowDelta,
          highDelta,
          impact:
            endpointImpacts.length === 0
              ? null
              : Math.max(
                  ...endpointImpacts.map((value) => Math.abs(value)),
                ),
          lowRunId: driver.low_case.calculation_run_id,
          highRunId: driver.high_case.calculation_run_id,
          unavailableReason,
          warnings: [
            ...driver.warnings,
            ...driver.low_case.warnings,
            ...driver.high_case.warnings,
          ],
        },
        index,
      };
    })
    .sort(
      (left, right) =>
        (right.row.impact ?? -1) - (left.row.impact ?? -1) ||
        left.index - right.index,
    )
    .map(({ row }) => row);
}

export function buildTwoWayMatrix(
  response: CalculationSensitivityResponse,
  assumptionsByTarget: ReadonlyMap<string, SensitivityAssumption>,
): SensitivityMatrixView | null {
  if (response.two_way === null) {
    return null;
  }
  const rowTargetKey = sensitivityTargetKey(response.two_way.row_target);
  const columnTargetKey = sensitivityTargetKey(
    response.two_way.column_target,
  );
  const rowValues: string[] = [];
  const columnValues: string[] = [];
  const seenRows = new Set<string>();
  const seenColumns = new Set<string>();
  const cellByCoordinates = new Map<string, SensitivityMatrixCell>();

  for (const cell of response.two_way.cells) {
    const rowValue = cell.row_value.value;
    const columnValue = cell.column_value.value;
    if (!seenRows.has(rowValue)) {
      seenRows.add(rowValue);
      rowValues.push(rowValue);
    }
    if (!seenColumns.has(columnValue)) {
      seenColumns.add(columnValue);
      columnValues.push(columnValue);
    }
    cellByCoordinates.set(`${rowValue}\u0000${columnValue}`, {
      rowValue,
      columnValue,
      calculationRunId: cell.calculation_run_id,
      numericValue: numericProjection(cell.output),
      unavailableReason: projectionUnavailableReason(cell.output),
      warnings: [...cell.warnings, ...cell.output.warnings],
    });
  }

  return {
    rowTargetKey,
    columnTargetKey,
    rowLabel:
      assumptionsByTarget.get(rowTargetKey)?.label ?? rowTargetKey,
    columnLabel:
      assumptionsByTarget.get(columnTargetKey)?.label ?? columnTargetKey,
    rowValues,
    columnValues,
    rows: rowValues.map((rowValue) => ({
      value: rowValue,
      cells: columnValues.map(
        (columnValue) =>
          cellByCoordinates.get(`${rowValue}\u0000${columnValue}`) ?? {
            rowValue,
            columnValue,
            calculationRunId: null,
            numericValue: null,
            unavailableReason: 'Sensitivity result unavailable.',
            warnings: [],
          },
      ),
    })),
  };
}

function isStructuredNotFound(
  error: unknown,
  requestedRunId: string,
): boolean {
  if (typeof error !== 'object' || error === null) {
    return false;
  }
  const candidate = error as {
    status?: unknown;
    detail?: unknown;
  };
  if (
    candidate.status !== 404 ||
    typeof candidate.detail !== 'object' ||
    candidate.detail === null
  ) {
    return false;
  }
  const detail = candidate.detail as {
    code?: unknown;
    resource_id?: unknown;
  };
  return (
    detail.code === 'CALCULATION_RUN_NOT_FOUND' &&
    (detail.resource_id === undefined ||
      detail.resource_id === null ||
      detail.resource_id === requestedRunId)
  );
}

export async function restoreSensitivityOutputProjection(
  storage: StorageLike,
  state: PersistedCalculationState,
  getOutputs: typeof getCalculationRunOutputs = getCalculationRunOutputs,
): Promise<CalculationRunOutputsResponse | null> {
  if (state.overrideRunId !== null) {
    try {
      return await getOutputs(state.overrideRunId);
    } catch (error) {
      if (!isStructuredNotFound(error, state.overrideRunId)) {
        throw error;
      }
      try {
        storage.removeItem(CALCULATION_STORAGE_KEYS.overrideRunId);
      } catch {
        // Storage may be unavailable or disabled.
      }
    }
  }
  return state.baselineRunId === null
    ? null
    : getOutputs(state.baselineRunId);
}

export function canApplySensitivityResponse(
  response: CalculationSensitivityResponse,
  guard: SensitivityResponseGuard,
): boolean {
  return (
    guard.requestRevision === guard.currentRevision &&
    response.model_version_id === guard.modelVersionId &&
    response.graph_version_id === guard.graphVersionId &&
    response.selected_output.output_id === guard.outputId
  );
}
