const ML_BASE = import.meta.env.VITE_ML_BASE_URL || "/ml/v1";

export class MlError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${ML_BASE}${path}`, {
      headers: { "content-type": "application/json", ...options.headers },
      ...options,
    });
  } catch {
    // Сервис рекомендаций необязателен: тренажёр работает и без него.
    throw new MlError("Сервис рекомендаций недоступен", 0);
  }

  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    throw new MlError(data?.detail || "Не удалось выполнить запрос", response.status);
  }
  return data;
}

export const mlApi = {
  health: () => request("/health"),
  sessions: () => request("/sessions"),
  advice: (sessionId) => request(`/sessions/${sessionId}/advice`),
  proposals: (status) => request(`/proposals${status ? `?status=${status}` : ""}`),
  review: (proposalId, decision, expertId, comment) =>
    request(`/proposals/${proposalId}/${decision}`, {
      method: "POST",
      body: JSON.stringify({ expert_id: expertId, comment: comment || null }),
    }),
  mine: (source) =>
    request(`/scenario-proposals/mine?source=${source}`, { method: "POST" }),
};
