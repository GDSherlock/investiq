const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const React = require('react');
const TestRenderer = require('react-test-renderer');
const { loadTypeScriptModule } = require('./load-typescript.cjs');

const componentDirectory = path.join(
  __dirname,
  '..',
  'src',
  'components',
  'report-chat',
);

const personas = [
  { id: 'IM', short: 'IM', name: 'Investment Manager' },
  { id: 'CF', short: 'CF', name: 'CFO' },
];

function loadComponent(filename, mocks = {}) {
  const componentPath = path.join(componentDirectory, filename);
  assert.ok(fs.existsSync(componentPath), `expected ${componentPath} to exist`);
  return loadTypeScriptModule(componentPath, mocks);
}

test('selector changes persona without owning message state', () => {
  const { ReportPersonaSelector } = loadComponent(
    'ReportPersonaSelector.tsx',
  );
  const changes = [];
  const renderer = TestRenderer.create(
    React.createElement(ReportPersonaSelector, {
      personaId: 'IM',
      personas,
      onChange: (id) => changes.push(id),
    }),
  );

  TestRenderer.act(() =>
    renderer.root.findByProps({ 'data-persona-id': 'CF' }).props.onClick(),
  );

  assert.deepEqual(changes, ['CF']);
  assert.equal(
    renderer.root.findByProps({ 'data-persona-id': 'IM' }).props[
      'aria-pressed'
    ],
    true,
  );
});

test('starter sends a normal chat message', () => {
  const { PersonaReportStarters } = loadComponent(
    'PersonaReportStarters.tsx',
  );
  const sent = [];
  const renderer = TestRenderer.create(
    React.createElement(PersonaReportStarters, {
      prompts: ['Generate a Board One-Pager'],
      disabled: false,
      onSend: (text) => sent.push(text),
    }),
  );

  TestRenderer.act(() => renderer.root.findByType('button').props.onClick());

  assert.deepEqual(sent, ['Generate a Board One-Pager']);
});

test('rich report renders stored persona, document blocks, sources, copy, and Word action', async () => {
  const copied = [];
  const downloads = [];
  const originalNavigator = global.navigator;
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: {
      clipboard: {
        writeText: async (value) => copied.push(value),
      },
    },
  });

  try {
    const componentPath = path.join(
      componentDirectory,
      'RichReportMessage.tsx',
    );
    const { RichReportMessage } = loadComponent('RichReportMessage.tsx', {
      '@/lib/report-chat': {
        reportDocumentToHtml: () => '<h1>CFO Funding Note</h1>',
        reportDocumentToText: () => 'CFO Funding Note for Word',
      },
    });
    const report = {
      title: 'CFO Funding Note',
      blocks: [
        {
          kind: 'heading',
          level: 1,
          text: 'Funding position',
          citation_ids: [],
        },
        {
          kind: 'paragraph',
          text: 'Minimum DSCR is 1.3x.',
          citation_ids: ['M1'],
        },
        {
          kind: 'table',
          columns: ['Metric', 'Value'],
          rows: [['Minimum DSCR', '1.3x']],
          citation_ids: ['M1', 'U1'],
        },
      ],
      citations: [
        {
          id: 'M1',
          source_type: 'model',
          label: 'Minimum DSCR',
          source_ref: 'Returns!B12',
          message_id: null,
        },
        {
          id: 'U1',
          source_type: 'user',
          label: 'User message',
          source_ref: 'message:user-1',
          message_id: 'user-1',
        },
      ],
    };
    const renderer = TestRenderer.create(
      React.createElement(RichReportMessage, {
        messageId: 'assistant-1',
        personaName: 'CFO',
        report,
        onDownload: async (messageId) => downloads.push(messageId),
      }),
    );
    const rendered = JSON.stringify(renderer.toJSON());

    assert.match(rendered, /CFO Funding Note/);
    assert.match(rendered, /Funding position/);
    assert.match(rendered, /Minimum DSCR is 1\.3x/);
    assert.match(rendered, /Metric/);
    assert.match(rendered, /\[M1\]/);
    assert.match(rendered, /\[U1\]/);
    assert.match(rendered, /Generated as CFO/);
    assert.doesNotMatch(fs.readFileSync(componentPath, 'utf8'), /dangerouslySetInnerHTML/);

    await TestRenderer.act(async () => {
      await renderer.root.findByProps({ 'data-action': 'copy-report' }).props.onClick();
    });
    await TestRenderer.act(async () => {
      await renderer.root.findByProps({ 'data-action': 'download-docx' }).props.onClick();
    });

    assert.deepEqual(copied, ['CFO Funding Note for Word']);
    assert.deepEqual(downloads, ['assistant-1']);
  } finally {
    Object.defineProperty(global, 'navigator', {
      configurable: true,
      value: originalNavigator,
    });
  }
});
