import { useEffect, useState } from "react";

const levelCaption = { 1: "обучение", 2: "стандарт", 3: "эксперт" };

export function StartSessionForm({ scenarios, onStart }) {
  const [operatorId, setOperatorId] = useState("operator-1");
  const [scenarioId, setScenarioId] = useState("");
  const [levelNo, setLevelNo] = useState(1);
  const selectedScenario =
    scenarios.find((scenario) => scenario.id === scenarioId) || scenarios[0];

  useEffect(() => {
    if (!scenarioId && scenarios[0]) setScenarioId(scenarios[0].id);
  }, [scenarioId, scenarios]);

  const submit = (event) => {
    event.preventDefault();
    if (!selectedScenario) return;
    onStart({ operatorId, scenarioId: selectedScenario.id, levelNo });
  };

  return (
    <form className="launch-card" onSubmit={submit}>
      <h2>Новое прохождение</h2>
      <label>
        Идентификатор оператора
        <input
          value={operatorId}
          maxLength="64"
          onChange={(event) => setOperatorId(event.target.value)}
          required
        />
      </label>
      <label>
        Сценарий
        <select
          value={scenarioId}
          onChange={(event) => setScenarioId(event.target.value)}
        >
          {scenarios.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              {scenario.name}
            </option>
          ))}
        </select>
      </label>
      <div>
        <span className="label">Уровень сложности</span>
        <div className="levels">
          {[1, 2, 3].map((level) => (
            <button
              type="button"
              className={levelNo === level ? "selected" : ""}
              onClick={() => setLevelNo(level)}
              key={level}
            >
              <b>{level}</b>
              <small>{levelCaption[level]}</small>
            </button>
          ))}
        </div>
      </div>
      <p className="scenario-description">
        {selectedScenario?.description || "Загрузка сценариев…"}
      </p>
      <button className="primary launch" disabled={!selectedScenario}>
        Создать сессию <span>→</span>
      </button>
    </form>
  );
}
