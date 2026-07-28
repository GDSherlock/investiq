import { getStageIndex, type ExtractionStage } from '../../lib/extractionProgress';

const ACTIVITIES = [
  {
    title: 'Inspecting workbook',
    description: 'Identifying sheets and ranges',
  },
  {
    title: 'Extracting financial data',
    description: 'Finding assumptions and outputs',
  },
  {
    title: 'Validating extraction',
    description: 'Checking consistency and quality',
  },
  {
    title: 'Preparing calculation model',
    description: 'Extracting rules and compiling the graph',
  },
] as const;

interface ProcessingActivityListProps {
  stage: ExtractionStage;
  state: 'idle' | 'processing' | 'completed' | 'failed';
}

export function ProcessingActivityList({
  stage,
  state,
}: ProcessingActivityListProps) {
  const activeIndex = Math.max(0, getStageIndex(stage) - 1);

  return (
    <div>
      <h3 className="text-base font-semibold text-white sm:text-lg">
        What we&apos;re doing
      </h3>
      <ol className="mt-5 space-y-0">
        {ACTIVITIES.map((activity, index) => {
          const isCompleted =
            state === 'completed' ||
            (state !== 'idle' && index < activeIndex);
          const isActive = state === 'processing' && index === activeIndex;
          const isFailed = state === 'failed' && index === activeIndex;

          return (
            <li
              key={activity.title}
              className="relative grid grid-cols-[28px_1fr] gap-3 pb-6 last:pb-0"
            >
              {index < ACTIVITIES.length - 1 && (
                <span
                  aria-hidden="true"
                  className={`absolute bottom-0 left-[13px] top-6 w-px ${
                    isCompleted ? 'bg-gold-500/60' : 'bg-d-border'
                  }`}
                />
              )}
              <span
                className={`relative mt-0.5 flex h-6 w-6 items-center justify-center rounded-full border-2 ${
                  isFailed
                    ? 'border-red-400 bg-red-500/15'
                    : isCompleted
                    ? 'border-emerald-400 bg-emerald-400/15'
                    : isActive
                      ? 'border-gold-400 bg-gold-500/10'
                      : 'border-slate-600 bg-d-card'
                }`}
                aria-hidden="true"
              >
                {isCompleted ? (
                  <svg
                    viewBox="0 0 20 20"
                    className="h-3.5 w-3.5 text-emerald-400"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m4 10 4 4 8-9" />
                  </svg>
                ) : isFailed ? (
                  <span className="text-xs font-bold text-red-300">!</span>
                ) : isActive ? (
                  <span className="h-2 w-2 rounded-full bg-gold-400" />
                ) : null}
              </span>

              <div>
                <div
                  className={`text-sm font-medium ${
                    isFailed
                      ? 'text-red-200'
                      : isActive
                      ? 'text-white'
                      : isCompleted
                        ? 'text-slate-200'
                        : 'text-slate-400'
                  }`}
                >
                  {activity.title}
                  <span className="sr-only">
                    {isCompleted
                      ? ', completed'
                      : isFailed
                        ? ', failed'
                        : isActive
                          ? ', in progress'
                          : ', pending'}
                  </span>
                </div>
                <div
                  className={`mt-1 text-xs leading-5 sm:text-sm ${
                    isFailed
                      ? 'text-red-300'
                      : isActive
                        ? 'text-slate-300'
                        : 'text-slate-400'
                  }`}
                >
                  {activity.description}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
