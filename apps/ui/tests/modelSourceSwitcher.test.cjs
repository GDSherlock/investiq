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
  'ModelSourceSwitcher.tsx',
);

test('source switcher exposes both modes and selects history', () => {
  assert.ok(fs.existsSync(componentPath), `expected ${componentPath} to exist`);
  const { ModelSourceSwitcher } = loadTypeScriptModule(componentPath);
  const changes = [];
  const renderer = TestRenderer.create(
    React.createElement(ModelSourceSwitcher, {
      mode: 'upload',
      onModeChange: (mode) => changes.push(mode),
    }),
  );

  const upload = renderer.root.findByProps({ 'data-model-source': 'upload' });
  const history = renderer.root.findByProps({ 'data-model-source': 'history' });
  assert.equal(upload.props['aria-selected'], true);
  assert.equal(history.props['aria-selected'], false);

  TestRenderer.act(() => history.props.onClick());
  assert.deepEqual(changes, ['history']);
  assert.match(JSON.stringify(renderer.toJSON()), /Upload new model/);
  assert.match(JSON.stringify(renderer.toJSON()), /Use existing model/);
});
