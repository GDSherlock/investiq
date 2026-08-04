import type {
  CanonicalReportCreateRequest,
  CanonicalReportHistoryResponse,
  CanonicalReportResponse,
  CalculationInputsResponse,
  CalculationReadinessResponse,
  CalculationRequest,
  CalculationSensitivityRequest,
  CalculationSensitivityResponse,
  CalculationRunOutputsResponse,
  CalculationRunResponse,
  CashFlowAnalysisResponse,
  ModelHistoryResponse,
  ModelDiagnosticsResponse,
  MonteCarloInputCatalogResponse,
  MonteCarloRunCreateRequest,
  MonteCarloRunHistoryResponse,
  MonteCarloRunResponse,
  OverviewAnalysisResponse,
  ReportChatExchangeResponse,
  ReportChatMessageCreateRequest,
  ReportChatThreadResponse,
  WorkbookValidationResponse,
} from './calculation-api-types';
import { parseCalculationApiErrorPayload } from './calculation-flow';

const API_BASE = '';
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

interface LegacyModelUploadResponse {
  model_id: string;
  investment_id: string;
  health_report: Record<string, unknown>;
  parsed_sheets: string[];
  assumptions_count: number;
}

function getAuthHeaders(): Record<string, string> {
  let token: string | null = null;
  if (typeof window !== 'undefined') {
    try {
      token = localStorage.getItem('investiq_token');
    } catch {
      token = null;
    }
  }
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

async function postModelUpload(file: File): Promise<Response> {
  const formData = new FormData();
  formData.append('file', file);
  return fetch(`${API_BASE}/api/v1/models/upload`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
    body: formData,
  });
}

async function readResponsePayload(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

async function parseJsonResponse<T>(res: Response): Promise<T> {
  const payload = await readResponsePayload(res);
  if (!res.ok) {
    throw parseCalculationApiErrorPayload(
      res.status,
      res.statusText,
      payload,
    );
  }
  return payload as T;
}

/**
 * Compatibility surface for existing legacy pages. New calculation code must
 * use uploadWorkbookForCalculation so model_version_id stays distinct from
 * legacy model_id.
 */
export async function uploadModel(
  file: File,
): Promise<LegacyModelUploadResponse> {
  return parseJsonResponse<LegacyModelUploadResponse>(
    await postModelUpload(file),
  );
}

export async function uploadWorkbookForCalculation(
  file: File,
): Promise<WorkbookValidationResponse> {
  return parseJsonResponse<WorkbookValidationResponse>(
    await postModelUpload(file),
  );
}

export async function getModelHistory(
  limit = 20,
): Promise<ModelHistoryResponse> {
  const response = await fetch(
    `${API_BASE}/api/v1/models?limit=${encodeURIComponent(String(limit))}`,
    {
      cache: 'no-store',
      headers: { ...getAuthHeaders() },
    },
  );
  return parseJsonResponse<ModelHistoryResponse>(response);
}

export async function getCalculationReadiness(
  modelVersionId: string,
): Promise<CalculationReadinessResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/calculation/readiness`,
    {
      cache: 'no-store',
      headers: { ...getAuthHeaders() },
    },
  );
  return parseJsonResponse<CalculationReadinessResponse>(res);
}

export async function prepareCalculation(
  modelVersionId: string,
): Promise<CalculationReadinessResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/calculation/prepare`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify({}),
    },
  );
  return parseJsonResponse<CalculationReadinessResponse>(res);
}

export async function getCalculationInputs(
  modelVersionId: string,
  options: {
    targetKind?: 'parameter' | 'financial_series_value';
    editableOnly?: boolean;
    limit?: number;
    cursor?: string;
  } = {},
): Promise<CalculationInputsResponse> {
  const params = new URLSearchParams();
  if (options.targetKind !== undefined) {
    params.set('target_kind', options.targetKind);
  }
  if (options.editableOnly !== undefined) {
    params.set('editable_only', String(options.editableOnly));
  }
  if (options.limit !== undefined) {
    params.set('limit', String(options.limit));
  }
  if (options.cursor !== undefined) {
    params.set('cursor', options.cursor);
  }
  const query = params.size > 0 ? `?${params.toString()}` : '';
  const res = await fetch(
    `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/calculation/inputs${query}`,
    {
      cache: 'no-store',
      headers: { ...getAuthHeaders() },
    },
  );
  return parseJsonResponse<CalculationInputsResponse>(res);
}

export async function runCalculation(
  modelVersionId: string,
  request: CalculationRequest,
): Promise<CalculationRunResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/calculations`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(request),
    },
  );
  return parseJsonResponse<CalculationRunResponse>(res);
}

export async function getCalculationRun(
  calculationRunId: string,
): Promise<CalculationRunResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/calculation-runs/${encodeURIComponent(calculationRunId)}`,
    {
      cache: 'no-store',
      headers: { ...getAuthHeaders() },
    },
  );
  return parseJsonResponse<CalculationRunResponse>(res);
}

