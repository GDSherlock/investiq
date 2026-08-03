'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  CalculationPreparationPanel,
  type CalculationPreparationLifecycle,
} from '@/components/calculation/CalculationPreparationPanel';
import { CalculationRunSummary } from '@/components/calculation/CalculationRunSummary';
import { PreparationNotifications } from '@/components/calculation/PreparationNotifications';
import { ExtractionLoadingExperience } from '@/components/extraction/ExtractionLoadingExperience';
import { HistoricalModelSelector } from '@/components/model-history/HistoricalModelSelector';
import {
  ModelSourceSwitcher,
  type ModelSourceMode,
} from '@/components/model-history/ModelSourceSwitcher';
import { WorkbookUploadZone } from '@/components/extraction/WorkbookUploadZone';
import { getModelHistory, uploadWorkbookForCalculation } from '@/lib/api';
import {
  CalculationApiError,
  type HistoricalModelItem,
  type WorkbookValidationResponse,
} from '@/lib/calculation-api-types';
import { canStartCalculationFlow } from '@/lib/calculation-flow';
import {
  clearCalculationArtifacts,
  persistHistoricalModelIdentity,
  persistUploadIdentity,
  readRestorableCalculationIdentity,
} from '@/lib/calculation-storage';
import {
  createProgressDriver,
  type ProgressDriver,
  type ProgressSnapshot,
} from '@/lib/extractionProgress';
import {
  buildPreparationNotifications,
  buildTechnicalDetails,
  validateWorkbookFile,
} from '@/lib/model-preparation-view';

import { useActiveAnalysis } from './ActiveAnalysisContext';

interface ActiveCalculationIdentity {
  modelVersionId: string;
  workbookVersionId: string;
  source: 'storage' | 'upload';
}

type PreparationPageState =
  | 'idle'
  | 'processing'
  | 'completed'
  | 'failed';

function createUploadError(
  status: number,
  code: string,
  message: string,
  retryable: boolean,
): CalculationApiError {
  return new CalculationApiError(status, {
    code,
    message,
    retryable,
    resource_id: null,
  });
}

