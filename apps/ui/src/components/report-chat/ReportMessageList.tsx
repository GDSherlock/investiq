'use client';

import { useMemo } from 'react';

import type { PersonaDef } from '@/app/PersonaContext';
import type { ReportChatMessageResponse } from '@/lib/calculation-api-types';

import { RichReportMessage } from './RichReportMessage';


interface ReportMessageListProps {
  messages: ReportChatMessageResponse[];
  personas: PersonaDef[];
  onDownload: (messageId: string) => Promise<void>;
}


export function ReportMessageList({
  messages,
  personas,
  onDownload,
}: ReportMessageListProps) {
  const personaNames = useMemo(
    () => new Map(personas.map((persona) => [persona.id, persona.name])),
    [personas],
  );

  if (messages.length === 0) {
    return (
      <div className="mx-auto flex max-w-xl flex-col items-center px-6 py-20 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-gold-500/40 bg-gold-500/10 text-xl text-gold-300">
          ✦
        </div>
        <h2 className="mt-4 text-xl font-semibold text-white">
          Start a report conversation
        </h2>
        <p className="mt-2 text-sm leading-6 text-d-muted">
          Choose a persona, generate its report, or add a fact for the next
          response.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 px-4 py-6 sm:px-6">
      {messages.map((message) => {
        const personaName =
          personaNames.get(message.persona_id) ?? message.persona_id;
        if (message.role === 'user') {
          return (
            <div key={message.message_id} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gold-500 px-4 py-3 text-sm leading-6 text-navy-950 sm:max-w-[70%]">
                {message.text}
              </div>
            </div>
          );
        }
        if (message.kind === 'report' && message.report) {
          return (
            <RichReportMessage
              key={message.message_id}
              messageId={message.message_id}
              personaName={personaName}
              report={message.report}
              onDownload={onDownload}
            />
          );
        }
        return (
          <div key={message.message_id} className="flex justify-start">
            <div
              className={`max-w-[85%] rounded-2xl rounded-bl-md border px-4 py-3 text-sm leading-6 sm:max-w-[75%] ${
                message.kind === 'error'
                  ? 'border-red-500/40 bg-red-500/10 text-red-200'
                  : 'border-d-border bg-d-card text-slate-200'
              }`}
            >
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-d-muted">
                {personaName}
              </p>
              {message.text}
            </div>
          </div>
        );
      })}
    </div>
  );
}
