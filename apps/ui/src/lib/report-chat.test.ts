import assert from 'node:assert/strict';
import test from 'node:test';

import type { ReportDocument } from './calculation-api-types';
import {
  getReportChatClientId,
  reportDocumentToHtml,
  reportDocumentToText,
} from './report-chat';


class MemoryStorage implements Pick<Storage, 'getItem' | 'setItem'> {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}


const REPORT_FIXTURE: ReportDocument = {
  title: 'CFO Funding Note',
  blocks: [
    {
      kind: 'heading',
      level: 1,
      text: 'Funding & liquidity',
      citation_ids: [],
    },
    {
      kind: 'paragraph',
      text: 'Minimum DSCR is 1.3x <script>alert(1)</script>.',
      citation_ids: ['M1'],
    },
    {
      kind: 'table',
      columns: ['Metric', 'Value'],
      rows: [['Minimum DSCR', '1.3x']],
      citation_ids: ['M1'],
    },
    {
      kind: 'numbered_list',
      items: ['Confirm the two-month delay'],
      citation_ids: ['U1'],
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


test('client id is stable for one browser', () => {
  const storage = new MemoryStorage();

  assert.equal(getReportChatClientId(storage, () => 'client-1'), 'client-1');
  assert.equal(getReportChatClientId(storage, () => 'client-2'), 'client-1');
});


test('rich conversion preserves structure and citations without raw HTML', () => {
  const html = reportDocumentToHtml(REPORT_FIXTURE);
  const text = reportDocumentToText(REPORT_FIXTURE);

  assert.match(html, /<h1>CFO Funding Note<\/h1>/);
  assert.match(html, /<table>/);
  assert.match(html, /\[M1\]/);
  assert.match(html, /\[U1\]/);
  assert.doesNotMatch(html, /<script/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(text, /CFO Funding Note/);
  assert.match(text, /Minimum DSCR\t1\.3x/);
  assert.match(text, /Evidence Sources/);
  assert.match(text, /\[M1\] Minimum DSCR — Returns!B12/);
});
