const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadTypeScriptModule } = require('./load-typescript.cjs');

const sourceRoot = path.join(__dirname, '..', 'src');
const progressPath = path.join(sourceRoot, 'lib', 'extractionProgress.ts');
const componentRoot = path.join(sourceRoot, 'components', 'extraction');

function loadExperience() {
  const experiencePath = path.join(componentRoot, 'ExtractionLoadingExperience.tsx');
  const requiredFiles = [
    progressPath,
    path.join(componentRoot, 'ExtractionStageStepper.tsx'),
    path.join(componentRoot, 'WorkbookTransformation.tsx'),
    path.join(componentRoot, 'ProcessingActivityList.tsx'),
    experiencePath,
  ];
  for (const filePath of requiredFiles) {
    assert.ok(fs.existsSync(filePath), `expected ${filePath} to exist`);
  }

  const progress = loadTypeScriptModule(progressPath);
  const progressMock = { '../../lib/extractionProgress': progress };
  const stepper = loadTypeScriptModule(requiredFiles[1], progressMock);
  const workbook = loadTypeScriptModule(requiredFiles[2]);
  const activities = loadTypeScriptModule(requiredFiles[3], progressMock);
  return loadTypeScriptModule(experiencePath, {
    '../../lib/extractionProgress': progress,
    './ExtractionStageStepper': stepper,
    './WorkbookTransformation': workbook,
    './ProcessingActivityList': activities,
  });
}

test('loading view renders approved inspect state and semantic progress', () => {
  const { ExtractionLoadingExperience } = loadExperience();
  const markup = renderToStaticMarkup(
    React.createElement(ExtractionLoadingExperience, {
      progress: 28,
      stage: 'inspect',
      state: 'processing',
    }),
  );

  assert.match(markup, /Uploading your financial model\.\.\./);
  assert.match(markup, /Inspecting workbook structure/);
  assert.match(markup, /Reading sheets, formulas and model relationships/);
  assert.match(markup, /What we&#x27;re doing/);
  assert.match(markup, /Identifying sheets and ranges/);
  assert.match(markup, /role="progressbar"/);
  assert.match(markup, /aria-valuemin="0"/);
  assert.match(markup, /aria-valuemax="100"/);
  assert.match(markup, /aria-valuenow="28"/);
});

test('loading view always displays Your model and no uploaded filename', () => {
  const { ExtractionLoadingExperience } = loadExperience();
  const markup = renderToStaticMarkup(
    React.createElement(ExtractionLoadingExperience, {
      progress: 45,
      stage: 'extract',
      state: 'processing',
    }),
  );

  assert.match(markup, />Your model</);
  assert.doesNotMatch(markup, /Financial_Model\.xlsx/);
  assert.doesNotMatch(markup, /actual-upload\.xlsx/);
});

test('preparation stage identifies estimated progress and backend work', () => {
  const { ExtractionLoadingExperience } = loadExperience();
  const markup = renderToStaticMarkup(
    React.createElement(ExtractionLoadingExperience, {
      progress: 90,
      stage: 'prepare',
      state: 'processing',
    }),
  );

  assert.match(markup, /Preparing calculation model/);
  assert.match(
    markup,
    /Extracting calculation rules and compiling the calculation graph/,
  );
  assert.match(markup, /Estimated progress/);
  assert.match(markup, /aria-label="Estimated model preparation progress"/);
});

test('completed view exposes 100 percent and completion status', () => {
  const { ExtractionLoadingExperience } = loadExperience();
  const markup = renderToStaticMarkup(
    React.createElement(ExtractionLoadingExperience, {
      progress: 100,
      stage: 'prepare',
      state: 'completed',
    }),
  );

  assert.match(markup, /aria-valuenow="100"/);
  assert.match(markup, /Model and calculation rules ready/);
  assert.match(markup, />100%</);
});
