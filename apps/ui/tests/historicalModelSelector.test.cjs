const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const React = require('react');
const TestRenderer = require('react-test-renderer');
const { loadTypeScriptModule } = require('./load-typescript.cjs');

const componentPath = path.join(
  __dirname,
  '..',
  'src',
  'components',
  'model-history',
  'HistoricalModelSelector.tsx',
);

const models = [
  {
    model_version_id: '11111111-1111-4111-8111-111111111111',
    workbook_version_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    filename: 'North Harbor Infrastructure.xlsx',
    updated_at: '2026-08-02T10:00:00Z',
    calculation_status: 'baseline_ready',
    graph_version_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    baseline_run_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  },
  {
    model_version_id: '22222222-2222-4222-8222-222222222222',
    workbook_version_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    filename: 'MetroLink PPP.xlsx',
    updated_at: '2026-07-18T05:00:00Z',
    calculation_status: 'calculation_required',
    graph_version_id: null,
    baseline_run_id: null,
  },
];

function loadSelector() {
  assert.ok(fs.existsSync(componentPath), `expected ${componentPath} to exist`);
  return loadTypeScriptModule(componentPath);
}

test('picker opens, selects a real model, and continues only after selection', () => {
  const { HistoricalModelSelector } = loadSelector();
  const selected = [];
  const continued = [];
  let renderer;

  const render = (selectedModelId) =>
    React.createElement(HistoricalModelSelector, {
      models,
      loading: false,
      error: null,
      selectedModelId,
      onSelectedModelIdChange: (modelId) => selected.push(modelId),
      onContinue: (model) => continued.push(model),
      onRetry: () => {},
    });

  TestRenderer.act(() => {
    renderer = TestRenderer.create(render(null));
  });
  const continueButton = renderer.root.findByProps({
    'data-testid': 'continue-with-historical-model',
  });
  assert.equal(continueButton.props.disabled, true);

  const picker = renderer.root.findByProps({
    'data-testid': 'historical-model-picker',
  });
  TestRenderer.act(() => picker.props.onClick());
  const secondOption = renderer.root.findByProps({
    'data-model-id': models[1].model_version_id,
  });
  TestRenderer.act(() => secondOption.props.onClick());
  assert.deepEqual(selected, [models[1].model_version_id]);

  TestRenderer.act(() => renderer.update(render(models[1].model_version_id)));
  const enabledContinue = renderer.root.findByProps({
    'data-testid': 'continue-with-historical-model',
  });
  TestRenderer.act(() => enabledContinue.props.onClick());
  assert.deepEqual(continued, [models[1]]);

  const renderedText = JSON.stringify(renderer.toJSON());
  assert.match(renderedText, /MetroLink PPP/);
  assert.match(renderedText, /Updated 18 Jul 2026/);
  assert.match(renderedText, /Calculation required/);
});

test('picker exposes loading, empty, and retryable error states', () => {
  const { HistoricalModelSelector } = loadSelector();
  const common = {
    selectedModelId: null,
    onSelectedModelIdChange: () => {},
    onContinue: () => {},
    onRetry: () => {},
  };

  const loading = TestRenderer.create(
    React.createElement(HistoricalModelSelector, {
      ...common,
      models: [],
      loading: true,
      error: null,
    }),
  );
  assert.match(JSON.stringify(loading.toJSON()), /Loading prepared models/);

  const empty = TestRenderer.create(
    React.createElement(HistoricalModelSelector, {
      ...common,
      models: [],
      loading: false,
      error: null,
    }),
  );
  assert.match(JSON.stringify(empty.toJSON()), /No prepared models/);

  const failed = TestRenderer.create(
    React.createElement(HistoricalModelSelector, {
      ...common,
      models: [],
      loading: false,
      error: new Error('offline'),
    }),
  );
  assert.match(JSON.stringify(failed.toJSON()), /Try again/);
});

test('picker offers a direct return to workbook upload', () => {
  const { HistoricalModelSelector } = loadSelector();
  let uploadRequested = false;
  const renderer = TestRenderer.create(
    React.createElement(HistoricalModelSelector, {
      models,
      loading: false,
      error: null,
      selectedModelId: null,
      onSelectedModelIdChange: () => {},
      onContinue: () => {},
      onRetry: () => {},
      onUseUpload: () => {
        uploadRequested = true;
      },
    }),
  );

  const uploadButton = renderer.root.findByProps({
    'data-testid': 'use-workbook-upload',
  });
  TestRenderer.act(() => uploadButton.props.onClick());

  assert.equal(uploadRequested, true);
  assert.match(JSON.stringify(renderer.toJSON()), /Upload a new workbook instead/);
});
