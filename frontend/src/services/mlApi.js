const ML_BASE = import.meta.env.VITE_ML_BASE_URL || "/ml/v1";

export class MlError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/**
 * Тело ответа как JSON, либо `undefined`, если это не JSON.
 *
 * Разбирать тело вслепую нельзя: упавший сервис рекомендаций доходит до клиента
 * пустым `502` от прокси, а не объектом с `detail`. Тогда `JSON.parse` бросает
 * свою ошибку, и эксперт видит «unexpected character at line 1 column 1» вместо
 * причины — сообщение парсера в интерфейсе не значит ничего.
 */
function parseJson(body) {
  if (!body) return null;
  try {
    return JSON.parse(body);
  } catch {
    return undefined;
  }
}

function failure(response, data) {
  // FastAPI кладёт причину в `detail`; это единственный случай, когда серверу есть
  // что сказать эксперту.
  if (typeof data?.detail === "string") return new MlError(data.detail, response.status);
  // Шлюзовые коды означают, что до сервиса не дошли: он не запущен или не отвечает.
  if ([502, 503, 504].includes(response.status)) {
    return new MlError("Сервис рекомендаций недоступен", response.status);
  }
  return new MlError(`Сервис рекомендаций ответил ошибкой ${response.status}`, response.status);
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

  const data = parseJson(await response.text());

  if (!response.ok) throw failure(response, data);
  if (data === undefined) {
    throw new MlError("Сервис рекомендаций вернул неожиданный ответ", response.status);
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
