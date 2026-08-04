'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useActiveAnalysis } from '../ActiveAnalysisContext';
import { usePersona } from '../PersonaContext';
import { ReportChatComposer } from '@/components/report-chat/ReportChatComposer';
import { ReportMessageList } from '@/components/report-chat/ReportMessageList';
import {
  downloadReportChatDocx,
  getReportChat,
  sendReportChatMessage,
} from '@/lib/api';
import type {
  ReportChatMessageResponse,
  ReportPersonaId,
} from '@/lib/calculation-api-types';
import { getReportChatClientId } from '@/lib/report-chat';


interface FailedAttempt {
  text: string;
  idempotencyKey: string;
  pendingMessageId: string;
  modelVersionId: string;
  graphVersionId: string;
  calculationRunId: string;
  personaId: ReportPersonaId;
  clientId: string;
}


function mergeMessages(
  current: ReportChatMessageResponse[],
  incoming: ReportChatMessageResponse[],
  removeMessageId?: string,
): ReportChatMessageResponse[] {
  const merged = [
    ...current.filter((message) => message.message_id !== removeMessageId),
    ...incoming,
  ];
  const seen = new Set<string>();
  return merged.filter((message) => {
    if (seen.has(message.message_id)) {
      return false;
    }
    seen.add(message.message_id);
    return true;
  });
}


function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : 'The report message could not be sent.';
}


