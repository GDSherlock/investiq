import assert from 'node:assert/strict';
import test from 'node:test';

import {
  AutomaticSensitivityAnalysisScheduler,
  buildAutomaticSensitivityAnalysisSnapshot,
  type AutomaticSensitivityAnalysisSnapshot,
} from './sensitivity-auto-analysis';

function snapshot(
  revision: number,
  currentRunId: string,
  overridesByTarget: Record<string, string> = { 'parameter:price': '62' },
): AutomaticSensitivityAnalysisSnapshot {
  return buildAutomaticSensitivityAnalysisSnapshot({
    revision,
    actionKey: `full-action:${currentRunId}:${JSON.stringify(overridesByTarget)}`,
    currentRunId,
    selectedOutputId: 'project-irr-output',
    overridesByTarget,
    tornadoDriverKeys: ['parameter:price', 'parameter:volume'],
  });
}

test('continuous slider snapshots keep one running request and replace the pending exact snapshot', () => {
  const scheduler = new AutomaticSensitivityAnalysisScheduler();
  const first = snapshot(1, 'exact-run-1', { 'parameter:price': '61' });
  const second = snapshot(2, 'exact-run-2', { 'parameter:price': '62' });
  const third = snapshot(3, 'exact-run-3', { 'parameter:price': '63' });

  assert.deepEqual(scheduler.enqueue(first), { kind: 'start', snapshot: first });
  assert.deepEqual(scheduler.enqueue(second), { kind: 'queued', snapshot: second });
  assert.deepEqual(scheduler.enqueue(third), { kind: 'queued', snapshot: third });
  assert.deepEqual(scheduler.state, {
    running: first,
    pending: third,
    error: null,
  });

  assert.deepEqual(scheduler.succeed(first, (candidate) => candidate.revision === 3), {
    kind: 'start',
    snapshot: third,
  });
  assert.deepEqual(scheduler.state, {
    running: third,
    pending: null,
    error: null,
  });
});

test('driver-selector-only snapshot queues analysis against the already persisted exact run', () => {
  const scheduler = new AutomaticSensitivityAnalysisScheduler();
  const priorDrivers = snapshot(4, 'exact-run-4');
  const selectedDrivers = buildAutomaticSensitivityAnalysisSnapshot({
    revision: 5,
    actionKey: 'full-action:exact-run-4:driver-selector-change',
    currentRunId: 'exact-run-4',
    selectedOutputId: 'project-irr-output',
    overridesByTarget: { 'parameter:price': '62' },
    tornadoDriverKeys: ['parameter:volume', 'parameter:price'],
  });

  assert.deepEqual(scheduler.enqueue(priorDrivers), {
    kind: 'start',
    snapshot: priorDrivers,
  });
  assert.deepEqual(scheduler.enqueue(selectedDrivers), {
    kind: 'queued',
    snapshot: selectedDrivers,
  });
  assert.equal(scheduler.state.pending?.currentRunId, 'exact-run-4');
  assert.deepEqual(scheduler.state.pending?.tornadoDriverKeys, [
    'parameter:volume',
    'parameter:price',
  ]);
});

test('stale response cannot replace the current revision and launches only the current pending snapshot', () => {
  const scheduler = new AutomaticSensitivityAnalysisScheduler();
  const stale = snapshot(6, 'exact-run-6');
  const current = snapshot(7, 'exact-run-7');

  scheduler.enqueue(stale);
  scheduler.enqueue(current);

  assert.deepEqual(scheduler.succeed(stale, (candidate) => candidate.revision === 7), {
    kind: 'start',
    snapshot: current,
  });
  assert.deepEqual(scheduler.succeed(stale, () => true), { kind: 'ignored' });
  assert.equal(scheduler.state.running, current);
  assert.equal(scheduler.state.error, null);
});

test('a failed current analysis retains the last artifact externally and leaves an immediate retry startable', () => {
  const scheduler = new AutomaticSensitivityAnalysisScheduler();
  const failed = snapshot(8, 'exact-run-8');
  const lastCompletedArtifact = { analysisId: 'analysis-7' };

  scheduler.enqueue(failed);
  const failure = new Error('analysis service unavailable');
  assert.deepEqual(scheduler.fail(failed, failure, () => true), {
    kind: 'idle',
  });
  assert.equal(scheduler.state.running, null);
  assert.equal(scheduler.state.pending, null);
  assert.equal(scheduler.state.error, failure);
  assert.deepEqual(lastCompletedArtifact, { analysisId: 'analysis-7' });
  assert.deepEqual(scheduler.enqueue(failed), { kind: 'start', snapshot: failed });
});

test('automatic snapshots contain exact persisted inputs and never carry estimated KPI preview values', () => {
  const exact = snapshot(9, 'exact-run-9', { 'parameter:price': '64' });

  assert.deepEqual(exact, {
    revision: 9,
    actionKey: 'full-action:exact-run-9:{"parameter:price":"64"}',
    currentRunId: 'exact-run-9',
    selectedOutputId: 'project-irr-output',
    overridesByTarget: { 'parameter:price': '64' },
    tornadoDriverKeys: ['parameter:price', 'parameter:volume'],
  });
  assert.equal('estimatedKpis' in exact, false);
});

test('a duplicate initial full action key joins the running request instead of issuing another POST', () => {
  const scheduler = new AutomaticSensitivityAnalysisScheduler();
  const initial = snapshot(10, 'exact-run-10');
  const duplicate = { ...initial, revision: 11 };

  assert.deepEqual(scheduler.enqueue(initial), { kind: 'start', snapshot: initial });
  assert.deepEqual(scheduler.enqueue(duplicate), {
    kind: 'joined',
    snapshot: initial,
  });
  assert.equal(scheduler.state.running, initial);
  assert.equal(scheduler.state.pending, null);
});
