'use client';

import { useEffect, useState } from 'react';

import type { PreparationNotification } from '../../lib/model-preparation-view';
import { formatUiNumber } from '../../lib/ui-number-format';

interface PreparationNotificationsProps {
  notifications: PreparationNotification[];
}

function NotificationIcon({
  severity,
}: {
  severity: PreparationNotification['severity'];
}) {
  if (severity === 'error') {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full border border-red-400 text-sm font-bold text-red-300">
        !
      </span>
    );
  }
  if (severity === 'info') {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full border border-blue-400 text-xs font-bold text-blue-300">
        i
      </span>
    );
  }
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6 text-amber-400" aria-hidden="true">
      <path d="M12 3 2.8 20h18.4L12 3Z" fill="currentColor" />
      <path d="M12 8v5M12 16.5v.1" fill="none" stroke="#0b1437" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function PreparationNotifications({
  notifications,
}: PreparationNotificationsProps) {
  const hasBlockingError = notifications.some(
    ({ severity }) => severity === 'error',
  );
  const [open, setOpen] = useState(hasBlockingError);

  useEffect(() => {
    if (hasBlockingError) {
      setOpen(true);
    }
  }, [hasBlockingError]);

  return (
    <details
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className="group rounded-xl border border-d-border bg-d-card/45 shadow-[0_18px_50px_rgba(0,0,0,0.12)]"
    >
      <summary className="flex cursor-pointer list-none items-center gap-4 px-5 py-5 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-gold-400 sm:px-7">
        <svg viewBox="0 0 24 24" className="h-7 w-7 shrink-0 text-amber-400" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
          <path d="M10 21h4" />
        </svg>
        <span className="text-base font-semibold text-white sm:text-lg">
          Notifications ({notifications.length})
        </span>
        <span className="ml-auto text-xs font-medium text-d-muted group-open:hidden">
          View all
        </span>
        <svg viewBox="0 0 20 20" className="h-5 w-5 text-slate-300 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m5 7 5 5 5-5" />
        </svg>
      </summary>

      <div className="border-t border-d-border px-5 py-5 sm:px-7">
        {notifications.length > 0 ? (
          <ul className="space-y-5">
            {notifications.map((notification) => (
              <li
                key={notification.id}
                className="grid grid-cols-[28px_minmax(0,1fr)] gap-3"
              >
                <NotificationIcon severity={notification.severity} />
                <div className="min-w-0">
                  <div
                    className={`break-words text-sm font-medium ${
                      notification.severity === 'error'
                        ? 'text-red-200'
                        : notification.severity === 'info'
                          ? 'text-blue-200'
                          : 'text-white'
                    }`}
                  >
                    {notification.code}
                    {notification.count !== null
                      ? ` (${formatUiNumber(notification.count, {
                          maximumFractionDigits: 0,
                        })})`
                      : ''}
                  </div>
                  <p className="mt-1 text-sm leading-5 text-d-muted">
                    {notification.message}
                  </p>
                  {notification.retryable !== null ? (
                    <p className="mt-1 text-xs text-slate-300">
                      {notification.retryable
                        ? 'Retry available'
                        : 'Do not retry immediately'}
                    </p>
                  ) : null}
                  {notification.resourceId ? (
                    <p className="mt-1 break-all font-mono text-[11px] text-d-dim">
                      Resource: {notification.resourceId}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-d-muted">
            No warnings or errors for the current model.
          </p>
        )}
      </div>
    </details>
  );
}
