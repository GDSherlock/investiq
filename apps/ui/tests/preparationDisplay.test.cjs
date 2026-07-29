const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadTypeScriptModule } = require('./load-typescript.cjs');

const componentRoot = path.join(
  __dirname,
  '..',
  'src',
  'components',
  'calculation',
);

function loadDisplayComponents() {
  const summaryPath = path.join(componentRoot, 'CalculationRunSummary.tsx');
  const notificationsPath = path.join(
    componentRoot,
    'PreparationNotifications.tsx',
  );
  const detailsPath = path.join(componentRoot, 'TechnicalDetails.tsx');

  for (const filePath of [summaryPath, notificationsPath, detailsPath]) {
    assert.ok(fs.existsSync(filePath), `expected ${filePath} to exist`);
  }

  const details = loadTypeScriptModule(detailsPath);
  const apiTypes = loadTypeScriptModule(
    path.join(__dirname, '..', 'src', 'lib', 'calculation-api-types.ts'),
  );
  const numberFormat = loadTypeScriptModule(
    path.join(__dirname, '..', 'src', 'lib', 'ui-number-format.ts'),
  );
  const view = loadTypeScriptModule(
    path.join(__dirname, '..', 'src', 'lib', 'model-preparation-view.ts'),
    {
      './calculation-api-types': apiTypes,
      './ui-number-format': numberFormat,
    },
  );
  const summary = loadTypeScriptModule(summaryPath, {
    './TechnicalDetails': details,
    '../../lib/model-preparation-view': view,
    '../../lib/ui-number-format': numberFormat,
  });
  const notifications = loadTypeScriptModule(notificationsPath, {
    '../../lib/ui-number-format': numberFormat,
  });
  return { ...summary, ...notifications, ...details };
}

test('run summary renders readiness metrics and keeps technical ids closed', () => {
  const { CalculationRunSummary } = loadDisplayComponents();
  const markup = renderToStaticMarkup(
    React.createElement(CalculationRunSummary, {
      readiness: {
        status: 'ready_with_warning',
        summary: {
          formula_cells_total: 1043,
          formula_cells_supported: 977,
          graph_nodes: 1043,
          graph_edges: 6265,
        },
      },
      phaseLabel: 'Completed with warnings',
      details: [
        { label: 'Model version', value: 'secret-model-version' },
        { label: 'Baseline run', value: 'secret-baseline-run' },
      ],
    }),
  );

  assert.match(markup, /Run summary/);
  assert.match(markup, />1,043</);
  assert.match(markup, />977</);
  assert.match(markup, /93\.7%/);
  assert.match(markup, />6,265</);
  assert.match(markup, /View details/);
  assert.doesNotMatch(markup, /<details[^>]*open/);
  assert.match(markup, /secret-model-version/);
});

test('run summary displays an em dash instead of NaN when no formulas exist', () => {
  const { CalculationRunSummary } = loadDisplayComponents();
  const markup = renderToStaticMarkup(
    React.createElement(CalculationRunSummary, {
      readiness: {
        status: 'not_prepared',
        summary: {
          formula_cells_total: 0,
          formula_cells_supported: 0,
          graph_nodes: 0,
          graph_edges: 0,
        },
      },
      phaseLabel: 'Waiting',
      details: [],
    }),
  );

  assert.match(markup, /—/);
  assert.doesNotMatch(markup, /NaN/);
});

test('completed run warnings use the amber summary treatment', () => {
  const { CalculationRunSummary } = loadDisplayComponents();
  const markup = renderToStaticMarkup(
    React.createElement(CalculationRunSummary, {
      readiness: {
        status: 'ready',
        summary: {
          formula_cells_total: 1,
          formula_cells_supported: 1,
          graph_nodes: 1,
          graph_edges: 0,
        },
      },
      phaseLabel: 'Completed with warnings',
      hasWarnings: true,
      details: [],
    }),
  );

  assert.match(markup, /text-amber-300/);
});

test('failed and waiting summaries do not claim a successful green state', () => {
  const { CalculationRunSummary } = loadDisplayComponents();
  const failedMarkup = renderToStaticMarkup(
    React.createElement(CalculationRunSummary, {
      readiness: null,
      phaseLabel: 'Failed',
      hasError: true,
      details: [],
    }),
  );
  const waitingMarkup = renderToStaticMarkup(
    React.createElement(CalculationRunSummary, {
      readiness: null,
      phaseLabel: 'Waiting',
      details: [],
    }),
  );

  assert.match(failedMarkup, /text-red-300/);
  assert.doesNotMatch(failedMarkup, /text-emerald-300/);
  assert.doesNotMatch(waitingMarkup, /text-emerald-300/);
});

test('notifications stay collapsed for warnings and open for blocking errors', () => {
  const { PreparationNotifications } = loadDisplayComponents();
  const warning = {
    id: 'warning',
    severity: 'warning',
    source: 'readiness',
    code: 'unsupported_formula_cells',
    message: 'Some formulas are not supported and were skipped.',
    count: 12,
    retryable: null,
    resourceId: null,
  };
  const error = {
    id: 'error',
    severity: 'error',
    source: 'request',
    code: 'API_UNAVAILABLE',
    message: 'Backend API is unavailable.',
    count: null,
    retryable: true,
    resourceId: null,
  };

  const warningMarkup = renderToStaticMarkup(
    React.createElement(PreparationNotifications, {
      notifications: [warning],
    }),
  );
  const errorMarkup = renderToStaticMarkup(
    React.createElement(PreparationNotifications, {
      notifications: [error],
    }),
  );

  assert.match(warningMarkup, /Notifications \(1\)/);
  assert.doesNotMatch(warningMarkup, /<details[^>]*open/);
  assert.match(warningMarkup, /unsupported_formula_cells \(12\)/);
  assert.match(errorMarkup, /<details[^>]*open/);
  assert.match(errorMarkup, /Retry available/);
});
