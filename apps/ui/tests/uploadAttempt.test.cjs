const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { loadTypeScriptModule } = require('./load-typescript.cjs');

const attemptPath = path.join(__dirname, '..', 'src', 'lib', 'uploadAttempt.ts');

function loadAttemptModule() {
  assert.ok(
    fs.existsSync(attemptPath),
    'expected src/lib/uploadAttempt.ts to exist',
  );
  return loadTypeScriptModule(attemptPath);
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test('one upload request remains pending while simulated progress continues', async () => {
  const { runUploadAttempt } = loadAttemptModule();
  const upload = deferred();
  const events = [];
  let requestCalls = 0;

  const attempt = runUploadAttempt({
    request: () => {
      requestCalls += 1;
      return upload.promise;
    },
    progress: {
      complete: async () => events.push('progress-complete'),
      stop: () => events.push('progress-stop'),
    },
    onPending: () => events.push('pending'),
    onCompleted: () => events.push('completed'),
    waitForHandoff: async () => events.push('handoff-wait'),
    onSucceeded: () => events.push('succeeded'),
    onFailed: () => events.push('failed'),
  });

  assert.equal(requestCalls, 1);
  assert.deepEqual(events, ['pending']);

  upload.resolve({ model_id: 'model-1' });
  await attempt;

  assert.equal(requestCalls, 1);
  assert.deepEqual(events, [
    'pending',
    'progress-complete',
    'completed',
    'handoff-wait',
    'succeeded',
    'progress-stop',
  ]);
});

test('successful upload passes through the real backend response', async () => {
  const { runUploadAttempt } = loadAttemptModule();
  const response = {
    model_id: 'real-model-id',
    investment_id: 'real-investment-id',
    parsed_sheets: ['Inputs'],
  };
  let received;

  const result = await runUploadAttempt({
    request: async () => response,
    progress: {
      complete: async () => {},
      stop: () => {},
    },
    onPending: () => {},
    onCompleted: () => {},
    waitForHandoff: async () => {},
    onSucceeded: (data) => {
      received = data;
    },
    onFailed: () => assert.fail('success must not call onFailed'),
  });

  assert.strictEqual(received, response);
  assert.strictEqual(result.data, response);
  assert.equal(result.status, 'succeeded');
});

test('failure stops progress immediately and preserves the original error', async () => {
  const { runUploadAttempt } = loadAttemptModule();
  const backendError = new Error('Workbook contains an unsupported formula');
  const events = [];
  let received;

  const result = await runUploadAttempt({
    request: async () => {
      throw backendError;
    },
    progress: {
      complete: async () => events.push('progress-complete'),
      stop: () => events.push('progress-stop'),
    },
    onPending: () => events.push('pending'),
    onCompleted: () => events.push('completed'),
    waitForHandoff: async () => events.push('handoff-wait'),
    onSucceeded: () => events.push('succeeded'),
    onFailed: (error) => {
      received = error;
      events.push('failed');
    },
  });

  assert.strictEqual(received, backendError);
  assert.strictEqual(result.error, backendError);
  assert.equal(result.status, 'failed');
  assert.deepEqual(events, ['pending', 'progress-stop', 'failed']);
});

test('unknown thrown values normalize without replacing real Error messages', () => {
  const { normalizeUploadError } = loadAttemptModule();

  assert.equal(
    normalizeUploadError(new Error('Real backend detail')),
    'Real backend detail',
  );
  assert.equal(normalizeUploadError('Gateway unavailable'), 'Gateway unavailable');
  assert.equal(normalizeUploadError({}), 'Upload failed');
});

test('backend response details normalize without discarding real error copy', () => {
  const { normalizeUploadResponseError } = loadAttemptModule();

  assert.equal(
    normalizeUploadResponseError('Unprocessable Entity', {
      detail: 'Workbook contains unsupported external links',
    }),
    'Workbook contains unsupported external links',
  );
  assert.equal(
    normalizeUploadResponseError('Bad Request', {
      detail: [{ msg: 'File is empty' }, { msg: 'Workbook is invalid' }],
    }),
    'File is empty; Workbook is invalid',
  );
  assert.equal(
    normalizeUploadResponseError('Service Unavailable', null),
    'Upload failed: Service Unavailable',
  );
});
