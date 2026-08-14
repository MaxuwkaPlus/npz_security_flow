import { useReport } from "../hooks/useReport.js";
import { formatNumber, formatTime } from "../utils/helpers.js";

function Timing({ name, value, raw }) {
  return (
    <div className="pair">
      <span>{name}</span>
      <b>{value == null ? "—" : raw ? formatNumber(value) : formatTime(value)}</b>
    </div>
  );
}

function ScoreRow({ name, score }) {
  return (
    <div className="score-row">
      <span>{name}</span>
      <div>
        <i style={{ width: `${Math.min(100, Number(score || 0))}%` }} />
      </div>
      <b>{formatNumber(score)}</b>
    </div>
  );
}

function outcomeTitle(outcome) {
  if (outcome === "stabilized") return "Установка стабилизирована";
  if (outcome === "aborted") return "Сессия прервана";
  return "Стабилизация не подтверждена";
}

export function ReportPage({ session, onBack }) {
  const { comparison, report } = useReport(session?.id, session?.operator_id);

  if (!report) {
    return (
      <main className="report-page">
        <p>Формирование отчёта…</p>
      </main>
    );
  }

  const scores = [
    ["Безопасность", report.scores.safety],
    ["Корректность действий", report.scores.action_correctness],
    ["Стабильность", report.scores.process_stability],
    ["Скорость реакции", report.scores.reaction_speed],
    ["Осведомлённость", report.scores.situation_awareness],
  ];

  return (
    <main className="report-page">
      <header>
        <button onClick={onBack}>← К пульту</button>
        <span className="eyebrow">ИТОГ ПРОХОЖДЕНИЯ</span>
        <h1>{outcomeTitle(report.outcome)}</h1>
        <p>Симуляционное время: {formatTime(report.timings.total_sim_time_ms)}</p>
      </header>
      <section className="resultiveness">
        <span>Результативность</span>
        <b>{formatNumber(report.scores.resultiveness)}</b>
        <small>/ 100</small>
      </section>
      <div className="report-grid">
        <section className="report-card">
          <h2>Профиль результата</h2>
          {scores.map(([name, score]) => (
            <ScoreRow key={name} name={name} score={score} />
          ))}
        </section>
        <section className="report-card">
          <h2>Временные показатели</h2>
          <Timing name="Обнаружение" value={report.timings.detection_time_ms} />
          <Timing name="Реакция" value={report.timings.reaction_time_ms} />
          <Timing name="Восстановление" value={report.timings.recovery_time_ms} />
          <Timing name="NASA-TLX" value={report.scores.raw_nasa_tlx} raw />
        </section>
        <section className="report-card wide">
          <h2>Выводы</h2>
          {report.conclusions.length ? (
            <ul>
              {report.conclusions.map((conclusion) => (
                <li key={conclusion}>{conclusion}</li>
              ))}
            </ul>
          ) : (
            <p>Выводы будут сформированы после завершения сценария.</p>
          )}
          <h3>Проверки downstream</h3>
          <div className="checks">
            <div>
              <b>Выполнены</b>
              {report.downstream_checks.completed.map((check) => (
                <span key={check}>✓ {check}</span>
              ))}
            </div>
            <div>
              <b>Пропущены</b>
              {report.downstream_checks.missing.map((check) => (
                <span key={check}>! {check}</span>
              ))}
            </div>
          </div>
        </section>
        <section className="report-card">
          <h2>Действия</h2>
          <p>{report.actions.total} команд</p>
          {Object.entries(report.actions.by_classification).map(
            ([classification, count]) => (
              <div className="pair" key={classification}>
                <span>{classification}</span>
                <b>{count}</b>
              </div>
            ),
          )}
        </section>
        <section className="report-card">
          <h2>Тревоги</h2>
          <p>{report.alarms.total} тревог</p>
          {report.alarms.unacknowledged.length ? (
            <p className="negative">
              Не квитированы: {report.alarms.unacknowledged.join(", ")}
            </p>
          ) : (
            <p className="positive">Все тревоги квитированы</p>
          )}
        </section>
        {comparison?.levels.length > 0 && (
          <section className="report-card wide">
            <h2>Сравнение уровней</h2>
            <div className="comparison">
              {comparison.levels.map((level) => (
                <div key={level.level_no}>
                  <span>Уровень {level.level_no}</span>
                  <b>{formatNumber(level.resultiveness)}</b>
                </div>
              ))}
              <div>
                <span>Сохранение эффективности</span>
                <b>
                  {comparison.efficiency_retention == null
                    ? "—"
                    : `${formatNumber(comparison.efficiency_retention)}%`}
                </b>
              </div>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