export default function ReportsPage() {
  const analysis = useActiveAnalysis();
  const { persona, personas, setPersonaById } = usePersona();
  const loadRevision = useRef(0);
  const scrollAnchor = useRef<HTMLDivElement | null>(null);
  const [clientId, setClientId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ReportChatMessageResponse[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [failedAttempt, setFailedAttempt] = useState<FailedAttempt | null>(
    null,
  );

  useEffect(() => {
    setClientId(getReportChatClientId());
  }, []);

  useEffect(() => {
    const revision = ++loadRevision.current;
    if (clientId === null || analysis.modelVersionId === null) {
      setMessages([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setSendError(null);
    setFailedAttempt(null);
    getReportChat(analysis.modelVersionId, clientId)
      .then((response) => {
        if (
          revision === loadRevision.current &&
          response.model_version_id === analysis.modelVersionId
        ) {
          setMessages(response.messages);
        }
      })
      .catch((error) => {
        if (revision === loadRevision.current) {
          setSendError(errorMessage(error));
        }
      })
      .finally(() => {
        if (revision === loadRevision.current) {
          setLoading(false);
        }
      });
    return () => {
      loadRevision.current += 1;
    };
  }, [analysis.modelVersionId, clientId]);

  useEffect(() => {
    scrollAnchor.current?.scrollIntoView({ behavior: 'smooth' });
  }, [loading, messages.length, sending]);

  const canSend =
    clientId !== null &&
    analysis.status === 'ready' &&
    analysis.modelVersionId !== null &&
    analysis.graphVersionId !== null &&
    analysis.activeRunId !== null;

  const send = useCallback(
    async (text: string, retry?: FailedAttempt) => {
      const trimmed = text.trim();
      if (!canSend || !trimmed || sending) {
        return;
      }
      const idempotencyKey = retry?.idempotencyKey ?? crypto.randomUUID();
      const pendingMessageId =
        retry?.pendingMessageId ?? `pending:${idempotencyKey}`;
      const modelVersionId =
        retry?.modelVersionId ?? analysis.modelVersionId!;
      const graphVersionId =
        retry?.graphVersionId ?? analysis.graphVersionId!;
      const calculationRunId =
        retry?.calculationRunId ?? analysis.activeRunId!;
      const personaId = retry?.personaId ?? persona.id;
      const attemptClientId = retry?.clientId ?? clientId!;
      if (!retry) {
        const optimisticMessage: ReportChatMessageResponse = {
          message_id: pendingMessageId,
          thread_id: 'pending',
          role: 'user',
          kind: 'text',
          persona_id: personaId,
          text: trimmed,
          report: null,
          graph_version_id: graphVersionId,
          calculation_run_id: calculationRunId,
          created_at: new Date().toISOString(),
        };
        setMessages((current) =>
          mergeMessages(current, [optimisticMessage]),
        );
        setInput('');
      }
      setSending(true);
      setSendError(null);
      try {
        const response = await sendReportChatMessage(
          modelVersionId,
          {
            client_id: attemptClientId,
            graph_version_id: graphVersionId,
            calculation_run_id: calculationRunId,
            persona_id: personaId,
            message: trimmed,
            idempotency_key: idempotencyKey,
          },
        );
        setMessages((current) =>
          mergeMessages(
            current,
            [response.user_message, response.assistant_message],
            pendingMessageId,
          ),
        );
        setFailedAttempt(null);
      } catch (error) {
        setSendError(errorMessage(error));
        setFailedAttempt({
          text: trimmed,
          idempotencyKey,
          pendingMessageId,
          modelVersionId,
          graphVersionId,
          calculationRunId,
          personaId,
          clientId: attemptClientId,
        });
      } finally {
        setSending(false);
      }
    },
    [
      analysis.activeRunId,
      analysis.graphVersionId,
      analysis.modelVersionId,
      canSend,
      clientId,
      persona.id,
      sending,
    ],
  );

  const download = useCallback(
    async (messageId: string) => {
      if (analysis.modelVersionId === null || clientId === null) {
        throw new Error('No report conversation is active.');
      }
      const blob = await downloadReportChatDocx(
        analysis.modelVersionId,
        messageId,
        clientId,
      );
      const message = messages.find(
        (candidate) => candidate.message_id === messageId,
      );
      const filename = `${message?.report?.title ?? 'report'}.docx`;
      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        URL.revokeObjectURL(url);
      }
    },
    [analysis.modelVersionId, clientId, messages],
  );

  const noModel = analysis.modelVersionId === null;
  const generationUnavailable = !noModel && analysis.status !== 'ready';

  return (
    <section className="mx-auto flex h-[calc(100vh-9.5rem)] min-h-[620px] max-w-6xl flex-col overflow-hidden rounded-xl border border-d-border bg-d-card/40 shadow-xl shadow-black/10">
      <header className="border-b border-d-border bg-d-card px-4 py-4 sm:px-6">
        <h1 className="text-xl font-semibold text-white">Reports</h1>
        <p className="mt-1 text-sm text-d-muted">
          One conversation, with report prompts tailored to the selected
          persona.
        </p>
      </header>

      {generationUnavailable ? (
        <div className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-200 sm:px-6">
          Existing reports remain available. Complete the active calculation to
          generate a new response.
        </div>
      ) : null}

      <div className="flex-1 overflow-y-auto" aria-label="Report conversation">
        {noModel ? (
          <div className="mx-auto max-w-lg px-6 py-20 text-center">
            <h2 className="text-xl font-semibold text-white">
              No model selected
            </h2>
            <p className="mt-2 text-sm leading-6 text-d-muted">
              Upload or select a model before starting a report conversation.
            </p>
            <Link
              href="/"
              className="mt-5 inline-flex rounded-lg bg-gold-500 px-4 py-2 text-sm font-semibold text-navy-950 transition hover:bg-gold-400"
            >
              Go to Upload
            </Link>
          </div>
        ) : loading && messages.length === 0 ? (
          <p className="px-6 py-16 text-center text-sm text-d-muted">
            Loading report history…
          </p>
        ) : (
          <ReportMessageList
            messages={messages}
            personas={personas}
            onDownload={download}
          />
        )}
        {sending ? (
          <div className="mx-auto max-w-5xl px-6 pb-5 text-sm text-d-muted">
            Generating a {persona.report_system_addendum.report_type_default}…
          </div>
        ) : null}
        <div ref={scrollAnchor} />
      </div>

      {sendError ? (
        <div className="flex items-center justify-between gap-3 border-t border-red-500/30 bg-red-500/10 px-4 py-2.5 text-sm text-red-200 sm:px-6">
          <span>{sendError}</span>
          {failedAttempt ? (
            <button
              type="button"
              disabled={!canSend || sending}
              onClick={() => void send(failedAttempt.text, failedAttempt)}
              className="shrink-0 rounded-md border border-red-400/60 px-3 py-1 text-xs font-semibold transition hover:bg-red-500/15 disabled:opacity-50"
            >
              Retry
            </button>
          ) : null}
        </div>
      ) : null}

      <ReportChatComposer
        value={input}
        disabled={!canSend || sending}
        busy={sending}
        persona={persona}
        personas={personas}
        onChange={setInput}
        onPersonaChange={setPersonaById}
        onSubmit={() => void send(input)}
        onSend={(text) => void send(text)}
      />
    </section>
  );
}
