import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formatAnalysisValue,
  formatUiNumber,
  MAX_UI_FRACTION_DIGITS,
} from './ui-number-format';
import { formatTypedValue } from './calculation-value-utils';

test('UI numbers round to at most four decimal places without padding', () => {
  const options = { locales: 'en-US' };

  assert.equal(formatUiNumber(1.23456, options), '1.2346');
  assert.equal(formatUiNumber('1.23000', options), '1.23');
  assert.equal(formatUiNumber(1000.00009, options), '1,000.0001');
});

test('UI number options cannot raise the global four-decimal cap', () => {
  assert.equal(MAX_UI_FRACTION_DIGITS, 4);
  assert.equal(
    formatUiNumber(1.234567, {
      locales: 'en-US',
      maximumFractionDigits: 6,
    }),
    '1.2346',
  );
  assert.equal(
    formatUiNumber(1.239, {
      locales: 'en-US',
      maximumFractionDigits: 2,
    }),
    '1.24',
  );
});

test('UI numbers normalize rounded negative zero and non-finite fallbacks', () => {
  assert.equal(
    formatUiNumber(-0.00001, { locales: 'en-US' }),
    '0',
  );
  assert.equal(
    formatUiNumber(Number.NaN, {
      fallback: 'Unavailable',
      locales: 'en-US',
    }),
    'Unavailable',
  );
  assert.equal(
    formatUiNumber(Number.POSITIVE_INFINITY, {
      fallback: 'Unavailable',
      locales: 'en-US',
    }),
    'Unavailable',
  );
});

test('UI numbers preserve supported compact notation within the cap', () => {
  assert.equal(
    formatUiNumber(1234567.89, {
      locales: 'en-US',
      notation: 'compact',
      maximumFractionDigits: 2,
    }),
    '1.23M',
  );
});

test('analysis values preserve role and unit semantics within the cap', () => {
  assert.equal(
    formatAnalysisValue('project_irr', '0.123456', '%', 'stale'),
    '12.3%',
  );
  assert.equal(
    formatAnalysisValue('minimum_dscr', '1.23456', null, 'stale'),
    '1.23x',
  );
  assert.equal(
    formatAnalysisValue('payback_period', '2.34567', null, 'stale'),
    '2.3 yrs',
  );
  assert.equal(
    formatAnalysisValue(
      'project_npv',
      '1234.56789',
      'USD M',
      'stale',
    ),
    '1,234.5679 USD M',
  );
  assert.equal(
    formatAnalysisValue('project_npv', null, 'USD M', 'Unavailable'),
    'Unavailable',
  );
});

test('typed numeric strings are formatted only at their display boundary', () => {
  const persisted = {
    value_type: 'number' as const,
    value: '1234.56789',
  };

  assert.equal(formatTypedValue(persisted), '1,234.5679');
  assert.equal(persisted.value, '1234.56789');
});
