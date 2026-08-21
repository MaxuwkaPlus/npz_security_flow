import { TERMINAL_SESSION_STATUSES } from "../../constants/index.js";

export function SessionControls({ session, canControl, canReadReport, onLifecycle, onReport }) {
  const canAbort = canControl && ["running", "paused"].includes(session.status);

  return (
    <section className="panel controls">
      <h3>Сессия</h3>
      <div className="control-buttons">
        {canControl && session.status === "ready" && (
          <button className="primary" onClick={() => onLifecycle("start")}>
            Запустить
          </button>
        )}
        {canControl && session.status === "running" && (
          <button onClick={() => onLifecycle("pause")}>Пауза</button>
        )}
        {canControl && session.status === "paused" && (
          <button className="primary" onClick={() => onLifecycle("resume")}>
            Продолжить
          </button>
        )}
        {canAbort && (
          <button
            className="danger"
            onClick={() => {
              if (confirm("Прервать сессию? Это действие необратимо.")) {
                onLifecycle("abort");
              }
            }}
          >
            Прервать
          </button>
        )}
        {canReadReport && TERMINAL_SESSION_STATUSES.includes(session.status) && (
          <button className="primary" onClick={onReport}>
            Открыть отчёт
          </button>
        )}
      </div>
      <small>
        {canControl
          ? "Команды применяются на ближайшем шаге симуляции."
          : "Запуск, паузу и прекращение прохождения выполняет инструктор."}
      </small>
    </section>
  );
}
