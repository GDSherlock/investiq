'use client';

import { useState } from 'react';

import type {
  ReportBlock,
  ReportDocument,
} from '@/lib/calculation-api-types';
import {
  reportDocumentToHtml,
  reportDocumentToText,
} from '@/lib/report-chat';


interface RichReportMessageProps {
  messageId: string;
  personaName: string;
  report: ReportDocument;
  onDownload: (messageId: string) => Promise<void>;
}


function CitationMarkers({ ids }: { ids: string[] }) {
  if (ids.length === 0) {
    return null;
  }
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {ids.map((id) => (
        <span
          key={id}
          className={`rounded px-1 py-0.5 text-[10px] font-semibold ${
            id.startsWith('U')
              ? 'bg-sky-500/15 text-sky-300'
              : 'bg-gold-500/15 text-gold-300'
          }`}
        >
          {`[${id}]`}
        </span>
      ))}
    </span>
  );
}


function ReportBlockView({ block }: { block: ReportBlock }) {
  switch (block.kind) {
    case 'heading': {
      const className =
        block.level === 1
          ? 'mt-7 text-xl font-semibold text-white'
          : block.level === 2
            ? 'mt-5 text-lg font-semibold text-slate-100'
            : 'mt-4 text-base font-semibold text-slate-200';
      return <h3 className={className}>{block.text}</h3>;
    }
    case 'paragraph':
      return (
        <p className="mt-3 text-sm leading-7 text-slate-200">
          {block.text}
          <CitationMarkers ids={block.citation_ids} />
        </p>
      );
    case 'bullet_list':
    case 'numbered_list': {
      const Tag = block.kind === 'bullet_list' ? 'ul' : 'ol';
      return (
        <Tag
          className={`mt-3 space-y-2 pl-6 text-sm leading-6 text-slate-200 ${
            block.kind === 'bullet_list' ? 'list-disc' : 'list-decimal'
          }`}
        >
          {block.items.map((item, index) => (
            <li key={`${index}-${item}`}>
              {item}
              <CitationMarkers ids={block.citation_ids} />
            </li>
          ))}
        </Tag>
      );
    }
    case 'table':
      return (
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full border-collapse text-left text-sm">
            <thead>
              <tr>
                {block.columns.map((column) => (
                  <th
                    key={column}
                    className="border border-d-border bg-d-bg px-3 py-2 font-semibold text-slate-200"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((value, columnIndex) => (
                    <td
                      key={`${rowIndex}-${columnIndex}`}
                      className="border border-d-border px-3 py-2 text-slate-300"
                    >
                      {value}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2">
            <CitationMarkers ids={block.citation_ids} />
          </div>
        </div>
      );
  }
}


export function RichReportMessage({
  messageId,
  personaName,
  report,
  onDownload,
}: RichReportMessageProps) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [copying, setCopying] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const copyReport = async () => {
    setCopying(true);
    setActionError(null);
    try {
      const html = reportDocumentToHtml(report);
      const text = reportDocumentToText(report);
      if (
        typeof ClipboardItem !== 'undefined' &&
        typeof navigator.clipboard?.write === 'function'
      ) {
        await navigator.clipboard.write([
          new ClipboardItem({
            'text/html': new Blob([html], { type: 'text/html' }),
            'text/plain': new Blob([text], { type: 'text/plain' }),
          }),
        ]);
      } else {
        await navigator.clipboard.writeText(text);
      }
    } catch {
      setActionError('The report could not be copied.');
    } finally {
      setCopying(false);
    }
  };

  const downloadReport = async () => {
    setDownloading(true);
    setActionError(null);
    try {
      await onDownload(messageId);
    } catch {
      setActionError('The Word document could not be downloaded.');
    } finally {
      setDownloading(false);
    }
  };

  return (
    <article className="rounded-xl border border-d-border bg-d-card p-5 shadow-sm sm:p-7">
      <div className="flex flex-col gap-3 border-b border-d-border pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-gold-400">
            {`Generated as ${personaName}`}
          </p>
          <h2 className="mt-1 text-2xl font-semibold text-white">
            {report.title}
          </h2>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            data-action="copy-report"
            disabled={copying}
            onClick={() => void copyReport()}
            className="rounded-md border border-d-border px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:border-gold-500/60 hover:text-gold-300 disabled:opacity-50"
          >
            {copying ? 'Copying…' : 'Copy'}
          </button>
          <button
            type="button"
            data-action="download-docx"
            disabled={downloading}
            onClick={() => void downloadReport()}
            className="rounded-md border border-gold-500/60 bg-gold-500/10 px-3 py-1.5 text-xs font-medium text-gold-300 transition hover:bg-gold-500/20 disabled:opacity-50"
          >
            {downloading ? 'Downloading…' : 'Download Word'}
          </button>
        </div>
      </div>

      <div>
        {report.blocks.map((block, index) => (
          <ReportBlockView key={`${block.kind}-${index}`} block={block} />
        ))}
      </div>

      <section className="mt-7 border-t border-d-border pt-4">
        <h3 className="text-sm font-semibold text-slate-100">
          Evidence Sources
        </h3>
        <ul className="mt-2 space-y-2 text-xs text-d-muted">
          {report.citations.map((citation) => (
            <li key={citation.id} className="flex gap-2">
              <span
                className={
                  citation.source_type === 'user'
                    ? 'font-semibold text-sky-300'
                    : 'font-semibold text-gold-300'
                }
              >
                {`[${citation.id}]`}
              </span>
              <span>
                {citation.label} — {citation.source_ref}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {actionError ? (
        <p className="mt-3 text-xs text-red-300" role="alert">
          {actionError}
        </p>
      ) : null}
    </article>
  );
}
