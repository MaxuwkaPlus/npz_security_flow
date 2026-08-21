import { accessToken, clearSession } from "./auth.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export class ApiError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

const requestId = () => crypto.randomUUID();

/**
 * Тело ответа как JSON, либо `undefined`, если это не JSON.
 *
 * Не всякий ответ приходит от приложения: остановленный backend доходит до клиента
 * пустым `502` от прокси. Разобрать такое тело как JSON нельзя, и показывать
 * сообщение парсера вместо причины — тоже: оно ничего не говорит оператору.
 */
function parseJson(body) {
  if (!body) return null;
  try {
    return JSON.parse(body);
  } catch {
    return undefined;
  }
}

async function request(path, options = {}) {
  const token = accessToken();
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: {
        "content-type": "application/json",
        ...(token ? { authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
      ...options,
    });
  } catch {
    throw new ApiError("NETWORK_ERROR", "Сервер недоступен");
  }

  const data = parseJson(await response.text());

  if (!response.ok) {
    const error = data?.error || {};
    // Истёкший или отозванный токен: сеанс закончился, дальше — экран входа.
    if (response.status === 401 && !path.startsWith("/auth/login")) {
      clearSession();
    }
    // Шлюзовые коды означают, что до приложения не дошли: оно не запущено или не отвечает.
    const unreachable = [502, 503, 504].includes(response.status);
    throw new ApiError(
      error.code || (unreachable ? "SERVICE_UNAVAILABLE" : "NETWORK_ERROR"),
      error.message ||
        (unreachable ? "Сервер недоступен" : `Сервер ответил ошибкой ${response.status}`),
      error.details,
    );
  }

  if (data === undefined) {
    throw new ApiError("MALFORMED_RESPONSE", "Сервер вернул неожиданный ответ");
  }
  return data;
}

export const api = {
  login: (username, password) =>
    request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  // Вход без учётной записи: токен на своё прохождение и ничего сверх него.
  guest: () => request("/auth/guest", { method: "POST" }),
  logout: () => request("/auth/logout", { method: "POST" }),
  me: () => request("/auth/me"),
  roles: () => request("/roles"),
  users: () => request("/users"),
  createUser: (body) =>
    request("/users", { method: "POST", body: JSON.stringify(body) }),
  grantRole: (userId, role) =>
    request(`/users/${userId}/roles`, {
      method: "POST",
      body: JSON.stringify({ role }),
    }),
  revokeRole: (userId, role) =>
    request(`/users/${userId}/roles/${role}`, { method: "DELETE" }),
  setUserActive: (userId, isActive) =>
    request(`/users/${userId}/active`, {
      method: "POST",
      body: JSON.stringify({ is_active: isActive }),
    }),
  securityEvents: (params = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value),
    ).toString();
    return request(`/security-events${query ? `?${query}` : ""}`);
  },
  scenarios: () => request("/scenarios"),
  scenario: (id) => request(`/scenarios/${id}`),
  topology: (id) => request(`/installations/${id}/topology`),
  sessions: (params = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value),
    ).toString();
    return request(`/sessions${query ? `?${query}` : ""}`);
  },
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
  // Токен идёт параметром: браузерный WebSocket не умеет задавать заголовки.
  const query = new URLSearchParams({
    token: accessToken() || "",
    last_sequence_no: String(lastSequenceNo),
  });
  return `${base}/ws/v1/sessions/${sessionId}?${query}`;
}
