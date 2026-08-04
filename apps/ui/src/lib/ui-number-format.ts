export const MAX_UI_FRACTION_DIGITS = 2;

export interface FormatUiNumberOptions
  extends Intl.NumberFormatOptions {
  fallback?: string;
  locales?: string | string[];
}

export interface FormatAnalysisValueOptions {
  maximumFractionDigits?: number;
}

function fractionDigits(
  requested: number | undefined,
  fallback: number,
): number {
  if (requested === undefined || !Number.isFinite(requested)) {
    return fallback;
  }
  return Math.min(
    MAX_UI_FRACTION_DIGITS,
    Math.max(0, Math.trunc(requested)),
  );
}

function finiteNumber(
  value: number | string | null | undefined,
): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string' && value.trim() === '') {
    return null;
  }
  const numeric = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function formatUiNumber(
  value: number | string | null | undefined,
  options: FormatUiNumberOptions = {},
): string {
  const {
    fallback = '—',
    locales,
    maximumFractionDigits: requestedMaximum,
    minimumFractionDigits: requestedMinimum,
    ...numberFormatOptions
  } = options;
  const numeric = finiteNumber(value);
  if (numeric === null) {
    return fallback;
  }

  const maximumFractionDigits = fractionDigits(
    requestedMaximum,
    MAX_UI_FRACTION_DIGITS,
  );
  const minimumFractionDigits = Math.min(
    fractionDigits(requestedMinimum, 0),
    maximumFractionDigits,
  );
  const roundsToZero =
    Math.abs(numeric) <
    0.5 * 10 ** -maximumFractionDigits;

  return new Intl.NumberFormat(locales, {
    ...numberFormatOptions,
    maximumFractionDigits,
    minimumFractionDigits,
  }).format(roundsToZero ? 0 : numeric);
}

const ANALYSIS_PERCENTAGE_ROLES = new Set([
  'project_irr',
  'equity_irr',
  'discount_rate',
  'project_irr_hurdle',
  'equity_irr_hurdle',
]);

const ANALYSIS_MULTIPLE_ROLES = new Set([
  'minimum_dscr',
  'average_dscr',
  'dscr_covenant',
  'equity_multiple',
  'debt_to_equity_ratio',
]);

export function formatAnalysisValue(
  role: string,
  value: number | string | null | undefined,
  unit: string | null,
  fallback = 'Unavailable',
  options: FormatAnalysisValueOptions = {},
): string {
  const numeric = finiteNumber(value);
  if (numeric === null) {
    return fallback;
  }
  if (ANALYSIS_PERCENTAGE_ROLES.has(role)) {
    return `${formatUiNumber(numeric * 100, {
      locales: 'en-US',
      maximumFractionDigits: options.maximumFractionDigits ?? 1,
    })}%`;
  }
  if (ANALYSIS_MULTIPLE_ROLES.has(role)) {
    return `${formatUiNumber(numeric, {
      locales: 'en-US',
      maximumFractionDigits: 2,
    })}x`;
  }
  if (role === 'payback_period') {
    return `${formatUiNumber(numeric, {
      locales: 'en-US',
      maximumFractionDigits: 1,
    })} yrs`;
  }
  const suffix = unit ? ` ${unit}` : '';
  return `${formatUiNumber(numeric, {
    locales: 'en-US',
  })}${suffix}`;
}
