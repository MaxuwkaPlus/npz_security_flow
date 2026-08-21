const EVENT_LABELS = {
  login: "Вход",
  logout: "Выход",
  guest_session: "Прохождение без входа",
  access_denied: "Отказ в доступе",
  user_created: "Заведена учётная запись",
  user_deactivated: "Учётная запись отключена",
  role_granted: "Выдана роль",
  role_revoked: "Отозвана роль",
  password_changed: "Смена пароля",
};

/**
 * Журнал событий безопасности.
 *
 * Отказ в доступе фиксируется вместе с запрошенным правом и ручкой — по этой паре
 * видно, чего именно не хватило учётной записи и не является ли это подбором прав.
 */
export function SecurityJournal({ events, filter, onFilter, onRefresh }) {
  return (
    <section className="report-card wide">
      <h2>Журнал доступа</h2>

      <div className="journal-filter">
        {["", "login", "guest_session", "access_denied", "role_granted", "role_revoked"].map((value) => (
          <button
            key={value || "all"}
            className={filter === value ? "selected" : ""}
            onClick={() => onFilter(value)}
          >
            {value ? EVENT_LABELS[value] : "Все события"}
          </button>
        ))}
        <button onClick={onRefresh}>Обновить</button>
      </div>

      {events.length === 0 ? (
        <p className="hint">Событий нет.</p>
      ) : (
        <table className="user-table">
          <thead>
            <tr>
              <th>Время</th>
              <th>Событие</th>
              <th>Кто</th>
              <th>Что</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id} className={event.outcome === "failure" ? "inactive" : ""}>
                <td>{new Date(event.occurred_at).toLocaleString("ru-RU")}</td>
                <td>
                  {EVENT_LABELS[event.event_type] || event.event_type}
                  {event.outcome === "failure" && " · отказ"}
                </td>
                <td>{event.actor_username || "—"}</td>
                <td>
                  <small>{event.target_id || "—"}</small>
                  {event.payload?.permission && (
                    <small>требовалось: {event.payload.permission}</small>
                  )}
                  {event.payload?.role && <small>роль: {event.payload.role}</small>}
                  {event.payload?.reason && <small>причина: {event.payload.reason}</small>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