export async function getCalculationRunOutputs(
  calculationRunId: string,
): Promise<CalculationRunOutputsResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/calculation-runs/${encodeURIComponent(calculationRunId)}/outputs`,
    {
      cache: 'no-store',
      headers: { ...getAuthHeaders() },
    },
  );
  return parseJsonResponse<CalculationRunOutputsResponse>(res);
}

export async function getOverviewAnalysis(
  calculationRunId: string,
): Promise<OverviewAnalysisResponse> {
  return parseJsonResponse<OverviewAnalysisResponse>(
    await fetch(
      `${API_BASE}/api/v1/calculation-runs/${encodeURIComponent(calculationRunId)}/overview`,
      {
        cache: 'no-store',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export async function getCashFlowAnalysis(
  calculationRunId: string,
): Promise<CashFlowAnalysisResponse> {
  return parseJsonResponse<CashFlowAnalysisResponse>(
    await fetch(
      `${API_BASE}/api/v1/calculation-runs/${encodeURIComponent(calculationRunId)}/cash-flow`,
      {
        cache: 'no-store',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export async function getModelDiagnostics(
  modelVersionId: string,
): Promise<ModelDiagnosticsResponse> {
  return parseJsonResponse<ModelDiagnosticsResponse>(
    await fetch(
      `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/diagnostics`,
      {
        cache: 'no-store',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export async function getMonteCarloInputs(
  modelVersionId: string,
): Promise<MonteCarloInputCatalogResponse> {
  return parseJsonResponse<MonteCarloInputCatalogResponse>(
    await fetch(
      `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/monte-carlo/inputs`,
      {
        cache: 'no-store',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export async function createMonteCarloRun(
  modelVersionId: string,
  request: MonteCarloRunCreateRequest,
): Promise<MonteCarloRunResponse> {
  return parseJsonResponse<MonteCarloRunResponse>(
    await fetch(
      `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/monte-carlo-runs`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify(request),
      },
    ),
  );
}

export async function getMonteCarloRun(
  monteCarloRunId: string,
): Promise<MonteCarloRunResponse> {
  return parseJsonResponse<MonteCarloRunResponse>(
    await fetch(
      `${API_BASE}/api/v1/monte-carlo-runs/${encodeURIComponent(monteCarloRunId)}`,
      {
        cache: 'no-store',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export async function cancelMonteCarloRun(
  monteCarloRunId: string,
): Promise<MonteCarloRunResponse> {
  return parseJsonResponse<MonteCarloRunResponse>(
    await fetch(
      `${API_BASE}/api/v1/monte-carlo-runs/${encodeURIComponent(monteCarloRunId)}/cancel`,
      {
        method: 'POST',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export async function getMonteCarloRunHistory(
  modelVersionId: string,
): Promise<MonteCarloRunHistoryResponse> {
  return parseJsonResponse<MonteCarloRunHistoryResponse>(
    await fetch(
      `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/monte-carlo-runs`,
      {
        cache: 'no-store',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export async function createCanonicalReport(
  modelVersionId: string,
  request: CanonicalReportCreateRequest,
): Promise<CanonicalReportResponse> {
  return parseJsonResponse<CanonicalReportResponse>(
    await fetch(
      `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/reports`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify(request),
      },
    ),
  );
}

export async function getCanonicalReport(
  reportId: string,
): Promise<CanonicalReportResponse> {
  return parseJsonResponse<CanonicalReportResponse>(
    await fetch(
      `${API_BASE}/api/v1/report-runs/${encodeURIComponent(reportId)}`,
      {
        cache: 'no-store',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export async function getCanonicalReportHistory(
  modelVersionId: string,
): Promise<CanonicalReportHistoryResponse> {
  return parseJsonResponse<CanonicalReportHistoryResponse>(
    await fetch(
      `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/reports`,
      {
        cache: 'no-store',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export async function getReportChat(
  modelVersionId: string,
  clientId: string,
): Promise<ReportChatThreadResponse> {
  const response = await fetch(
    `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}` +
      `/report-chat?client_id=${encodeURIComponent(clientId)}`,
    {
      cache: 'no-store',
      headers: { ...getAuthHeaders() },
    },
  );
  return parseJsonResponse<ReportChatThreadResponse>(response);
}

export async function sendReportChatMessage(
  modelVersionId: string,
  request: ReportChatMessageCreateRequest,
): Promise<ReportChatExchangeResponse> {
  const response = await fetch(
    `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}` +
      '/report-chat/messages',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(request),
    },
  );
  return parseJsonResponse<ReportChatExchangeResponse>(response);
}

export async function downloadReportChatDocx(
  modelVersionId: string,
  messageId: string,
  clientId: string,
): Promise<Blob> {
  const response = await fetch(
    `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}` +
      `/report-chat/messages/${encodeURIComponent(messageId)}` +
      `/docx?client_id=${encodeURIComponent(clientId)}`,
    { headers: { ...getAuthHeaders() } },
  );
  if (!response.ok) {
    await parseJsonResponse<never>(response);
    throw new Error('Unable to download report.');
  }
  return response.blob();
}

export async function runCalculationSensitivity(
  modelVersionId: string,
  request: CalculationSensitivityRequest,
): Promise<CalculationSensitivityResponse> {
  return parseJsonResponse<CalculationSensitivityResponse>(
    await fetch(
      `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/calculation/sensitivity`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify(request),
      },
    ),
  );
}

export async function getCalculationSensitivityAnalysis(
  analysisId: string,
): Promise<CalculationSensitivityResponse> {
  return parseJsonResponse<CalculationSensitivityResponse>(
    await fetch(
      `${API_BASE}/api/v1/calculation-sensitivity-analyses/${encodeURIComponent(analysisId)}`,
      {
        cache: 'no-store',
        headers: { ...getAuthHeaders() },
      },
    ),
  );
}

export function isUsableLegacyModelId(
  modelId: string | null | undefined,
): modelId is string {
  return typeof modelId === 'string' && UUID_PATTERN.test(modelId.trim());
}

export async function loadLegacyModelIfAvailable<T>(
  modelId: string | null | undefined,
  loader: (validModelId: string) => Promise<T>,
): Promise<T | null> {
  if (!isUsableLegacyModelId(modelId)) {
    return null;
  }
  return loader(modelId.trim());
}

export async function getModel(modelId: string) {
  if (!isUsableLegacyModelId(modelId)) {
    throw new Error('A valid legacy model ID is required.');
  }
  const res = await fetch(
    `${API_BASE}/api/v1/models/${encodeURIComponent(modelId.trim())}?_t=${Date.now()}`,
    {
      cache: 'no-store',
      headers: { ...getAuthHeaders() },
    },
  );
  if (!res.ok) throw new Error('Model not found');
  return res.json();
}

export async function getAssumptions(modelId: string, category?: string) {
  const url = category
    ? `${API_BASE}/api/v1/models/${modelId}/assumptions?category=${category}`
    : `${API_BASE}/api/v1/models/${modelId}/assumptions`;
  const res = await fetch(url, { headers: { ...getAuthHeaders() } });
  return res.json();
}

export async function createScenario(modelId: string, name: string, overrides?: Record<string, unknown>) {
  const res = await fetch(`${API_BASE}/api/v1/scenarios`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ model_id: modelId, name, assumptions_overrides: overrides || {} }),
  });
  return res.json();
}

export async function runSensitivity(scenarioId: string) {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/${scenarioId}/sensitivity`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({}),
  });
  return res.json();
}

