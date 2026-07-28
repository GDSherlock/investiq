import {
  EXTRACTION_STAGES,
  getStageIndex,
  type ExtractionStage,
} from '../../lib/extractionProgress';

interface ExtractionStageStepperProps {
  stage: ExtractionStage;
  state: 'idle' | 'processing' | 'completed' | 'failed';
}

export function ExtractionStageStepper({
  stage,
  state,
}: ExtractionStageStepperProps) {
  const activeIndex = getStageIndex(stage);

  return (
    <ol
      className="grid grid-cols-5 gap-0"
      aria-label="Model extraction stages"
    >
      {EXTRACTION_STAGES.map((item, index) => {
        const isCompleted =
          state === 'completed' ||
          (state !== 'idle' && index < activeIndex);
        const isActive = state === 'processing' && index === activeIndex;
        const isFailed = state === 'failed' && index === activeIndex;
        const connectorCompleted =
          state === 'completed' ||
          (state !== 'idle' && index < activeIndex);
        const status = isCompleted
          ? 'Completed'
          : isFailed
            ? 'Failed'
          : isActive
            ? 'In Progress'
            : 'Pending';

        return (
          <li
            key={item.id}
            className="relative min-w-0 text-center"
            aria-current={isActive ? 'step' : undefined}
          >
            {index < EXTRACTION_STAGES.length - 1 && (
              <span
                aria-hidden="true"
                className={`absolute left-[calc(50%+1.25rem)] right-[calc(-50%+1.25rem)] top-[1.1rem] h-px border-t ${
                  connectorCompleted
                    ? 'border-solid border-gold-400'
                    : 'border-dashed border-slate-600'
                }`}
              />
            )}

            <div className="relative z-10 mx-auto flex h-9 w-9 items-center justify-center rounded-full">
              <span
                className={`flex h-8 w-8 items-center justify-center rounded-full border text-sm font-semibold transition-colors sm:h-9 sm:w-9 ${
                  isFailed
                    ? 'border-red-400 bg-red-500/15 text-red-200'
                    : isCompleted
                      ? 'border-emerald-400 bg-emerald-500/10 text-emerald-300'
                      : isActive
                        ? 'border-gold-400 bg-gold-500 text-white shadow-[0_0_18px_rgba(197,160,89,0.22)]'
                    : 'border-slate-400 bg-d-bg text-slate-200'
                }`}
              >
                {isCompleted ? (
                  <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="m4 10 4 4 8-9" />
                  </svg>
                ) : isFailed ? (
                  '!'
                ) : (
                  index + 1
                )}
              </span>
            </div>

            <div
              className={`mt-2 truncate text-[11px] font-semibold sm:text-sm ${
                isFailed
                  ? 'text-red-200'
                  : isActive || isCompleted
                    ? 'text-white'
                    : 'text-slate-300'
              }`}
            >
              {item.label}
            </div>
            <div
              className={`mt-1 truncate text-[9px] sm:text-xs ${
                isCompleted
                  ? 'text-emerald-400'
                  : isFailed
                    ? 'text-red-300'
                  : isActive
                    ? 'text-gold-400'
                    : 'text-slate-400'
              }`}
            >
              {status}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
