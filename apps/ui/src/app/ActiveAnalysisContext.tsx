'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { usePathname } from 'next/navigation';

import {
  hydrateActiveAnalysis,
  resolveActiveAnalysis,
  type ActiveAnalysisResolution,
} from '@/lib/active-analysis';
import {
  CALCULATION_STORAGE_KEYS,
  type PersistedCalculationState,
} from '@/lib/calculation-storage';
import {
  getCalculationReadiness,
  getCalculationRun,
} from '@/lib/api';

type ActiveAnalysisLoadStatus = 'loading' | 'settled' | 'error';

export interface ActiveAnalysisContextValue
  extends ActiveAnalysisResolution {
  loadStatus: ActiveAnalysisLoadStatus;
  error: Error | null;
  refresh: () => Promise<void>;
}

const EMPTY_STATE: PersistedCalculationState = {
  workbookVersionId: null,
  modelVersionId: null,
  graphVersionId: null,
  baselineRunId: null,
  overrideRunId: null,
};

const ActiveAnalysisContext =
  createContext<ActiveAnalysisContextValue | null>(null);

export function ActiveAnalysisProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const revisionRef = useRef(0);
  const [resolution, setResolution] =
    useState<ActiveAnalysisResolution>(() =>
      resolveActiveAnalysis(EMPTY_STATE),
    );
  const [loadStatus, setLoadStatus] =
    useState<ActiveAnalysisLoadStatus>('loading');
  const [error, setError] = useState<Error | null>(null);

  const refresh = useCallback(async () => {
    const revision = ++revisionRef.current;
    setLoadStatus('loading');
    setError(null);
    try {
      const next = await hydrateActiveAnalysis(window.localStorage, {
        getReadiness: getCalculationReadiness,
        getRun: getCalculationRun,
      });
      if (revision === revisionRef.current) {
        setResolution(next);
        setLoadStatus('settled');
      }
    } catch (caught) {
      if (revision === revisionRef.current) {
        setError(
          caught instanceof Error
            ? caught
            : new Error('Unable to load the active analysis.'),
        );
        setLoadStatus('error');
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [pathname, refresh]);

  useEffect(() => {
    const calculationKeys = new Set<string>(
      Object.values(CALCULATION_STORAGE_KEYS),
    );
    const handleStorage = (event: StorageEvent) => {
      if (event.key === null || calculationKeys.has(event.key)) {
        void refresh();
      }
    };
    const handleFocus = () => void refresh();
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void refresh();
      }
    };

    window.addEventListener('storage', handleStorage);
    window.addEventListener('focus', handleFocus);
    document.addEventListener(
      'visibilitychange',
      handleVisibilityChange,
    );
    return () => {
      revisionRef.current += 1;
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener('focus', handleFocus);
      document.removeEventListener(
        'visibilitychange',
        handleVisibilityChange,
      );
    };
  }, [refresh]);

  const value = useMemo<ActiveAnalysisContextValue>(
    () => ({
      ...resolution,
      loadStatus,
      error,
      refresh,
    }),
    [error, loadStatus, refresh, resolution],
  );

  return (
    <ActiveAnalysisContext.Provider value={value}>
      {children}
    </ActiveAnalysisContext.Provider>
  );
}

export function useActiveAnalysis(): ActiveAnalysisContextValue {
  const context = useContext(ActiveAnalysisContext);
  if (context === null) {
    throw new Error(
      'useActiveAnalysis must be used within ActiveAnalysisProvider.',
    );
  }
  return context;
}
