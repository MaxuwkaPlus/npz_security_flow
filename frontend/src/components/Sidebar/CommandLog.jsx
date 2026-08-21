import { PanelHeader } from "../common/PanelHeader.jsx";

export function CommandLog({ actions, onCancel }) {
  return (
    <section className="panel commands">
      <PanelHeader title="Журнал команд">
        <span>{actions.length}</span>
      </PanelHeader>
      {actions.length === 0 ? (
        <p className="empty">Здесь появятся принятые команды</p>
      ) : (
        actions.map((action, index) => (
          <article key={action.id || index}>
            <div>
              <b>{action.action_type}</b>
              <small>
                {action.target_code} · {action.status}
              </small>
            </div>
            {onCancel && action.status === "accepted" && action.id && (
              <button onClick={() => onCancel(action)}>Отменить</button>
            )}
          </article>
        ))
      )}
    </section>
  );
}
