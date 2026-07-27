import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MODEL_UPLOAD_PROXY_TIMEOUT_MS,
  buildUploadProxyTimeoutResponse,
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
