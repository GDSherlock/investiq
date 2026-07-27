export const MODEL_UPLOAD_PROXY_TIMEOUT_MS = 30 * 60 * 1000;

const UPSTREAM_TIMEOUT_CODES = new Set([
  'UND_ERR_HEADERS_TIMEOUT',
  'UND_ERR_BODY_TIMEOUT',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function isUpstreamTimeout(error: unknown): boolean {
  if (!isRecord(error) || !isRecord(error.cause)) {
    return false;
  }
  const code = error.cause.code;
  return typeof code === 'string' && UPSTREAM_TIMEOUT_CODES.has(code);
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
