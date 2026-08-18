import { formatNumber } from "../../utils/helpers.js";

export function SystemicFindings({ busy, findings, onMine }) {
  return (
    <section className="report-card wide">
      <h2>Системные проблемы</h2>
      <p className="hint">
        Если один и тот же шаг проваливает половина операторов, дело уже не в конкретном
        человеке: не хватает сценария, который этот шаг отрабатывает.
      </p>

      <div className="mine-actions">
        <button disabled={busy === "mine"} onClick={() => onMine("backend")}>
          Проанализировать прохождения тренажёра
        </button>
        <button disabled={busy === "mine"} onClick={() => onMine("corpus")}>
          Проанализировать учебный корпус
        </button>
      </div>

      {busy === "mine" && <p className="hint">Анализ и формулировка предложений…</p>}

      {findings && (
        <>
          <div className="pair">
            <span>Проанализировано прохождений</span>
            <b>
              {findings.sessions_analysed} (минимум для выводов:{" "}
              {findings.min_sessions_required})
            </b>
          </div>

          {findings.total === 0 && (
            <p className="hint">
              Выводов нет: прохождений с проявившимся возмущением пока меньше порога. Это
              ожидаемое поведение, а не ошибка.
            </p>
          )}

          {findings.items.map((item) => (
            <article className="finding" key={item.finding.key}>
              <header>
                <h3>{item.text.title}</h3>
                <b>{formatNumber(item.finding.share * 100)}%</b>
              </header>
              <p className="summary">{item.finding.summary}</p>
              <p>{item.text.purpose}</p>
              <div className="chips">
                <span>уровень {item.finding.scenario.level_no}</span>
                {item.finding.scenario.focus_steps.map((step) => (
                  <span key={step}>{step}</span>
                ))}
              </div>
              <p className="hint">Критерий отработки: {item.text.expected_outcome}</p>
            </article>
          ))}
        </>
      )}
    </section>
  );
}
