'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { CalculationPreparationPanel } from '@/components/calculation/CalculationPreparationPanel';
import { ExtractionLoadingExperience } from '@/components/extraction/ExtractionLoadingExperience';
import { uploadWorkbookForCalculation } from '@/lib/api';
import {
  CalculationApiError,
  type CalculationUiPhase,
  type WorkbookValidationResponse,
} from '@/lib/calculation-api-types';
import { canStartCalculationFlow } from '@/lib/calculation-flow';
import {
  CALCULATION_STORAGE_KEYS,
  clearCalculationArtifacts,
  persistUploadIdentity,
  readRestorableCalculationIdentity,
} from '@/lib/calculation-storage';
import {
  createProgressDriver,
  type ProgressDriver,
  type ProgressSnapshot,
} from '@/lib/extractionProgress';
import { runUploadAttempt } from '@/lib/uploadAttempt';

interface ActiveCalculationIdentity {
  modelVersionId: string;
  workbookVersionId: string;
  source: 'storage' | 'upload';
}

function UploadErrorDetails({ error }: { error: Error }) {
  if (error instanceof CalculationApiError) {
    return (
      <dl className="mt-2 grid gap-1 font-mono text-xs">
        <div>
          <dt className="inline text-red-300">code: </dt>
          <dd className="inline">{error.code}</dd>
        </div>
        <div>
          <dt className="inline text-red-300">message: </dt>
          <dd className="inline">{error.message}</dd>
        </div>
        <div>
          <dt className="inline text-red-300">retryable: </dt>
          <dd className="inline">{String(error.retryable)}</dd>
        </div>
        <div>
          <dt className="inline text-red-300">resource_id: </dt>
          <dd className="inline">{error.resourceId ?? 'null'}</dd>
        </div>
      </dl>
    );
  }
  return <p className="mt-2 text-sm">{error.message}</p>;
}

