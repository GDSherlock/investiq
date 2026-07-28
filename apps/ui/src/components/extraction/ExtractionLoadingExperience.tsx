import {
  EXTRACTION_STAGES,
  getStageIndex,
  type ExtractionStage,
} from '../../lib/extractionProgress';
import { ExtractionStageStepper } from './ExtractionStageStepper';
import { ProcessingActivityList } from './ProcessingActivityList';
import { WorkbookTransformation } from './WorkbookTransformation';

interface ExtractionLoadingExperienceProps {
  progress: number;
  stage: ExtractionStage;
  state: 'idle' | 'processing' | 'completed' | 'failed';
}

export function ExtractionLoadingExperience({
  progress,
  stage,
  state,
}: ExtractionLoadingExperienceProps) {
  const currentStage = EXTRACTION_STAGES[getStageIndex(stage)];
  const completed = state === 'completed';
  const failed = state === 'failed';
  const idle = state === 'idle';
  const roundedProgress = Math.round(progress);
  const statusText = completed
    ? 'Model and calculation rules ready'
    : failed
      ? `Model preparation stopped during ${currentStage.label}`
      : idle
        ? 'Ready for your workbook'
    : `${currentStage.title}, ${roundedProgress} percent complete`;

  return (
    <section className="w-full">
      <div className="mx-auto max-w-4xl">
        <ExtractionStageStepper stage={stage} state={state} />
      </div>

      <div className="mt-6 overflow-hidden rounded-xl border border-d-border bg-d-card/45 shadow-[0_24px_60px_rgba(0,0,0,0.18)] sm:mt-7 lg:grid lg:grid-cols-[minmax(0,1.65fr)_minmax(310px,0.9fr)]">
        <div className="min-w-0 p-5 sm:p-8">
          <div className="extraction-stage-transition" key={currentStage.id}>
            <h2 className="text-base font-semibold text-white sm:text-lg">
              {completed
                ? 'Model and calculation rules ready'
                : failed
                  ? 'Model preparation stopped'
                  : idle
                    ? 'Ready for your workbook'
                    : currentStage.title}
            </h2>
            <p className="mt-1 text-sm text-slate-300 sm:text-base">
              {completed
                ? 'Your financial model and calculation graph are ready'
                : failed
                  ? 'Review the notification below, then retry or choose another workbook'
                  : idle
                    ? 'Choose an .xlsx workbook to begin upload and analysis'
                    : currentStage.description}
            </p>
          </div>

          <div className={idle || failed ? 'opacity-70' : undefined}>
            <WorkbookTransformation />
          </div>

          <div className="mt-1">
            <div className="flex items-end justify-between gap-4">
              <span className="text-sm font-semibold text-white sm:text-base">
                Estimated progress
              </span>
              <span className="text-2xl font-bold tabular-nums text-gold-400 sm:text-3xl">
                {roundedProgress}%
              </span>
            </div>
            <div
              className="mt-3 h-3 overflow-hidden rounded-full bg-slate-600/50 sm:h-4"
              role="progressbar"
              aria-label="Estimated model preparation progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={roundedProgress}
            >
              <div
                className="extraction-progress-fill h-full rounded-full bg-gradient-to-r from-gold-500 via-gold-400 to-gold-300 shadow-[0_0_18px_rgba(197,160,89,0.24)]"
                style={{ width: `${Math.min(100, roundedProgress)}%` }}
              />
            </div>
          </div>
        </div>

        <aside className="border-t border-d-border p-5 sm:p-8 lg:border-l lg:border-t-0">
          <ProcessingActivityList stage={stage} state={state} />
        </aside>
      </div>

      <p className="sr-only" role="status" aria-live="polite">
        {statusText}
      </p>
    </section>
  );
}
