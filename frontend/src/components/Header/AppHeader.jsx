import { SESSION_STATUS_LABELS } from "../../constants/index.js";
import { formatTime } from "../../utils/helpers.js";

export function AppHeader({ auth, session, wsStatus, onExpert, onLeave }) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">∿</span>
        <div>
          <b>ЭЛОУ-АВТ</b>
          <small>операторский тренажёр</small>
        </div>
      </div>
      <div className="session-meta">
        <span className={`connection ${wsStatus}`} />
        {wsStatus === "connected" && "связь установлена"}
        {wsStatus === "denied" && "поток закрыт: нет доступа"}
        {!["connected", "denied"].includes(wsStatus) && "подключение…"}
        <span className={`status ${session.status}`}>
          {SESSION_STATUS_LABELS[session.status] || session.status}
        </span>
        <b>{formatTime(session.sim_time_ms)}</b>
        <span className="who" title={auth.user.roles.join(", ")}>
          {auth.user.display_name}
        </span>
        {/* Разбор идёт параллельно с прохождением, не прерывая его. Кнопка видна
            всем, но за ней экран входа: кабинет эксперта закрыт. */}
        <button className="expert-link" onClick={onExpert}>
          Кабинет эксперта
        </button>
        <button className="expert-link" onClick={onLeave}>
          К списку
        </button>
      </div>
    </header>
  );
}
