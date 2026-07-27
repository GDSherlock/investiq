import assert from 'node:assert/strict';
import test from 'node:test';

import { buildSensitivityTornadoGeometry } from './sensitivity-tornado-geometry';

test('places Low and High on the exact same track for every driver', () => {
  const geometry = buildSensitivityTornadoGeometry({
    width: 400,
    rowHeight: 48,
    barHeight: 14,
    rows: [
      { targetKey: 'revenue', lowDelta: -0.12, highDelta: 0.18 },
      { targetKey: 'cost', lowDelta: 0.06, highDelta: 0.09 },
    ],
  });

  for (const row of geometry.rows) {
    assert.equal(row.low.yCenter, row.high.yCenter);
    assert.equal(row.low.barY, row.high.barY);
    assert.equal(row.low.barHeight, row.high.barHeight);
  }
});

test('uses a symmetric domain and renders endpoints on opposite sides of zero', () => {
  const geometry = buildSensitivityTornadoGeometry({
    width: 400,
    rowHeight: 48,
    barHeight: 14,
    rows: [{ targetKey: 'revenue', lowDelta: -0.12, highDelta: 0.18 }],
  });
  const [row] = geometry.rows;

  assert.deepEqual(geometry.domain, [-0.18, 0.18]);
  assert.equal(geometry.zeroX, 200);
  assert.ok(row.low.barX !== null && row.low.barX < geometry.zeroX);
  assert.ok(
    row.low.barX !== null &&
      row.low.barX + row.low.barWidth === geometry.zeroX,
  );
  assert.equal(row.high.barX, geometry.zeroX);
  assert.ok(row.high.barWidth > 0);
});

test('keeps same-side endpoints anchored at zero and distinguishable by their endpoint positions', () => {
  const geometry = buildSensitivityTornadoGeometry({
    width: 400,
    rowHeight: 48,
    barHeight: 14,
    rows: [{ targetKey: 'cost', lowDelta: 0.06, highDelta: 0.09 }],
  });
  const [row] = geometry.rows;

  assert.equal(row.low.barX, geometry.zeroX);
  assert.equal(row.high.barX, geometry.zeroX);
  assert.notEqual(row.low.markerX, row.high.markerX);
  assert.ok(
    row.low.markerX !== null &&
      row.high.markerX !== null &&
      row.low.markerX < row.high.markerX,
  );
});

test('keeps zero values valid at the zero axis with a nonzero fallback domain', () => {
  const geometry = buildSensitivityTornadoGeometry({
    width: 400,
    rowHeight: 48,
    barHeight: 14,
    rows: [{ targetKey: 'tax', lowDelta: 0, highDelta: 0 }],
  });
  const [row] = geometry.rows;

  assert.deepEqual(geometry.domain, [-1, 1]);
  assert.equal(row.low.barWidth, 0);
  assert.equal(row.high.barWidth, 0);
  assert.equal(row.low.markerX, geometry.zeroX);
  assert.equal(row.high.markerX, geometry.zeroX);
});

test('preserves an unavailable endpoint instead of treating it as zero', () => {
  const geometry = buildSensitivityTornadoGeometry({
    width: 400,
    rowHeight: 48,
    barHeight: 14,
    rows: [{ targetKey: 'debt', lowDelta: null, highDelta: -0.1 }],
  });
  const [row] = geometry.rows;

  assert.equal(row.low.available, false);
  assert.equal(row.low.barX, null);
  assert.equal(row.low.markerX, null);
  assert.equal(row.high.available, true);
  assert.ok(row.high.barX !== null && row.high.barX < geometry.zeroX);
});