export default function HomePage() {
  const { refresh: refreshActiveAnalysis } = useActiveAnalysis();
  const [modelSourceMode, setModelSourceMode] =
    useState<ModelSourceMode>('upload');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [pageState, setPageState] =
    useState<PreparationPageState>('idle');
  const [uploadInFlight, setUploadInFlight] = useState(false);
  const [uploadResult, setUploadResult] =
    useState<WorkbookValidationResponse | null>(null);
  const [uploadError, setUploadError] = useState<Error | null>(null);
  const [activeIdentity, setActiveIdentity] =
    useState<ActiveCalculationIdentity | null>(null);
  const [historicalModels, setHistoricalModels] = useState<
    HistoricalModelItem[]
  >([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [selectedHistoricalModelId, setSelectedHistoricalModelId] =
    useState<string | null>(null);
  const [historySelectionCommitted, setHistorySelectionCommitted] =
    useState(false);
  const [progressSnapshot, setProgressSnapshot] = useState<ProgressSnapshot>({
    progress: 0,
    stage: 'upload',
    phase: 'processing',
  });

  const activeDriverRef = useRef<ProgressDriver | null>(null);
  const uploadInFlightRef = useRef(false);
  const uploadRevisionRef = useRef(0);
  const historyRevisionRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    // Keep legacy navigation storage intact. Calculation APIs only use the
    // versioned identity read below and never consume investiq_model_id.
    const migrations: [string, string][] = [
      ['projagent_model_id', 'investiq_model_id'],
      ['projagent_investment_id', 'investiq_investment_id'],
      ['projagent_persona', 'investiq_persona'],
    ];
    for (const [oldKey, newKey] of migrations) {
      const value = localStorage.getItem(oldKey);
      if (value && !localStorage.getItem(newKey)) {
        localStorage.setItem(newKey, value);
      }
      localStorage.removeItem(oldKey);
    }

    const persisted = readRestorableCalculationIdentity(localStorage);
    if (persisted) {
      setProgressSnapshot({
        progress: 92,
        stage: 'prepare',
        phase: 'processing',
      });
      setPageState('processing');
      setActiveIdentity({
        modelVersionId: persisted.modelVersionId,
        workbookVersionId: persisted.workbookVersionId,
        source: 'storage',
      });
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      uploadRevisionRef.current += 1;
      historyRevisionRef.current += 1;
      activeDriverRef.current?.stop();
      activeDriverRef.current = null;
    };
  }, []);

  const loadHistoricalModels = useCallback(async () => {
    const requestRevision = ++historyRevisionRef.current;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const response = await getModelHistory();
      if (
        mountedRef.current &&
        requestRevision === historyRevisionRef.current
      ) {
        setHistoricalModels(response.models);
        setSelectedHistoricalModelId((current) =>
          response.models.some(
            (model) => model.model_version_id === current,
          )
            ? current
            : response.models[0]?.model_version_id ?? null,
        );
      }
    } catch (caught) {
      if (
        mountedRef.current &&
        requestRevision === historyRevisionRef.current
      ) {
        setHistoricalModels([]);
        setHistoryError(
          caught instanceof Error
            ? caught
            : new Error('Prepared models could not be loaded.'),
        );
      }
    } finally {
      if (
        mountedRef.current &&
        requestRevision === historyRevisionRef.current
      ) {
        setHistoryLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (modelSourceMode === 'history' && !historySelectionCommitted) {
      void loadHistoricalModels();
    }
  }, [historySelectionCommitted, loadHistoricalModels, modelSourceMode]);

  const handlePreparationLifecycle = useCallback(
    (lifecycle: CalculationPreparationLifecycle) => {
      if (!mountedRef.current) {
        return;
      }
      if (lifecycle === 'processing') {
        setPageState('processing');
        if (!activeDriverRef.current) {
          setProgressSnapshot({
            progress: 92,
            stage: 'prepare',
            phase: 'processing',
          });
        }
        return;
      }
      if (lifecycle === 'failed') {
        activeDriverRef.current?.stop();
        activeDriverRef.current = null;
        setPageState('failed');
        setProgressSnapshot((current) => ({
          progress: current.progress,
          stage: 'prepare',
          phase: 'processing',
        }));
        return;
      }

      const driver = activeDriverRef.current;
      if (!driver) {
        setProgressSnapshot({
          progress: 100,
          stage: 'prepare',
          phase: 'completed',
        });
        setPageState('completed');
        return;
      }
      void driver.complete().then(() => {
        if (mountedRef.current && activeDriverRef.current === driver) {
          activeDriverRef.current = null;
          setPageState('completed');
        }
      });
    },
    [],
  );

  const startUpload = useCallback(async (file: File) => {
    if (uploadInFlightRef.current) {
      return;
    }

    setSelectedFile(file);
    const validationError = validateWorkbookFile(file);
    if (validationError) {
      setUploadResult(null);
      setActiveIdentity(null);
      setUploadError(
        createUploadError(
          400,
          validationError.code,
          validationError.message,
          false,
        ),
      );
      setProgressSnapshot({
        progress: 0,
        stage: 'upload',
        phase: 'processing',
      });
      setPageState('failed');
      return;
    }

    const requestRevision = ++uploadRevisionRef.current;
    uploadInFlightRef.current = true;
    setUploadInFlight(true);
    activeDriverRef.current?.stop();
    setUploadResult(null);
    setUploadError(null);
    setActiveIdentity(null);
    setPageState('processing');
    setProgressSnapshot({
      progress: 0,
      stage: 'upload',
      phase: 'processing',
    });

    const progress = createProgressDriver({
      onUpdate: (snapshot) => {
        if (
          mountedRef.current &&
          requestRevision === uploadRevisionRef.current
        ) {
          setProgressSnapshot(snapshot);
        }
      },
      reducedMotion: window.matchMedia(
        '(prefers-reduced-motion: reduce)',
      ).matches,
    });
    activeDriverRef.current = progress;

    try {
      await clearCalculationArtifacts(localStorage);
      const response = await uploadWorkbookForCalculation(file);
      if (
        !mountedRef.current ||
        requestRevision !== uploadRevisionRef.current
      ) {
        return;
      }
      setUploadResult(response);
      if (!canStartCalculationFlow(response)) {
        throw createUploadError(
          422,
          response.stop_reason || 'UPLOAD_REJECTED',
          'The workbook stopped before model submission.',
          false,
        );
      }

      progress.waitForPreparation();
      await persistUploadIdentity(localStorage, response);
      if (
        !mountedRef.current ||
        requestRevision !== uploadRevisionRef.current
      ) {
        return;
      }
      setActiveIdentity({
        modelVersionId: response.model_version_id,
        workbookVersionId: response.workbook_version_id,
        source: 'upload',
      });
    } catch (caught) {
      if (
        mountedRef.current &&
        requestRevision === uploadRevisionRef.current
      ) {
        progress.stop();
        if (activeDriverRef.current === progress) {
          activeDriverRef.current = null;
        }
        setUploadError(
          caught instanceof Error
            ? caught
            : new Error('Workbook upload failed.'),
        );
        setPageState('failed');
      }
    } finally {
      if (
        mountedRef.current &&
        requestRevision === uploadRevisionRef.current
      ) {
        uploadInFlightRef.current = false;
        setUploadInFlight(false);
      }
    }
  }, []);

  const continueWithHistoricalModel = useCallback(
    async (model: HistoricalModelItem) => {
      setHistoryError(null);
      try {
        await persistHistoricalModelIdentity(localStorage, model);
        if (!mountedRef.current) {
          return;
        }
        setSelectedFile(null);
        setUploadResult(null);
        setUploadError(null);
        setActiveIdentity({
          modelVersionId: model.model_version_id,
          workbookVersionId: model.workbook_version_id,
          source: 'storage',
        });
        setProgressSnapshot({
          progress: 92,
          stage: 'prepare',
          phase: 'processing',
        });
        setPageState('processing');
        setHistorySelectionCommitted(true);
        void refreshActiveAnalysis();
      } catch (caught) {
        if (mountedRef.current) {
          setHistoryError(
            caught instanceof Error
              ? caught
              : new Error('The selected model could not be restored.'),
          );
        }
      }
    },
    [refreshActiveAnalysis],
  );

  const notifications = activeIdentity
    ? []
    : buildPreparationNotifications({
        uploadResult,
        readiness: null,
        activeRun: null,
        error: uploadError,
        stateNotice: null,
      });
  const technicalDetails = buildTechnicalDetails({
    uploadResult,
    readiness: null,
    baselineRun: null,
    overrideRun: null,
  });
  const hasFailure = pageState === 'failed';
  const canRetryUpload =
    uploadError instanceof CalculationApiError &&
    uploadError.retryable;
  const showCalculationFlow =
    modelSourceMode === 'upload' || historySelectionCommitted;

  const changeModelSource = useCallback((mode: ModelSourceMode) => {
    if (uploadInFlightRef.current) {
      return;
    }
    setModelSourceMode(mode);
    setHistorySelectionCommitted(false);
    if (mode === 'history') {
      setHistoryError(null);
    }
  }, []);

  return (
    <main className="mx-auto max-w-6xl space-y-5 pb-10 sm:space-y-6">
      <header className="pb-1 pt-7 text-center sm:pt-10">
        <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
          InvestIQ
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-sm text-slate-200 sm:text-base">
          Upload your financial model. We&apos;ll analyze it and prepare the
          calculation APIs.
        </p>
      </header>

      <ModelSourceSwitcher
        mode={modelSourceMode}
        onModeChange={changeModelSource}
      />

      {modelSourceMode === 'history' && !historySelectionCommitted ? (
        <HistoricalModelSelector
          models={historicalModels}
          loading={historyLoading}
          error={historyError}
          selectedModelId={selectedHistoricalModelId}
          onSelectedModelIdChange={setSelectedHistoricalModelId}
          onContinue={(model) => void continueWithHistoricalModel(model)}
          onRetry={() => void loadHistoricalModels()}
          onUseUpload={() => changeModelSource('upload')}
        />
      ) : null}

      {showCalculationFlow ? (
        <>
          {modelSourceMode === 'upload' ? (
            <WorkbookUploadZone
              selectedFile={selectedFile}
              busy={uploadInFlight}
              hasError={hasFailure}
              canRetry={canRetryUpload}
              onFileSelected={(file) => void startUpload(file)}
              onRetry={() => {
                if (selectedFile && canRetryUpload) {
                  void startUpload(selectedFile);
                }
              }}
            />
          ) : null}

          <ExtractionLoadingExperience
            progress={progressSnapshot.progress}
            stage={progressSnapshot.stage}
            state={pageState}
          />

          {activeIdentity ? (
            <CalculationPreparationPanel
              key={`${activeIdentity.modelVersionId}:${activeIdentity.workbookVersionId}`}
              modelVersionId={activeIdentity.modelVersionId}
              workbookVersionId={activeIdentity.workbookVersionId}
              restoreFromStorage={activeIdentity.source === 'storage'}
              uploadResult={uploadResult}
              onLifecycleChange={handlePreparationLifecycle}
            />
          ) : (
            <>
              <CalculationRunSummary
                readiness={null}
                phaseLabel={
                  pageState === 'failed'
                    ? 'Failed'
                    : pageState === 'processing'
                      ? 'Processing'
                      : 'Waiting'
                }
                hasWarnings={notifications.some(
                  ({ severity }) => severity === 'warning',
                )}
                hasError={hasFailure}
                details={technicalDetails}
              />
              <PreparationNotifications notifications={notifications} />
            </>
          )}
        </>
      ) : null}

      <p className="flex items-center justify-center gap-2 pt-2 text-center text-xs text-d-muted sm:text-sm">
        <span aria-hidden="true">▣</span>
        Your data is secure and private. We never store your file permanently.
      </p>
    </main>
  );
}