export async function runRealtimeSensitivity(scenarioId: string, overrides: Record<string, number>) {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/${scenarioId}/sensitivity/realtime`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ overrides }),
  });
  return res.json();
}

export async function runMonteCarlo(
  scenarioId: string,
  nSimulations = 10000,
  variables?: Record<string, number>,
  volatilities?: Record<string, number>,
  correlationMatrix?: number[][],
) {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/${scenarioId}/monte-carlo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({
      n_simulations: nSimulations,
      variables: variables || null,
      volatilities: volatilities || null,
      correlation_matrix: correlationMatrix || null,
    }),
  });
  return res.json();
}

export async function getCashFlows(scenarioId: string) {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/${scenarioId}/cashflows`, {
    headers: { ...getAuthHeaders() },
  });
  return res.json();
}

export async function getMonitor(scenarioId: string) {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/${scenarioId}/monitor`, {
    headers: { ...getAuthHeaders() },
  });
  return res.json();
}

export async function getMonitorLegacy(investmentId: string) {
  const res = await fetch(`${API_BASE}/api/v1/investments/${investmentId}/monitor`, {
    headers: { ...getAuthHeaders() },
  });
  return res.json();
}

export async function generateReport(investmentId: string) {
  const res = await fetch(`${API_BASE}/api/v1/reports/generate?investment_id=${investmentId}`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
  });
  return res.json();
}

export async function generatePersonaReport(modelId: string, persona: any) {
  const res = await fetch(`${API_BASE}/api/v1/reports/persona-generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ model_id: modelId, persona }),
  });
  return res.json();
}

export async function chatWithAssistant(
  modelId: string,
  query: string,
  persona: any,
  history?: { role: string; content: string }[],
) {
  const res = await fetch(`${API_BASE}/api/v1/assistant/chat-persona`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ model_id: modelId, query, persona, history: history || [] }),
  });
  return res.json();
}

export async function getAlerts(investmentId?: string) {
  const url = investmentId
    ? `${API_BASE}/api/v1/alerts/active?investment_id=${investmentId}`
    : `${API_BASE}/api/v1/alerts/active`;
  const res = await fetch(url, { headers: { ...getAuthHeaders() } });
  return res.json();
}
