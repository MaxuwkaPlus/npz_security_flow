const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export class ApiError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

const requestId = () => crypto.randomUUID();

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "content-type": "application/json", ...options.headers },
    ...options,
  });
  const data = response.status === 204 ? null : await response.json();

  if (!response.ok) {
    const error = data?.error || {};
    throw new ApiError(
      error.code || "NETWORK_ERROR",
      error.message || "Не удалось выполнить запрос",
      error.details,
    );
  }

  return data;
}

export const api = {
  scenarios: () => request("/scenarios"),
  scenario: (id) => request(`/scenarios/${id}`),
  topology: (id) => request(`/installations/${id}/topology`),
  createSession: (body) =>
    request("/sessions", {
      method: "POST",
      body: JSON.stringify({ request_id: requestId(), ...body }),
    }),
  state: (id) => request(`/sessions/${id}/state`),
  lifecycle: (id, command) =>
    request(`/sessions/${id}/${command}`, {
      method: "POST",
      body: JSON.stringify({ request_id: requestId() }),
    }),
  action: (id, body) =>
    request(`/sessions/${id}/actions`, {
      method: "POST",
      body: JSON.stringify({ request_id: requestId(), ...body }),
    }),
  cancelAction: (id, actionId) =>
    request(`/sessions/${id}/actions/${actionId}/cancel`, { method: "POST" }),
  observe: (id, body) =>
    request(`/sessions/${id}/observations`, {
      method: "POST",
      body: JSON.stringify({ request_id: requestId(), ...body }),
    }),
  diagnose: (id, body) =>
    request(`/sessions/${id}/diagnoses`, {
      method: "POST",
      body: JSON.stringify({ request_id: requestId(), ...body }),
    }),
  alarms: (id) => request(`/sessions/${id}/alarms`),
  acknowledge: (id, alarmId) =>
    request(`/sessions/${id}/alarms/${alarmId}/acknowledge`, {
      method: "POST",
      body: JSON.stringify({ request_id: requestId() }),
    }),
  currentSagat: (id) => request(`/sessions/${id}/sagat/current`),
  submitSagat: (id, checkpointId, answers) =>
    request(`/sessions/${id}/sagat/${checkpointId}/answers`, {
      method: "POST",
      body: JSON.stringify({ request_id: requestId(), answers }),
    }),
  nasaTlx: (id, values) =>
    request(`/sessions/${id}/nasa-tlx`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  report: (id) => request(`/sessions/${id}/report`),
  comparison: (operatorId) =>
    request(`/operators/${operatorId}/level-comparison`),
};

export function socketUrl(sessionId, lastSequenceNo) {
  const base =
    import.meta.env.VITE_WS_BASE_URL ||
    `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}`;
  return `${base}/ws/v1/sessions/${sessionId}?last_sequence_no=${lastSequenceNo}`;
}
