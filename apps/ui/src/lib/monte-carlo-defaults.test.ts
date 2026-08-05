import assert from 'node:assert/strict';
import test from 'node:test';

import { defaultMonteCarloSpread } from './monte-carlo-defaults';

test('default Monte Carlo spread stays proportional for decimal rates', () => {
  assert.equal(defaultMonteCarloSpread(0.005), 0.0005);
  assert.equal(defaultMonteCarloSpread(0.5), 0.05);
  assert.equal(defaultMonteCarloSpread(100), 10);
  assert.equal(defaultMonteCarloSpread(0), 0.000001);
});
