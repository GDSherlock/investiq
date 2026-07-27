import type { CalculationSensitivityResponse } from './calculation-api-types';
import { sensitivityTargetKey } from './sensitivity-analysis';

export type InitialSensitivityAnalysisAction =
  | 'waiting_for_current_run'
  | 'unavailable'
  | 'restore'
  | 'build';

export interface InitialSensitivityAnalysisArtifact {
  response: CalculationSensitivityResponse;
  analysisOverridesByTarget: Record<string, string>;
  analysisTornadoDriverKeys: string[];
}

export interface InitialSensitivityAnalysisInput {
  modelVersionId: string;
  graphVersionId: string;
  comparisonBaselineRunId: string;
  currentRunId: string | null;
  selectedOutputId: string | null;
  currentOverridesByTarget: Record<string, string>;
  tornadoDriverKeys: string[];
  artifact: InitialSensitivityAnalysisArtifact | null;
}

export type InitialSensitivityAnalysisActionKeyInput = Omit<
  InitialSensitivityAnalysisInput,
  'artifact'
>;

export interface InitialSensitivityActionIdentity {
  modelVersionId: string;
  graphVersionId: string;
  baselineRunId: string | null;
  currentRunId: string | null;
}

export interface InitialSensitivityActionInFlight
  extends InitialSensitivityActionIdentity {
  actionKey: string;
}

function decimalMapsEqual(
  left: Readonly<Record<string, string>>,
  right: Readonly<Record<string, string>>,
): boolean {
  const keys = Object.keys(left);
  return (
    keys.length === Object.keys(right).length &&
    keys.every(
      (key) =>
        Object.prototype.hasOwnProperty.call(right, key) &&
        Number(left[key]) === Number(right[key]),
    )
  );
}

function orderedKeysEqual(
  left: readonly string[],
  right: readonly string[],
): boolean {
  return left.length === right.length && left.every((key, index) => key === right[index]);
}

export function resolveInitialSensitivityAnalysis(
  input: InitialSensitivityAnalysisInput,
): InitialSensitivityAnalysisAction {
  if (input.currentRunId === null) {
    return 'waiting_for_current_run';
  }
  if (
    input.selectedOutputId === null ||
    input.tornadoDriverKeys.length === 0
  ) {
    return 'unavailable';
  }
  const artifact = input.artifact;
  if (
    artifact === null ||
    artifact.response.model_version_id !== input.modelVersionId ||
    artifact.response.graph_version_id !== input.graphVersionId ||
    artifact.response.comparison_baseline_run_id !==
      input.comparisonBaselineRunId ||
    artifact.response.current_run_id !== input.currentRunId ||
    artifact.response.selected_output.output_id !== input.selectedOutputId ||
    !decimalMapsEqual(
      artifact.analysisOverridesByTarget,
      input.currentOverridesByTarget,
    ) ||
    !orderedKeysEqual(
      artifact.analysisTornadoDriverKeys,
      input.tornadoDriverKeys,
    ) ||
    !orderedKeysEqual(
      artifact.response.drivers.map((driver) => sensitivityTargetKey(driver.target)),
      input.tornadoDriverKeys,
    )
  ) {
    return 'build';
  }
  return 'restore';
}

export function buildInitialSensitivityActionKey(
  input: InitialSensitivityAnalysisActionKeyInput,
): string {
  return JSON.stringify({
    modelVersionId: input.modelVersionId,
    graphVersionId: input.graphVersionId,
    comparisonBaselineRunId: input.comparisonBaselineRunId,
    currentRunId: input.currentRunId,
    selectedOutputId: input.selectedOutputId,
    currentOverridesByTarget: Object.entries(input.currentOverridesByTarget).sort(
      ([left], [right]) => left.localeCompare(right),
    ),
    tornadoDriverKeys: input.tornadoDriverKeys,
  });
}

export function shouldStartInitialSensitivityAction(
  inFlightActionKey: string | null,
  actionKey: string,
): boolean {
  return inFlightActionKey !== actionKey;
}

export function canJoinInitialSensitivityAnalysis(
  inFlightActionKey: string | null,
  actionKey: string,
): boolean {
  return inFlightActionKey === actionKey;
}

export function canJoinInitialSensitivityAction(
  inFlight: InitialSensitivityActionInFlight | null,
  current: InitialSensitivityActionIdentity,
): boolean {
  return (
    inFlight !== null &&
    inFlight.modelVersionId === current.modelVersionId &&
    inFlight.graphVersionId === current.graphVersionId &&
    inFlight.baselineRunId === current.baselineRunId &&
    inFlight.currentRunId === current.currentRunId
  );
}

export function initialSensitivityAnalysisStatusLabel(
  action: InitialSensitivityAnalysisAction | 'ready' | 'unavailable' | 'error',
): string {
  switch (action) {
    case 'waiting_for_current_run':
      return 'Waiting for exact current scenario…';
    case 'build':
      return 'Building Tornado and 5×5 matrix…';
    case 'restore':
    case 'ready':
      return 'Ready';
    case 'unavailable':
      return 'Unavailable';
    case 'error':
      return 'Analysis failed';
  }
}
