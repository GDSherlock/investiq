import {
  CalculationApiError,
  type CalculationErrorDetail,
  type CalculationReadinessStatus,
  type CalculationRequest,
  type WorkbookValidationResponse,
} from './calculation-api-types';

const FINITE_DECIMAL_PATTERN =
  /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseCalculationApiErrorPayload(
  status: number,
  statusText: string,
  payload: unknown,
): CalculationApiError {
  const payloadRecord = isRecord(payload) ? payload : {};
  const rawDetail = isRecord(payloadRecord.detail)
    ? payloadRecord.detail
    : payloadRecord;
  const detail: CalculationErrorDetail = {
    code:
      typeof rawDetail.code === 'string'
        ? rawDetail.code
        : `HTTP_${status}`,
    message:
      typeof rawDetail.message === 'string'
        ? rawDetail.message
        : statusText || `Request failed with status ${status}`,
    retryable:
      typeof rawDetail.retryable === 'boolean' ? rawDetail.retryable : false,
    resource_id:
      typeof rawDetail.resource_id === 'string'
        ? rawDetail.resource_id
        : null,
  };
  return new CalculationApiError(status, detail);
}

export function canStartCalculationFlow(
  response: WorkbookValidationResponse,
): response is WorkbookValidationResponse & {
  model_version_id: string;
  workbook_version_id: string;
  submitted: true;
} {
  return (
    response.submitted === true &&
    response.model_version_id !== null &&
    response.workbook_version_id !== null
  );
}

export function isCalculationReady(
  status: CalculationReadinessStatus,
): boolean {
  return status === 'ready' || status === 'ready_with_warning';
}

export function buildBaselineRequest(
  graphVersionId: string,
): CalculationRequest {
  return {
    graph_version_id: graphVersionId,
    overrides: [],
    idempotency_key: null,
  };
}

export function normalizeFiniteNumericString(value: string): string {
  const normalized = value.trim();
  if (
    !FINITE_DECIMAL_PATTERN.test(normalized) ||
    !Number.isFinite(Number(normalized))
  ) {
    throw new Error('Enter a finite numeric string.');
  }
  return normalized;
}

export function buildParameterOverrideRequest(
  graphVersionId: string,
  parameterId: string,
  draftValue: string,
): CalculationRequest {
  return {
    graph_version_id: graphVersionId,
    overrides: [
      {
        target: {
          kind: 'parameter',
          parameter_id: parameterId,
        },
        value: {
          value_type: 'number',
          value: normalizeFiniteNumericString(draftValue),
        },
      },
    ],
    idempotency_key: null,
  };
}
