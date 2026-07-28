import type { TechnicalDetail } from '../../lib/model-preparation-view';

interface TechnicalDetailsProps {
  details: TechnicalDetail[];
}

export function TechnicalDetails({ details }: TechnicalDetailsProps) {
  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md border border-d-border px-4 py-2 text-sm font-medium text-white transition hover:bg-d-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-gold-400">
        <span>View details</span>
        <svg
          viewBox="0 0 20 20"
          className="h-4 w-4 transition-transform group-open:rotate-180"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m5 7 5 5 5-5" />
        </svg>
      </summary>

      <dl className="mt-4 grid gap-x-8 gap-y-3 border-t border-d-border pt-4 text-sm sm:grid-cols-2">
        {details.length > 0 ? (
          details.map(({ label, value }) => (
            <div key={`${label}:${value}`} className="min-w-0">
              <dt className="text-d-muted">{label}</dt>
              <dd className="mt-0.5 break-all font-mono text-xs text-slate-200">
                {value}
              </dd>
            </div>
          ))
        ) : (
          <div>
            <dt className="sr-only">Details</dt>
            <dd className="text-d-muted">No technical details available.</dd>
          </div>
        )}
      </dl>
    </details>
  );
}
