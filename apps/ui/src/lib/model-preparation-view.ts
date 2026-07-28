import {
  CalculationApiError,
  type CalculationReadinessResponse,
  type CalculationRunResponse,
  type WorkbookValidationResponse,
} from './calculation-api-types';

export const DEFAULT_MAX_WORKBOOK_BYTES = 25 * 1024 * 1024;

export interface WorkbookFileLike {
  name: string;
  size: number;
}

export interface WorkbookFileValidationError {
  code: 'UNSUPPORTED_WORKBOOK_FORMAT' | 'WORKBOOK_TOO_LARGE';
  message: string;
}

export type PreparationNotificationSeverity = 'error' | 'warning' | 'info';
export type PreparationNotificationSource =
  | 'request'
  | 'upload'
  | 'readiness'
  | 'calculation'
  | 'state';

export interface PreparationNotification {
  id: string;
  severity: PreparationNotificationSeverity;
  source: PreparationNotificationSource;
  code: string;
  message: string;
  count: number | null;
  retryable: boolean | null;
  resourceId: string | null;
}

export interface TechnicalDetail {
  label: string;
  value: string;
}

interface BuildPreparationNotificationsInput {
  uploadResult: WorkbookValidationResponse | null;
  readiness: CalculationReadinessResponse | null;
  activeRun: CalculationRunResponse | null;
  error: Error | null;
  stateNotice: string | null;
}

interface BuildTechnicalDetailsInput {
  uploadResult: WorkbookValidationResponse | null;
  readiness: CalculationReadinessResponse | null;
  baselineRun: CalculationRunResponse | null;
  overrideRun: CalculationRunResponse | null;
}

const WARNING_MESSAGES: Record<string, string> = {
  unsupported_formula_cells:
    'Some formulas are not supported and were skipped.',
  blocked_by_dependency:
    'Some cells are blocked by unresolved dependencies.',
  cycles_detected:
    'Circular calculation dependencies were detected.',
  execution_errors:
    'Some formulas could not be evaluated.',
  canonical_lineage_incomplete:
    'Lineage could not be completed for some outputs.',
  external_reference_cells:
    'Some formulas depend on external workbooks.',
  special_formula_cells:
    'Some formulas use calculation behavior that is not yet supported.',
  missing_cached_values:
    'Some workbook values were unavailable during calculation.',
  cached_value_mismatches:
    'Some calculated values differ from workbook cached values.',
  CALCULATION_PREPARATION_FAILED:
    'Calculation preparation did not complete successfully.',
};

export function validateWorkbookFile(
  file: WorkbookFileLike,
): WorkbookFileValidationError | null {
  if (!file.name.toLowerCase().endsWith('.xlsx')) {
    return {
      code: 'UNSUPPORTED_WORKBOOK_FORMAT',
      message: 'Choose an .xlsx workbook.',
    };
  }
  if (file.size > DEFAULT_MAX_WORKBOOK_BYTES) {
    return {
      code: 'WORKBOOK_TOO_LARGE',
      message: 'Choose an .xlsx workbook no larger than 25 MB.',
    };
  }
  return null;
}

