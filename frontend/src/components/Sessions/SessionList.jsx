import { SESSION_STATUS_LABELS } from "../../constants/index.js";
import { formatTime } from "../../utils/helpers.js";

/**
 * Прохождения, доступные текущей роли.
 *
 * Обучаемому сервер отдаёт только назначенные ему сессии, инструктору и эксперту —
 * все. Фильтрация выполняется на сервере, здесь только отображение.
 */
export function SessionList({ sessions, title, hint, onOpen, onRefresh }) {
  return (
    <section className="launch-card assigned-sessions">
      <h2>{title}</h2>
      {hint && <p className="scenario-description">{hint}</p>}

      {sessions.length === 0 ? (
        <p className="hint">Назначенных прохождений нет.</p>
      ) : (
        <ul className="session-rows">
          {sessions.map((session) => (
            <li key={session.id}>
              <button type="button" onClick={() => onOpen(session)}>
                <b>{session.operator_id}</b>
                <span className={`status ${session.status}`}>
                  {SESSION_STATUS_LABELS[session.status] || session.status}
                </span>
                <small>
                  уровень {session.level_no} · {formatTime(session.sim_time_ms)}
                </small>
              </button>
            </li>
          ))}
        </ul>
      )}

      <button type="button" onClick={onRefresh}>
        Обновить список
      </button>
    </section>
  );
}
