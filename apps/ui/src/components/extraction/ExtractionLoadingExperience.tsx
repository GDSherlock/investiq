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
  state: 'processing' | 'completed';
}

export function ExtractionLoadingExperience({
  progress,
  stage,
  state,
}: ExtractionLoadingExperienceProps) {
  const currentStage = EXTRACTION_STAGES[getStageIndex(stage)];
  const completed = state === 'completed';
  const roundedProgress = Math.round(progress);
  const statusText = completed
    ? 'Model and calculation rules ready'
    : `${currentStage.title}, ${roundedProgress} percent complete`;

  return (
    <section className="mx-auto w-full max-w-5xl pb-8 pt-2 sm:pt-5">
      <header className="text-center">
        <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
          InvestIQ
        </h1>
        <p className="mt-3 text-sm text-slate-100 sm:text-lg">
          Uploading your financial model...
        </p>
      </header>

      <div className="mx-auto mt-8 max-w-4xl sm:mt-9">
        <ExtractionStageStepper stage={stage} completed={completed} />
      </div>

      <div className="mt-6 overflow-hidden rounded-xl border border-d-border bg-d-card/45 shadow-[0_24px_60px_rgba(0,0,0,0.18)] sm:mt-7 lg:grid lg:grid-cols-[minmax(0,1.65fr)_minmax(310px,0.9fr)]">
        <div className="min-w-0 p-5 sm:p-8">
          <div className="extraction-stage-transition" key={currentStage.id}>
            <h2 className="text-base font-semibold text-white sm:text-lg">
              {completed
                ? 'Model and calculation rules ready'
                : currentStage.title}
            </h2>
            <p className="mt-1 text-sm text-slate-300 sm:text-base">
              {completed
                ? 'Your financial model and calculation graph are ready'
                : currentStage.description}
            </p>
          </div>

          <WorkbookTransformation />

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
          <ProcessingActivityList stage={stage} completed={completed} />
        </aside>
      </div>

      <div className="mt-5 flex items-start gap-4 rounded-xl border border-d-border bg-d-card/70 px-5 py-4 sm:px-7 sm:py-5">
        <svg
          viewBox="0 0 24 24"
          className="mt-0.5 h-6 w-6 shrink-0 text-gold-400"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M9 18h6M10 22h4" />
          <path d="M8.2 14.7A7 7 0 1 1 15.8 14.7C14.7 15.4 14 16.5 14 18h-4c0-1.5-.7-2.6-1.8-3.3Z" />
        </svg>
        <div>
          <p className="text-sm font-semibold text-white sm:text-base">
            This may take a few minutes.
          </p>
          <p className="mt-1 text-sm text-slate-300">
            Larger models with more sheets and formulas will take longer.
          </p>
        </div>
      </div>

      <p className="sr-only" role="status" aria-live="polite">
        {statusText}
      </p>
    </section>
  );
}
