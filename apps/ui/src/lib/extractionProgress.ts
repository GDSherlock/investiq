export const EXTRACTION_STAGES = [
  {
    id: 'upload',
    label: 'Upload',
    title: 'Uploading workbook',
    description: 'Preparing the file for analysis',
  },
  {
    id: 'inspect',
    label: 'Inspect',
    title: 'Inspecting workbook structure',
    description: 'Reading sheets, formulas and model relationships',
  },
  {
    id: 'extract',
    label: 'Extract',
    title: 'Extracting financial data',
    description: 'Organising assumptions, outputs and time series',
  },
  {
    id: 'validate',
    label: 'Validate',
    title: 'Validating extraction',
    description: 'Checking consistency and data quality',
  },
  {
    id: 'finalize',
    label: 'Finalize',
    title: 'Finalizing your model',
    description: 'Preparing the extracted model for review',
  },
] as const;

export type ExtractionStage = (typeof EXTRACTION_STAGES)[number]['id'];
export type ProgressPhase = 'processing' | 'completing' | 'completed';

export interface ProgressSnapshot {
  progress: number;
  stage: ExtractionStage;
  phase: ProgressPhase;
}

export interface AnimationScheduler {
  now: () => number;
  request: (callback: (timestamp: number) => void) => number;
  cancel: (requestId: number) => void;
  isHidden?: () => boolean;
}

export interface ProgressDriver {
  complete: () => Promise<void>;
  stop: () => void;
}

interface CreateProgressDriverOptions {
  onUpdate: (snapshot: ProgressSnapshot) => void;
  reducedMotion?: boolean;
  scheduler?: AnimationScheduler;
  completionDurationMs?: number;
}

const SIMULATION_CAP = 92;
const COMPLETION_DURATION_MS = 750;

function interpolate(
  elapsedMs: number,
  startMs: number,
  endMs: number,
  startProgress: number,
  endProgress: number,
): number {
  const ratio = (elapsedMs - startMs) / (endMs - startMs);
  return startProgress + (endProgress - startProgress) * ratio;
}

export function getSimulatedProgress(elapsedMs: number): number {
  const elapsed = Math.max(0, elapsedMs);

  if (elapsed <= 3_000) {
    return interpolate(elapsed, 0, 3_000, 0, 12);
  }
  if (elapsed <= 12_000) {
    return interpolate(elapsed, 3_000, 12_000, 12, 30);
  }
  if (elapsed <= 35_000) {
    return interpolate(elapsed, 12_000, 35_000, 30, 58);
  }
  if (elapsed <= 70_000) {
    return interpolate(elapsed, 35_000, 70_000, 58, 78);
  }
  if (elapsed <= 100_000) {
    return interpolate(elapsed, 70_000, 100_000, 78, 88);
  }

  const tailProgress = 88 + 4 * (1 - Math.exp(-(elapsed - 100_000) / 60_000));
  return Math.min(SIMULATION_CAP, tailProgress);
}

export function getStageForElapsed(elapsedMs: number): ExtractionStage {
  const elapsed = Math.max(0, elapsedMs);

  if (elapsed < 3_000) return 'upload';
  if (elapsed < 12_000) return 'inspect';
  if (elapsed < 70_000) return 'extract';
  if (elapsed < 100_000) return 'validate';
  return 'finalize';
}

export function getStageIndex(stage: ExtractionStage): number {
  return EXTRACTION_STAGES.findIndex((candidate) => candidate.id === stage);
}

function createBrowserScheduler(): AnimationScheduler {
  return {
    now: () => performance.now(),
    request: (callback) => window.requestAnimationFrame(callback),
    cancel: (requestId) => window.cancelAnimationFrame(requestId),
    isHidden: () => document.visibilityState === 'hidden',
  };
}

function roundProgress(progress: number): number {
  return Math.round(progress * 10) / 10;
}

export function createProgressDriver({
  onUpdate,
  reducedMotion = false,
  scheduler = createBrowserScheduler(),
  completionDurationMs = COMPLETION_DURATION_MS,
}: CreateProgressDriverOptions): ProgressDriver {
  const simulationStartedAt = scheduler.now();
  let frameId: number | null = null;
  let stopped = false;
  let lastProgress = 0;
  let lastStage: ExtractionStage = 'upload';
  let completionPromise: Promise<void> | null = null;
  let resolveCompletion: (() => void) | null = null;

  const cancelScheduledFrame = () => {
    if (frameId !== null) {
      scheduler.cancel(frameId);
      frameId = null;
    }
  };

  const emit = (
    progress: number,
    stage: ExtractionStage,
    phase: ProgressPhase,
    force = false,
  ) => {
    const nextProgress = roundProgress(Math.max(lastProgress, progress));
    const nextStageIndex = Math.max(getStageIndex(lastStage), getStageIndex(stage));
    const nextStage = EXTRACTION_STAGES[nextStageIndex].id;
    const changed = (
      nextProgress !== lastProgress
      || nextStage !== lastStage
      || phase !== 'processing'
    );

    lastProgress = nextProgress;
    lastStage = nextStage;
    if (force || changed) {
      onUpdate({ progress: nextProgress, stage: nextStage, phase });
    }
  };

  const scheduleSimulationFrame = () => {
    if (stopped) return;
    frameId = scheduler.request((timestamp) => {
      frameId = null;
      if (stopped) return;

      if (!scheduler.isHidden?.()) {
        const elapsed = Math.max(0, timestamp - simulationStartedAt);
        emit(
          Math.min(SIMULATION_CAP, getSimulatedProgress(elapsed)),
          getStageForElapsed(elapsed),
          'processing',
        );
      }
      scheduleSimulationFrame();
    });
  };

  emit(0, 'upload', 'processing', true);
  scheduleSimulationFrame();

  const complete = (): Promise<void> => {
    if (completionPromise) return completionPromise;
    if (stopped) return Promise.resolve();

    cancelScheduledFrame();

    if (reducedMotion) {
      emit(100, 'finalize', 'completed', true);
      return Promise.resolve();
    }

    const completionStartedAt = scheduler.now();
    const completionStartedFrom = lastProgress;
    completionPromise = new Promise<void>((resolve) => {
      resolveCompletion = resolve;
    });

    const scheduleCompletionFrame = () => {
      frameId = scheduler.request((timestamp) => {
        frameId = null;
        if (stopped) return;

        const ratio = Math.min(
          1,
          Math.max(0, (timestamp - completionStartedAt) / completionDurationMs),
        );
        const easedRatio = 1 - Math.pow(1 - ratio, 3);
        const progress = completionStartedFrom
          + (100 - completionStartedFrom) * easedRatio;
        emit(
          ratio === 1 ? 100 : progress,
          'finalize',
          ratio === 1 ? 'completed' : 'completing',
          true,
        );

        if (ratio === 1) {
          resolveCompletion?.();
          resolveCompletion = null;
          return;
        }
        scheduleCompletionFrame();
      });
    };

    scheduleCompletionFrame();
    return completionPromise;
  };

  const stop = () => {
    if (stopped) return;
    stopped = true;
    cancelScheduledFrame();
    resolveCompletion?.();
    resolveCompletion = null;
  };

  return { complete, stop };
}
