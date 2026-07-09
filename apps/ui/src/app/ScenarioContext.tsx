'use client';

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

export type ScenarioKey = 'base_case' | 'stress_case' | 'upside_case';

export const SCENARIO_META: { key: ScenarioKey; label: string; short: string; color: string; activeBg: string }[] = [
  { key: 'base_case',    label: 'Base Case',    short: 'BASE',    color: 'text-green-400 border-green-500',  activeBg: 'bg-green-500/20 border-green-500 text-green-300' },
  { key: 'stress_case',  label: 'Stress Case',  short: 'STRESS',  color: 'text-red-400 border-red-500',      activeBg: 'bg-red-500/20 border-red-500 text-red-300' },
  { key: 'upside_case',  label: 'Upside Case',  short: 'UPSIDE',  color: 'text-blue-400 border-blue-500',    activeBg: 'bg-blue-500/20 border-blue-500 text-blue-300' },
];

interface ScenarioContextType {
  scenario: ScenarioKey;
  setScenario: (s: ScenarioKey) => void;
  scenarioLabel: string;
}

const ScenarioContext = createContext<ScenarioContextType>({
  scenario: 'base_case',
  setScenario: () => {},
  scenarioLabel: 'Base Case',
});

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [scenario, setScenarioState] = useState<ScenarioKey>('base_case');

  useEffect(() => {
    const saved = localStorage.getItem('investiq_scenario') as ScenarioKey | null;
    if (saved === 'base_case' || saved === 'stress_case' || saved === 'upside_case') {
      setScenarioState(saved);
    }
  }, []);

  const setScenario = (s: ScenarioKey) => {
    setScenarioState(s);
    localStorage.setItem('investiq_scenario', s);
  };

  const scenarioLabel = SCENARIO_META.find(m => m.key === scenario)?.label ?? 'Base Case';

  return (
    <ScenarioContext.Provider value={{ scenario, setScenario, scenarioLabel }}>
      {children}
    </ScenarioContext.Provider>
  );
}

export function useScenario() {
  return useContext(ScenarioContext);
}
