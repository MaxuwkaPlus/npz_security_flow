import { PanelHeader } from "../common/PanelHeader.jsx";

export function AlarmPanel({ alarms, enabled, onAcknowledge }) {
  const activeAlarmCount = alarms.filter((alarm) => alarm.state !== "cleared").length;

  return (
    <section className="panel alarms">
      <PanelHeader title="Тревоги">
        <span>{activeAlarmCount}</span>
      </PanelHeader>
      {alarms.length === 0 ? (
        <p className="empty">Активных тревог нет</p>
      ) : (
        alarms.map((alarm) => (
          <article
            className={`alarm ${alarm.level.toLowerCase()} ${alarm.is_nuisance ? "nuisance" : ""}`}
            key={alarm.id}
          >
            <div>
              <b>
                {alarm.level} · {alarm.equipment_code}
              </b>
              <p>{alarm.message}</p>
            </div>
            {alarm.state === "active_unacknowledged" && (
              <button
                disabled={!enabled}
                onClick={() => onAcknowledge(alarm.id)}
              >
                Квитировать
              </button>
            )}
            {alarm.state === "active_acknowledged" && <small>Квитирована</small>}
          </article>
        ))
      )}
    </section>
  );
}
