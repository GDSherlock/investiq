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
  'extraction',
  'WorkbookUploadZone.tsx',
);

function loadUploadZone() {
  assert.ok(fs.existsSync(componentPath), `expected ${componentPath} to exist`);
  return loadTypeScriptModule(componentPath);
}

test('selecting a workbook starts immediately and clears the input for same-file retry', () => {
  const { WorkbookUploadZone } = loadUploadZone();
  const selected = [];
  const workbook = { name: 'model.xlsx', size: 1024 };
  const renderer = TestRenderer.create(
    React.createElement(WorkbookUploadZone, {
      selectedFile: null,
      busy: false,
      hasError: false,
      canRetry: false,
      onFileSelected: (file) => selected.push(file),
      onRetry: () => {},
    }),
  );
  const input = renderer.root.findByType('input');
  const event = {
    currentTarget: {
      files: [workbook],
      value: 'C:\\fakepath\\model.xlsx',
    },
  };

  TestRenderer.act(() => input.props.onChange(event));

  assert.deepEqual(selected, [workbook]);
  assert.equal(event.currentTarget.value, '');
  assert.equal(input.props.accept, '.xlsx');
});

test('dropping a workbook starts immediately and busy state rejects duplicates', () => {
  const { WorkbookUploadZone } = loadUploadZone();
  const selected = [];
  const workbook = { name: 'model.xlsx', size: 1024 };
  const renderer = TestRenderer.create(
    React.createElement(WorkbookUploadZone, {
      selectedFile: workbook,
      busy: false,
      hasError: false,
      canRetry: false,
      onFileSelected: (file) => selected.push(file),
      onRetry: () => {},
    }),
  );
  const dropZone = renderer.root.findByProps({
    'data-testid': 'workbook-drop-zone',
  });

  TestRenderer.act(() =>
    dropZone.props.onDrop({
      preventDefault() {},
      dataTransfer: { files: [workbook] },
    }),
  );
  assert.deepEqual(selected, [workbook]);

  renderer.update(
    React.createElement(WorkbookUploadZone, {
      selectedFile: workbook,
      busy: true,
      hasError: false,
      canRetry: false,
      onFileSelected: (file) => selected.push(file),
      onRetry: () => {},
    }),
  );
  const busyDropZone = renderer.root.findByProps({
    'data-testid': 'workbook-drop-zone',
  });
  TestRenderer.act(() =>
    busyDropZone.props.onDrop({
      preventDefault() {},
      dataTransfer: { files: [workbook] },
    }),
  );

  assert.deepEqual(selected, [workbook]);
  assert.equal(renderer.root.findByType('input').props.disabled, true);
});

test('failed upload offers retry only when safe and always allows another workbook', () => {
  const { WorkbookUploadZone } = loadUploadZone();
  const workbook = { name: 'model.xlsx', size: 1024 };
  const retryable = TestRenderer.create(
    React.createElement(WorkbookUploadZone, {
      selectedFile: workbook,
      busy: false,
      hasError: true,
      canRetry: true,
      onFileSelected: () => {},
      onRetry: () => {},
    }),
  );
  const buttons = retryable.root.findAllByType('button');
  assert.ok(buttons.some(({ children }) => children.includes('Retry upload')));
  assert.ok(
    buttons.some(({ children }) => children.includes('Choose another file')),
  );

  const timeout = TestRenderer.create(
    React.createElement(WorkbookUploadZone, {
      selectedFile: workbook,
      busy: false,
      hasError: true,
      canRetry: false,
      onFileSelected: () => {},
      onRetry: () => {},
    }),
  );
  const timeoutRetry = timeout.root
    .findAllByType('button')
    .find(({ children }) => children.includes('Retry upload'));
  assert.equal(timeoutRetry.props.disabled, true);
});
