import { SESSION_STATUS_LABELS } from "../../constants/index.js";
import { formatTime } from "../../utils/helpers.js";
import { PlatformHeader } from "../common/PlatformHeader.jsx";

export function AppHeader({ auth, session, wsStatus, onExpert, onLeave }) {
  return (
    <PlatformHeader section="Рабочее место оператора">
      <div className="session-meta">
        <span className="connection-label" role="status">
          <i className={`connection ${wsStatus}`} />
          {wsStatus === "connected" && "На связи"}
          {wsStatus === "denied" && "Нет доступа к потоку"}
          {!["connected", "denied"].includes(wsStatus) && "Подключение…"}
        </span>
        <span className={`status ${session.status}`}>
          {SESSION_STATUS_LABELS[session.status] || session.status}
        </span>
        <b className="simulation-clock" title="Симуляционное время">
          {formatTime(session.sim_time_ms)}
        </b>
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
    </PlatformHeader>
  );
}
