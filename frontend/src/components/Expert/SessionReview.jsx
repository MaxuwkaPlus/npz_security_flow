import { formatNumber } from "../../utils/helpers.js";

const KNOB_LABELS = {
  sensor_delay_ms: "Задержка датчиков",
  nuisance_alarm_rate: "Темп второстепенных тревог",
  reaction_deadline_ms: "Дедлайн реакции",
  development_speed_factor: "Скорость развития возмущения",
  hints_enabled: "Подсказки",
  standby_pump_start_delay_ms: "Задержка пуска резервного насоса",
};

const CAUSE_LABELS = {
  feed_pump_capacity_loss: "потеря производительности сырьевого насоса",
  flow_control_valve_stiction: "заедание регулирующего органа",
};

function knobValue(name, value) {
  if (typeof value === "boolean") return value ? "включены" : "выключены";
  if (name.endsWith("_ms")) return `${Math.round(value / 1000)} с`;
  return formatNumber(value);
}

function SkillRow({ skill }) {
  if (skill.score == null) {
    return (
      <div className="skill-row muted">
        <span>{skill.name}</span>
        <div />
        <b>—</b>
        <small>{skill.evidence}</small>
      </div>
    );
  }

  return (
    <div className={`skill-row${skill.score < 70 ? " weak" : ""}`}>
      <span>{skill.name}</span>
      <div>
        <i style={{ width: `${Math.min(100, skill.score)}%` }} />
      </div>
      <b>{formatNumber(skill.score)}</b>
      <small>{skill.evidence}</small>
    </div>
  );
}

export function SessionReview({ advice, busy, sessions, selectedId, onSelect }) {
  return (
    <>
      <section className="report-card wide">
        <h2>Прохождения</h2>
        <div className="session-list">
          {sessions.length === 0 && <p className="hint">Прохождений пока нет.</p>}
          {sessions.map((session) => (
            <button
              key={session.session_id}
              className={session.session_id === selectedId ? "selected" : ""}
              onClick={() => onSelect(session.session_id)}
            >
              <b>{session.operator_id}</b>
              <span>
                уровень {session.level_no} · {session.status}
              </span>
              <small className={session.weak_skill ? "negative" : "positive"}>
                {session.weak_skill_name ||
                  (session.disturbance_happened
                    ? "слабых мест не выявлено"
                    : "возмущение не проявилось")}
              </small>
            </button>
          ))}
        </div>
      </section>

      <section className="report-card wide">
        <h2>Разбор прохождения</h2>
        {busy === "advice" && <p className="hint">Модель готовит формулировку…</p>}
        {!advice && busy !== "advice" && (
          <p className="hint">
            Выберите прохождение слева. Оценка навыков считается детерминированно, текст к
            ней формулирует локальная модель.
          </p>
        )}
        {advice && (
          <>
            <h3>{advice.text.title}</h3>
            <p className="summary">{advice.text.summary}</p>

            <div className="skills">
              {advice.skills.skills.map((skill) => (
                <SkillRow key={skill.code} skill={skill} />
              ))}
            </div>

            <h3>Предлагаемое следующее прохождение</h3>
            <div className="pair">
              <span>Цель тренировки</span>
              <b className="text">{advice.recommendation.goal}</b>
            </div>
            <div className="pair">
              <span>Уровень</span>
              <b>{advice.recommendation.scenario.level_no}</b>
            </div>
            <div className="pair">
              <span>Первопричина</span>
              <b className="text">
                {CAUSE_LABELS[advice.recommendation.scenario.disturbance_cause] ||
                  advice.recommendation.scenario.disturbance_cause}
              </b>
            </div>
            <div className="pair">
              <span>Целевая ветвь</span>
              <b>{advice.recommendation.scenario.target_branch}</b>
            </div>

            <h3>Параметры уровня</h3>
            <div className="knobs">
              {Object.entries(advice.recommendation.scenario.knobs).map(([name, value]) => (
                <div
                  key={name}
                  className={
                    advice.recommendation.scenario.changed_knobs.includes(name)
                      ? "changed"
                      : ""
                  }
                >
                  <span>{KNOB_LABELS[name] || name}</span>
                  <b>{knobValue(name, value)}</b>
                </div>
              ))}
            </div>

            <h3>Отрабатываемые шаги</h3>
            <div className="chips">
              {advice.recommendation.scenario.focus_steps.map((step) => (
                <span key={step}>{step}</span>
              ))}
            </div>

            <h3>Обоснование</h3>
            <ul>
              {advice.recommendation.evidence.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>

            <div className="instructor-note">
              <b>Инструктору на следующее прохождение</b>
              <p>{advice.text.instructor_note}</p>
            </div>

            <p className="hint">
              Текст:{" "}
              {advice.text.source === "llm"
                ? "локальная модель"
                : "шаблон — модель не запущена"}
              {advice.session_status === "running" &&
                " · сессия ещё идёт, оценка будет уточняться"}
            </p>
          </>
        )}
      </section>
    </>
  );
}
