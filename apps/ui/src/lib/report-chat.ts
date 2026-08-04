import type {
  ReportBlock,
  ReportDocument,
} from './calculation-api-types';


const REPORT_CHAT_CLIENT_ID_KEY = 'investiq_report_chat_client_id';

type ReportChatStorage = Pick<Storage, 'getItem' | 'setItem'>;


export function getReportChatClientId(
  storage: ReportChatStorage = window.localStorage,
  createId: () => string = () => crypto.randomUUID(),
): string {
  try {
    const existing = storage.getItem(REPORT_CHAT_CLIENT_ID_KEY);
    if (existing) {
      return existing;
    }
    const created = createId();
    storage.setItem(REPORT_CHAT_CLIENT_ID_KEY, created);
    return created;
  } catch {
    return createId();
  }
}


function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      })[character] ?? character,
  );
}


function citationSuffix(citationIds: string[]): string {
  return citationIds.length > 0
    ? ` ${citationIds.map((id) => `[${id}]`).join(' ')}`
    : '';
}


function blockToHtml(block: ReportBlock): string {
  const suffix = escapeHtml(citationSuffix(block.citation_ids));
  switch (block.kind) {
    case 'heading': {
      const level = Math.min(block.level + 1, 4);
      return `<h${level}>${escapeHtml(block.text)}</h${level}>`;
    }
    case 'paragraph':
      return `<p>${escapeHtml(block.text)}${suffix}</p>`;
    case 'bullet_list':
    case 'numbered_list': {
      const tag = block.kind === 'bullet_list' ? 'ul' : 'ol';
      const items = block.items
        .map((item) => `<li>${escapeHtml(item)}${suffix}</li>`)
        .join('');
      return `<${tag}>${items}</${tag}>`;
    }
    case 'table': {
      const headings = block.columns
        .map((column) => `<th>${escapeHtml(column)}</th>`)
        .join('');
      const rows = block.rows
        .map(
          (row) =>
            `<tr>${row
              .map((value) => `<td>${escapeHtml(value)}</td>`)
              .join('')}</tr>`,
        )
        .join('');
      return (
        `<table><thead><tr>${headings}</tr></thead>` +
        `<tbody>${rows}</tbody></table><p>${suffix.trim()}</p>`
      );
    }
  }
}


export function reportDocumentToHtml(report: ReportDocument): string {
  const blocks = report.blocks.map(blockToHtml).join('');
  const citations = report.citations
    .map(
      (citation) =>
        `<li>[${escapeHtml(citation.id)}] ${escapeHtml(citation.label)} — ` +
        `${escapeHtml(citation.source_ref)}</li>`,
    )
    .join('');
  return (
    `<h1>${escapeHtml(report.title)}</h1>${blocks}` +
    `<h2>Evidence Sources</h2><ul>${citations}</ul>`
  );
}


function blockToText(block: ReportBlock): string {
  const suffix = citationSuffix(block.citation_ids);
  switch (block.kind) {
    case 'heading':
      return block.text;
    case 'paragraph':
      return `${block.text}${suffix}`;
    case 'bullet_list':
      return block.items.map((item) => `• ${item}${suffix}`).join('\n');
    case 'numbered_list':
      return block.items
        .map((item, index) => `${index + 1}. ${item}${suffix}`)
        .join('\n');
    case 'table':
      return [
        block.columns.join('\t'),
        ...block.rows.map((row) => row.join('\t')),
        suffix.trim(),
      ]
        .filter(Boolean)
        .join('\n');
  }
}


export function reportDocumentToText(report: ReportDocument): string {
  const blocks = report.blocks.map(blockToText).join('\n\n');
  const citations = report.citations
    .map(
      (citation) =>
        `[${citation.id}] ${citation.label} — ${citation.source_ref}`,
    )
    .join('\n');
  return `${report.title}\n\n${blocks}\n\nEvidence Sources\n${citations}`;
}
