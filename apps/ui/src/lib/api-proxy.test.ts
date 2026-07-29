import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MODEL_UPLOAD_PROXY_TIMEOUT_MS,
  buildUploadProxyErrorResponse,
  buildUploadProxyTimeoutResponse,
  isUpstreamUnavailable,
  isUpstreamTimeout,
} from './api-proxy';

test('model upload proxy waits thirty minutes for response headers and body data', () => {
  assert.equal(MODEL_UPLOAD_PROXY_TIMEOUT_MS, 30 * 60 * 1000);
});

test('upstream timeout detection recognizes Undici header and body timeouts', () => {
  for (const code of ['UND_ERR_HEADERS_TIMEOUT', 'UND_ERR_BODY_TIMEOUT']) {
    assert.equal(
      isUpstreamTimeout({
        cause: { code },
      }),
      true,
    );
  }
  assert.equal(isUpstreamTimeout({ cause: { code: 'ECONNREFUSED' } }), false);
  assert.equal(isUpstreamTimeout(new Error('unrelated')), false);
});

test('upload proxy timeout response is structured and does not invite duplicate retry', async () => {
  const response = buildUploadProxyTimeoutResponse();

  assert.equal(response.status, 504);
  assert.deepEqual(await response.json(), {
    detail: {
      code: 'UPLOAD_PROXY_TIMEOUT',
      message:
        'Model analysis exceeded the 30-minute proxy window and may still be running. Do not retry immediately.',
      retryable: false,
      resource_id: null,
    },
  });
});

test('upload proxy classifies backend connection failures as unavailable', () => {
  for (const code of [
    'ENOTFOUND',
    'ECONNREFUSED',
    'ECONNRESET',
    'EHOSTUNREACH',
  ]) {
    assert.equal(isUpstreamUnavailable({ cause: { code } }), true);
  }
  assert.equal(
    isUpstreamUnavailable({ cause: { code: 'UND_ERR_HEADERS_TIMEOUT' } }),
    false,
  );
  assert.equal(isUpstreamUnavailable(new Error('unrelated')), false);
});

test('upload proxy returns a retryable structured 503 when the API is unavailable', async () => {
  const response = buildUploadProxyErrorResponse({
    cause: { code: 'ENOTFOUND' },
  });

  assert.ok(response);
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), {
    detail: {
      code: 'API_UNAVAILABLE',
      message:
        'Backend API is unavailable. Wait for the service to become healthy, then retry.',
      retryable: true,
      resource_id: null,
    },
  });
});

test('upload proxy preserves timeout handling and ignores unrelated failures', () => {
  assert.equal(
    buildUploadProxyErrorResponse({
      cause: { code: 'UND_ERR_BODY_TIMEOUT' },
    })?.status,
    504,
  );
  assert.equal(buildUploadProxyErrorResponse(new Error('unrelated')), null);
});
