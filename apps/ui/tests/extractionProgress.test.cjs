const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { loadTypeScriptModule } = require('./load-typescript.cjs');

const progressPath = path.join(
  __dirname,
  '..',
  'src',
  'lib',
  'extractionProgress.ts',
);

function loadProgressModule() {
  assert.ok(
    fs.existsSync(progressPath),
    'expected src/lib/extractionProgress.ts to exist',
  );
  return loadTypeScriptModule(progressPath);
}

function createFakeScheduler() {
  let currentTime = 0;
  let nextId = 0;
  let hidden = false;
  const callbacks = new Map();
  const cancelled = [];

  return {
    scheduler: {
      now: () => currentTime,
      request: (callback) => {
        nextId += 1;
        callbacks.set(nextId, callback);
        return nextId;
      },
      cancel: (id) => {
        cancelled.push(id);
        callbacks.delete(id);
      },
      isHidden: () => hidden,
    },
    cancelled,
    frameAt(time) {
      currentTime = time;
      const pending = [...callbacks.values()];
      callbacks.clear();
      for (const callback of pending) callback(time);
    },
    setHidden(value) {
      hidden = value;
    },
    pendingFrames() {
      return callbacks.size;
    },
  };
}

test('fifth stage prepares calculation rules and graph compilation', () => {
  const { EXTRACTION_STAGES } = loadProgressModule();

  assert.deepEqual(EXTRACTION_STAGES.at(-1), {
    id: 'prepare',
    label: 'Prepare',
    title: 'Preparing calculation model',
    description:
      'Extracting calculation rules and compiling the calculation graph',
  });
});

test('simulated progress matches every elapsed-time boundary', () => {
  const { getSimulatedProgress } = loadProgressModule();

  assert.equal(getSimulatedProgress(0), 0);
  assert.equal(getSimulatedProgress(3_000), 12);
  assert.equal(getSimulatedProgress(12_000), 30);
  assert.equal(getSimulatedProgress(35_000), 58);
  assert.equal(getSimulatedProgress(70_000), 78);
  assert.equal(getSimulatedProgress(100_000), 88);
  assert.ok(getSimulatedProgress(160_000) > 88);
  assert.ok(getSimulatedProgress(160_000) < 92);
});

test('simulated progress is monotonic and never exceeds 92 percent', () => {
  const { getSimulatedProgress } = loadProgressModule();
  const times = [
    0, 1_000, 2_999, 3_000, 8_000, 12_000, 20_000, 35_000,
    50_000, 70_000, 85_000, 100_000, 160_000, 1_000_000,
  ];
  const values = times.map(getSimulatedProgress);

  for (let index = 1; index < values.length; index += 1) {
    assert.ok(values[index] >= values[index - 1]);
  }
  assert.ok(values.every((value) => value <= 92));
  assert.ok(values.slice(0, -1).every((value) => value < 92));
});

test('stage selection changes at the required time ranges', () => {
  const { getStageForElapsed } = loadProgressModule();

  assert.equal(getStageForElapsed(0), 'upload');
  assert.equal(getStageForElapsed(2_999), 'upload');
  assert.equal(getStageForElapsed(3_000), 'inspect');
  assert.equal(getStageForElapsed(11_999), 'inspect');
  assert.equal(getStageForElapsed(12_000), 'extract');
  assert.equal(getStageForElapsed(69_999), 'extract');
  assert.equal(getStageForElapsed(70_000), 'validate');
  assert.equal(getStageForElapsed(99_999), 'validate');
  assert.equal(getStageForElapsed(100_000), 'prepare');
});

test('progress driver animates real success to 100 percent', async () => {
  const { createProgressDriver } = loadProgressModule();
  const fake = createFakeScheduler();
  const updates = [];
  const driver = createProgressDriver({
    onUpdate: (snapshot) => updates.push(snapshot),
    scheduler: fake.scheduler,
  });

  fake.frameAt(35_000);
  assert.equal(updates.at(-1).progress, 58);

  const completed = driver.complete();
  fake.frameAt(35_375);
  assert.ok(updates.at(-1).progress > 58);
  assert.ok(updates.at(-1).progress < 100);
  fake.frameAt(35_750);
  await completed;

  assert.equal(updates.at(-1).progress, 100);
  assert.equal(updates.at(-1).stage, 'prepare');
  assert.equal(updates.at(-1).phase, 'completed');
});

test('progress driver never moves backward when frame time regresses', () => {
  const { createProgressDriver } = loadProgressModule();
  const fake = createFakeScheduler();
  const updates = [];
  const driver = createProgressDriver({
    onUpdate: (snapshot) => updates.push(snapshot.progress),
    scheduler: fake.scheduler,
  });

  fake.frameAt(35_000);
  fake.frameAt(20_000);
  driver.stop();

  for (let index = 1; index < updates.length; index += 1) {
    assert.ok(updates[index] >= updates[index - 1]);
  }
});

test('progress driver reduces updates while the document is hidden', () => {
  const { createProgressDriver } = loadProgressModule();
  const fake = createFakeScheduler();
  const updates = [];
  const driver = createProgressDriver({
    onUpdate: (snapshot) => updates.push(snapshot.progress),
    scheduler: fake.scheduler,
  });

  fake.setHidden(true);
  fake.frameAt(12_000);
  assert.deepEqual(updates, [0]);

  fake.setHidden(false);
  fake.frameAt(12_016);
  assert.equal(updates.at(-1), 30);
  driver.stop();
});

test('progress driver cancels its scheduled animation frame on cleanup', () => {
  const { createProgressDriver } = loadProgressModule();
  const fake = createFakeScheduler();
  const updates = [];
  const driver = createProgressDriver({
    onUpdate: (snapshot) => updates.push(snapshot),
    scheduler: fake.scheduler,
  });

  assert.equal(fake.pendingFrames(), 1);
  driver.stop();
  assert.equal(fake.pendingFrames(), 0);
  assert.equal(fake.cancelled.length, 1);

  fake.frameAt(20_000);
  assert.equal(updates.length, 1);
});

test('reduced motion completes without continuous success animation', async () => {
  const { createProgressDriver } = loadProgressModule();
  const fake = createFakeScheduler();
  const updates = [];
  const driver = createProgressDriver({
    onUpdate: (snapshot) => updates.push(snapshot),
    reducedMotion: true,
    scheduler: fake.scheduler,
  });

  await driver.complete();

  assert.equal(updates.at(-1).progress, 100);
  assert.equal(updates.at(-1).phase, 'completed');
});
