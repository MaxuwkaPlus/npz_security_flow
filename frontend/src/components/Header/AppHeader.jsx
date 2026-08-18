import { SESSION_STATUS_LABELS } from "../../constants/index.js";
import { formatTime } from "../../utils/helpers.js";

export function AppHeader({ session, wsStatus, onExpert }) {
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
        {wsStatus === "connected" ? "связь установлена" : "подключение…"}
        <span className={`status ${session.status}`}>
          {SESSION_STATUS_LABELS[session.status] || session.status}
        </span>
        <b>{formatTime(session.sim_time_ms)}</b>
        {/* Инструктор ведёт разбор параллельно с прохождением, не прерывая его. */}
        <button className="expert-link" onClick={onExpert}>
          Кабинет эксперта
        </button>
      </div>
    </header>
  );
}