export function formatSupportedPercentage(
  supported: number,
  total: number,
): string {
  if (total <= 0) {
    return '—';
  }
  return `${((supported / total) * 100).toFixed(1)}%`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringField(
  value: Record<string, unknown>,
  field: string,
): string | null {
  const candidate = value[field];
  return typeof candidate === 'string' && candidate.trim()
    ? candidate.trim()
    : null;
}

function warningCount(
  code: string,
  run: CalculationRunResponse | null,
): number | null {
  if (!run) {
    return null;
  }
  const summary = run.summary;
  const counts: Record<string, number> = {
    unsupported_formula_cells: summary.unsupported_formula_cells,
    blocked_by_dependency: summary.blocked_formula_cells,
    cycles_detected: summary.cycle_formula_cells,
    execution_errors: summary.execution_error_cells,
  };
  const count = counts[code];
  return typeof count === 'number' && count > 0 ? count : null;
}

function warningMessage(code: string, fallback?: string | null): string {
  return fallback || WARNING_MESSAGES[code] || code.replaceAll('_', ' ');
}

function pushUnique(
  target: PreparationNotification[],
  seen: Set<string>,
  notification: PreparationNotification,
): void {
  const dedupeKey = `${notification.source}:${notification.code}`;
  if (seen.has(dedupeKey)) {
    return;
  }
  seen.add(dedupeKey);
  target.push(notification);
}

export function buildPreparationNotifications({
  uploadResult,
  readiness,
  activeRun,
  error,
  stateNotice,
}: BuildPreparationNotificationsInput): PreparationNotification[] {
  const notifications: PreparationNotification[] = [];
  const seen = new Set<string>();

  if (error) {
    const structured =
      error instanceof CalculationApiError
        ? {
            code: error.code,
            retryable: error.retryable,
            resourceId: error.resourceId,
          }
        : {
            code: 'UNEXPECTED_ERROR',
            retryable: false,
            resourceId: null,
          };
    pushUnique(notifications, seen, {
      id: `error:${structured.code}`,
      severity: 'error',
      source: 'request',
      code: structured.code,
      message: error.message,
      count: null,
      retryable: structured.retryable,
      resourceId: structured.resourceId,
    });
  }

  if (uploadResult) {
    for (const rawWarning of uploadResult.warnings) {
      const warning = isRecord(rawWarning) ? rawWarning : {};
      const code = stringField(warning, 'code') ?? 'UPLOAD_WARNING';
      pushUnique(notifications, seen, {
        id: `upload:${code}`,
        severity: 'warning',
        source: 'upload',
        code,
        message: warningMessage(code, stringField(warning, 'message')),
        count: null,
        retryable: null,
        resourceId:
          stringField(warning, 'model_version_id') ??
          stringField(warning, 'workbook_version_id'),
      });
    }

    if (!uploadResult.submitted) {
      for (const rawError of uploadResult.errors) {
        const uploadError = isRecord(rawError) ? rawError : {};
        const code =
          stringField(uploadError, 'code') ||
          uploadResult.stop_reason ||
          'UPLOAD_REJECTED';
        pushUnique(notifications, seen, {
          id: `upload-error:${code}`,
          severity: 'error',
          source: 'upload',
          code,
          message:
            stringField(uploadError, 'message') ||
            'The workbook stopped before model submission.',
          count: null,
          retryable: null,
          resourceId: null,
        });
      }
      if (uploadResult.errors.length === 0) {
        const code = uploadResult.stop_reason || 'UPLOAD_REJECTED';
        pushUnique(notifications, seen, {
          id: `upload-error:${code}`,
          severity: 'error',
          source: 'upload',
          code,
          message: 'The workbook stopped before model submission.',
          count: null,
          retryable: null,
          resourceId: null,
        });
      }
    }
  }

  if (readiness?.error) {
    pushUnique(notifications, seen, {
      id: `readiness-error:${readiness.error.code}`,
      severity: 'error',
      source: 'readiness',
      code: readiness.error.code,
      message: readiness.error.message,
      count: null,
      retryable: readiness.error.retryable,
      resourceId: readiness.error.resource_id,
    });
  }

  for (const code of readiness?.warnings ?? []) {
    pushUnique(notifications, seen, {
      id: `readiness:${code}`,
      severity: 'warning',
      source: 'readiness',
      code,
      message: warningMessage(code),
      count: warningCount(code, activeRun),
      retryable: null,
      resourceId: null,
    });
  }

  for (const code of activeRun?.warnings ?? []) {
    pushUnique(notifications, seen, {
      id: `calculation:${code}`,
      severity: 'warning',
      source: 'calculation',
      code,
      message: warningMessage(code),
      count: warningCount(code, activeRun),
      retryable: null,
      resourceId: activeRun?.calculation_run_id ?? null,
    });
  }

  if (stateNotice) {
    pushUnique(notifications, seen, {
      id: 'state:notice',
      severity: 'info',
      source: 'state',
      code: 'STATE_NOTICE',
      message: stateNotice,
      count: null,
      retryable: null,
      resourceId: null,
    });
  }

  return notifications;
}

function appendDetail(
  details: TechnicalDetail[],
  label: string,
  value: string | number | null | undefined,
  suffix = '',
): void {
  if (value === null || value === undefined || value === '') {
    return;
  }
  details.push({ label, value: `${value}${suffix}` });
}

export function buildTechnicalDetails({
  uploadResult,
  readiness,
  baselineRun,
  overrideRun,
}: BuildTechnicalDetailsInput): TechnicalDetail[] {
  const details: TechnicalDetail[] = [];
  appendDetail(details, 'Filename', uploadResult?.filename);
  appendDetail(details, 'Endpoint mode', uploadResult?.endpoint_mode);
  appendDetail(details, 'Runtime', uploadResult?.runtime_seconds, ' seconds');
  appendDetail(
    details,
    'Model version',
    readiness?.model_version_id ?? uploadResult?.model_version_id,
  );
  appendDetail(
    details,
    'Workbook version',
    readiness?.workbook_version_id ?? uploadResult?.workbook_version_id,
  );
  appendDetail(details, 'Graph version', readiness?.graph_version_id);
  appendDetail(
    details,
    'Extraction ID',
    readiness?.calculation_rule_extraction_id,
  );
  appendDetail(details, 'Baseline run', baselineRun?.calculation_run_id);
  appendDetail(details, 'Override run', overrideRun?.calculation_run_id);
  appendDetail(
    details,
    'Active run',
    overrideRun?.calculation_run_id ?? baselineRun?.calculation_run_id,
  );

  const versions = readiness?.versions;
  appendDetail(details, 'Phase 1 IR', versions?.phase1_ir);
  appendDetail(details, 'Phase 2 IR', versions?.phase2_ir);
  appendDetail(details, 'Compiler', versions?.compiler);
  appendDetail(details, 'Engine', versions?.engine);
  appendDetail(details, 'Registry', versions?.registry);
  appendDetail(details, 'Semantics', versions?.semantics);
  return details;
}
