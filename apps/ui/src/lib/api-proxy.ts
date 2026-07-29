export const MODEL_UPLOAD_PROXY_TIMEOUT_MS = 30 * 60 * 1000;

const UPSTREAM_TIMEOUT_CODES = new Set([
  'UND_ERR_HEADERS_TIMEOUT',
  'UND_ERR_BODY_TIMEOUT',
]);
const UPSTREAM_UNAVAILABLE_CODES = new Set([
  'ENOTFOUND',
  'ECONNREFUSED',
  'ECONNRESET',
  'EHOSTUNREACH',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function upstreamErrorCode(error: unknown): string | null {
  if (!isRecord(error) || !isRecord(error.cause)) {
    return null;
  }
  const code = error.cause.code;
  return typeof code === 'string' ? code : null;
}

export function isUpstreamTimeout(error: unknown): boolean {
  const code = upstreamErrorCode(error);
  return code !== null && UPSTREAM_TIMEOUT_CODES.has(code);
}

export function isUpstreamUnavailable(error: unknown): boolean {
  const code = upstreamErrorCode(error);
  return code !== null && UPSTREAM_UNAVAILABLE_CODES.has(code);
}

export function buildUploadProxyTimeoutResponse(): Response {
  return Response.json(
    {
      detail: {
        code: 'UPLOAD_PROXY_TIMEOUT',
        message:
          'Model analysis exceeded the 30-minute proxy window and may still be running. Do not retry immediately.',
        retryable: false,
        resource_id: null,
      },
    },
    {
      status: 504,
      statusText: 'Gateway Timeout',
      headers: { 'Cache-Control': 'no-store' },
    },
  );
}

function buildApiUnavailableResponse(): Response {
  return Response.json(
    {
      detail: {
        code: 'API_UNAVAILABLE',
        message:
          'Backend API is unavailable. Wait for the service to become healthy, then retry.',
        retryable: true,
        resource_id: null,
      },
    },
    {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Cache-Control': 'no-store' },
    },
  );
}

export function buildUploadProxyErrorResponse(
  error: unknown,
): Response | null {
  if (isUpstreamTimeout(error)) {
    return buildUploadProxyTimeoutResponse();
  }
  if (isUpstreamUnavailable(error)) {
    return buildApiUnavailableResponse();
  }
  return null;
}
