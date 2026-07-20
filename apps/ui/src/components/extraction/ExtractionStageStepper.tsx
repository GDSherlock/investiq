import {
  EXTRACTION_STAGES,
  getStageIndex,
  type ExtractionStage,
} from '../../lib/extractionProgress';

interface ExtractionStageStepperProps {
  stage: ExtractionStage;
  completed: boolean;
}

export function ExtractionStageStepper({
  stage,
  completed,
}: ExtractionStageStepperProps) {
  const activeIndex = getStageIndex(stage);

  return (
    <ol
      className="grid grid-cols-5 gap-0"
      aria-label="Model extraction stages"
    >
      {EXTRACTION_STAGES.map((item, index) => {
        const isCompleted = completed || index < activeIndex;
        const isActive = !completed && index === activeIndex;
        const connectorCompleted = completed || index < activeIndex;
        const status = isCompleted
          ? 'Completed'
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
                  isCompleted || isActive
                    ? 'border-gold-400 bg-gold-500 text-white shadow-[0_0_18px_rgba(197,160,89,0.22)]'
                    : 'border-slate-400 bg-d-bg text-slate-200'
                }`}
              >
                {index + 1}
              </span>
            </div>

            <div
              className={`mt-2 truncate text-[11px] font-semibold sm:text-sm ${
                isActive || isCompleted ? 'text-white' : 'text-slate-300'
              }`}
            >
              {item.label}
            </div>
            <div
              className={`mt-1 truncate text-[9px] sm:text-xs ${
                isCompleted
                  ? 'text-green-400'
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
