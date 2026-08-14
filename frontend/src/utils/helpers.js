import { ApiError } from "../services/api.js";
import { STAGE_LABELS } from "../constants/index.js";

export const formatTime = (ms = 0) =>
  `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(
    Math.floor(ms / 1000) % 60,
  ).padStart(2, "0")}`;

export const stageTitle = (code) =>
  STAGE_LABELS[code] || code?.replaceAll("_", " ") || "—";

export const formatNumber = (value) =>
  typeof value === "number"
    ? value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })
    : String(value ?? "—");

export function metricUnit(code) {
  if (code.includes("temp")) return "°C";
  if (code.includes("pressure")) return "бар";
  if (code.includes("flow")) return "т/ч";
  if (code.includes("ratio") || code.includes("index")) return "отн.";
  if (code.includes("level")) return "%";
  return "";
}

export function rejectionMessage(reason) {
  return (
    {
      unknown_action_type: "Неизвестный тип команды",
      target_not_allowed: "Команда недоступна для этого оборудования",
      missing_value: "Не задано обязательное значение",
      value_out_of_range: "Значение вне допустимого диапазона",
    }[reason] || "Команда отклонена сервером"
  );
}

export function apiErrorMessage(error) {
  if (error instanceof ApiError) {
    return (
      {
        SESSION_NOT_RUNNING:
          "Сессия не запущена: органы управления заблокированы.",
        SESSION_TRANSITION_NOT_ALLOWED: "Этот переход сейчас недоступен.",
        ACTION_ALREADY_RESOLVED: "Команда уже применена или отклонена.",
        NASA_TLX_ALREADY_SUBMITTED: "Анкета NASA-TLX уже отправлена.",
      }[error.code] || error.message
    );
  }

  return "Не удалось связаться с backend. Проверьте, что он запущен.";
}
