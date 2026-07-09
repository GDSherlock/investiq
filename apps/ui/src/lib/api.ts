const API_BASE = '';

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('investiq_token') : null;
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export async function uploadModel(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/api/v1/models/upload`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
  return res.json();
}

export async function getModel(modelId: string) {
  const res = await fetch(`${API_BASE}/api/v1/models/${modelId}?_t=${Date.now()}`, {
    cache: 'no-store',
    headers: { ...getAuthHeaders() },
  });
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