export default function HomePage() {
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<CalculationUiPhase>('idle');
  const [uploadResult, setUploadResult] =
    useState<WorkbookValidationResponse | null>(null);
  const [uploadError, setUploadError] = useState<Error | null>(null);
  const [activeIdentity, setActiveIdentity] =
    useState<ActiveCalculationIdentity | null>(null);
  const [loadingState, setLoadingState] =
    useState<'processing' | 'completed'>('processing');
  const [progressSnapshot, setProgressSnapshot] = useState<ProgressSnapshot>({
    progress: 0,
    stage: 'upload',
    phase: 'processing',
  });
  const activeDriverRef = useRef<ProgressDriver | null>(null);
  const attemptInFlightRef = useRef(false);
  const handoffTimerRef = useRef<number | null>(null);
  const handoffResolveRef = useRef<(() => void) | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    // Keep the legacy page migration for other application pages. Calculation
    // APIs never read investiq_model_id.
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
      setActiveIdentity({
        modelVersionId: persisted.modelVersionId,
        workbookVersionId: persisted.workbookVersionId,
        source: 'storage',
      });
      setPhase('uploaded');
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeDriverRef.current?.stop();
      if (handoffTimerRef.current !== null) {
        window.clearTimeout(handoffTimerRef.current);
      }
      handoffResolveRef.current?.();
      handoffResolveRef.current = null;
    };
  }, []);

  const waitForCompletedState = useCallback(
    () =>
      new Promise<void>((resolve) => {
        if (!mountedRef.current) {
          resolve();
          return;
        }
        handoffResolveRef.current = resolve;
        handoffTimerRef.current = window.setTimeout(() => {
          handoffTimerRef.current = null;
          handoffResolveRef.current = null;
          resolve();
        }, 350);
      }),
    [],
  );

  const handleUpload = useCallback(async () => {
    if (!file || attemptInFlightRef.current) {
      return;
    }
    attemptInFlightRef.current = true;
    setActiveIdentity(null);
    setUploadResult(null);
    setUploadError(null);
    setProgressSnapshot({
      progress: 0,
      stage: 'upload',
      phase: 'processing',
    });

    const progress = createProgressDriver({
      onUpdate: (snapshot) => {
        if (mountedRef.current) {
          setProgressSnapshot(snapshot);
        }
      },
      reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    });
    activeDriverRef.current = progress;

    try {
      const attempt = await runUploadAttempt<WorkbookValidationResponse>({
        request: async () => {
          await clearCalculationArtifacts(localStorage);
          return uploadWorkbookForCalculation(file);
        },
        progress,
        onPending: () => {
          if (!mountedRef.current) {
            return;
          }
          setLoadingState('processing');
          setPhase('uploading');
        },
        onCompleted: () => {
          if (mountedRef.current) {
            setLoadingState('completed');
          }
        },
        waitForHandoff: waitForCompletedState,
        onSucceeded: () => {},
        onFailed: (caught) => {
          if (!mountedRef.current) {
            return;
          }
          setUploadError(
            caught instanceof Error ? caught : new Error('Upload failed.'),
          );
          setPhase('failed');
        },
      });

      if (attempt.status === 'succeeded' && mountedRef.current) {
        const response = attempt.data;
        setUploadResult(response);
        if (canStartCalculationFlow(response)) {
          await persistUploadIdentity(localStorage, response);
          if (!mountedRef.current) {
            return;
          }
          setActiveIdentity({
            modelVersionId: response.model_version_id,
            workbookVersionId: response.workbook_version_id,
            source: 'upload',
          });
          setPhase('uploaded');
        } else {
          setPhase('failed');
        }
      }
    } catch (caught) {
      if (mountedRef.current) {
        setUploadError(
          caught instanceof Error ? caught : new Error('Upload failed.'),
        );
        setPhase('failed');
      }
    } finally {
      activeDriverRef.current = null;
      attemptInFlightRef.current = false;
    }
  }, [file, waitForCompletedState]);

  const uploading = phase === 'uploading';

  if (uploading) {
    return (
      <ExtractionLoadingExperience
        progress={progressSnapshot.progress}
        stage={progressSnapshot.stage}
        state={loadingState}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="py-8 text-center">
        <h1 className="text-3xl font-bold text-white">InvestIQ</h1>
        <p className="mt-2 text-d-muted">
          Upload a financial model, then exercise the persisted calculation
          APIs.
        </p>
      </div>

      <section className="mx-auto max-w-xl rounded-lg border border-d-border bg-d-card p-6 shadow">
        <h2 className="mb-4 text-lg font-semibold text-white">
          Upload Financial Model
        </h2>
        <div className="rounded-lg border-2 border-dashed border-d-border p-8 text-center">
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="block w-full text-sm text-d-muted file:mr-4 file:cursor-pointer
              file:rounded file:border-0 file:bg-gold-500 file:px-4 file:py-2
              file:text-sm file:font-semibold file:text-white file:shadow-sm
              hover:file:bg-gold-600"
          />
          {file ? (
            <p className="mt-2 text-sm text-slate-300">
              Selected: {file.name} ({(file.size / 1024).toFixed(1)} KB)
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => void handleUpload()}
          disabled={!file || uploading}
          className="mt-4 w-full rounded bg-gold-500 px-4 py-2.5 font-semibold
            text-white shadow-sm transition hover:bg-gold-600 disabled:cursor-not-allowed
            disabled:bg-gray-500 disabled:text-gray-300"
        >
          {uploading
            ? 'Processing…'
            : phase === 'failed'
              ? 'Retry upload'
              : 'Upload & Analyze'}
        </button>

        {uploadError ? (
          <div className="mt-3 rounded border border-red-700/60 bg-red-900/20 p-3 text-red-200">
            <p className="font-semibold">Upload request failed</p>
            <UploadErrorDetails error={uploadError} />
          </div>
        ) : null}
      </section>

      {uploadResult ? (
        <section className="mx-auto max-w-4xl rounded-lg border border-d-border bg-d-card p-6 shadow">
          <h2 className="text-lg font-semibold text-white">
            Workbook validation response
          </h2>
          <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
            <div className="rounded bg-d-bg p-3">
              <dt className="text-d-muted">submitted</dt>
              <dd className="font-mono text-white">
                {String(uploadResult.submitted)}
              </dd>
            </div>
            <div className="rounded bg-d-bg p-3">
              <dt className="text-d-muted">stop_reason</dt>
              <dd className="font-mono text-white">
                {uploadResult.stop_reason || '—'}
              </dd>
            </div>
            <div className="rounded bg-d-bg p-3">
              <dt className="text-d-muted">model_version_id</dt>
              <dd className="break-all font-mono text-white">
                {uploadResult.model_version_id ?? 'null'}
              </dd>
            </div>
            <div className="rounded bg-d-bg p-3">
              <dt className="text-d-muted">workbook_version_id</dt>
              <dd className="break-all font-mono text-white">
                {uploadResult.workbook_version_id ?? 'null'}
              </dd>
            </div>
          </dl>

          <div className="mt-4 rounded border border-d-border bg-d-bg p-3">
            <h3 className="text-sm font-medium text-white">
              Validation summary
            </h3>
            <pre className="mt-2 overflow-auto text-xs text-slate-200">
              {JSON.stringify(uploadResult.validation_summary, null, 2)}
            </pre>
          </div>

          {!uploadResult.submitted ? (
            <div className="mt-4 rounded border border-red-700/60 bg-red-900/20 p-4 text-red-200">
              <p className="font-semibold">
                Upload stopped before model submission
              </p>
              <p className="mt-1 font-mono text-sm">
                stop_reason: {uploadResult.stop_reason || 'unknown'}
              </p>
              <div className="mt-3">
                <p className="text-sm font-medium">errors</p>
                <pre className="mt-1 overflow-auto text-xs">
                  {JSON.stringify(uploadResult.errors, null, 2)}
                </pre>
              </div>
              <div className="mt-3">
                <p className="text-sm font-medium">validation_summary</p>
                <pre className="mt-1 overflow-auto text-xs">
                  {JSON.stringify(uploadResult.validation_summary, null, 2)}
                </pre>
              </div>
            </div>
          ) : null}

          {uploadResult.warnings.length > 0 ? (
            <details className="mt-4">
              <summary className="cursor-pointer text-sm font-medium text-yellow-300">
                Upload warnings ({uploadResult.warnings.length})
              </summary>
              <pre className="mt-2 max-h-80 overflow-auto rounded bg-d-bg p-3 text-xs text-yellow-100">
                {JSON.stringify(uploadResult.warnings, null, 2)}
              </pre>
            </details>
          ) : null}
        </section>
      ) : null}

      {activeIdentity ? (
        <CalculationPreparationPanel
          key={activeIdentity.modelVersionId}
          modelVersionId={activeIdentity.modelVersionId}
          workbookVersionId={activeIdentity.workbookVersionId}
          restoreFromStorage={activeIdentity.source === 'storage'}
        />
      ) : null}

      <p className="mx-auto max-w-4xl break-all text-center font-mono text-[11px] text-d-muted">
        Calculation identity keys:{' '}
        {CALCULATION_STORAGE_KEYS.modelVersionId},{' '}
        {CALCULATION_STORAGE_KEYS.workbookVersionId}
      </p>
    </div>
  );
}
