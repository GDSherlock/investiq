import type {
  CalculationRunValue,
  CalculationTypedValue,
} from './calculation-api-types';

export function typedValuesEqual(
  left: CalculationTypedValue | null,
  right: CalculationTypedValue | null,
): boolean {
  if (left === null || right === null) {
    return left === right;
  }
  if (left.value_type !== right.value_type) {
    return false;
  }

  switch (left.value_type) {
    case 'number':
    case 'text':
    case 'date':
      return left.value === (right as typeof left).value;
    case 'boolean':
      return left.value === (right as typeof left).value;
    case 'blank':
      return true;
    case 'date_serial': {
      const typedRight = right as typeof left;
      return (
        left.value === typedRight.value &&
        (left.iso_evidence ?? null) === (typedRight.iso_evidence ?? null)
      );
    }
    case 'error':
      return left.error_code === (right as typeof left).error_code;
  }
}

export interface CalculationValueDiff {
  formulaCellId: string;
  baseline: CalculationRunValue;
  override: CalculationRunValue;
}

export function diffCalculationRunValues(
  baselineValues: CalculationRunValue[],
  overrideValues: CalculationRunValue[],
): CalculationValueDiff[] {
  const baselineByFormulaId = new Map(
    baselineValues.map((value) => [value.formula_cell_id, value]),
  );
  const changed: CalculationValueDiff[] = [];

  for (const override of overrideValues) {
    const baseline = baselineByFormulaId.get(override.formula_cell_id);
    if (baseline && !typedValuesEqual(baseline.value, override.value)) {
      changed.push({
        formulaCellId: override.formula_cell_id,
        baseline,
        override,
      });
    }
  }
  return changed;
}

export function formatTypedValue(
  value: CalculationTypedValue | null,
): string {
  if (value === null) {
    return 'No persisted value';
  }
  switch (value.value_type) {
    case 'blank':
      return '(blank)';
    case 'boolean':
      return value.value ? 'true' : 'false';
    case 'date_serial':
      return value.iso_evidence
        ? `${value.value} (${value.iso_evidence})`
        : value.value;
    case 'error':
      return value.error_code;
    default:
      return value.value;
  }
}
