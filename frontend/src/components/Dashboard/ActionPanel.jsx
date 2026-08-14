import { useState } from "react";
import { OBSERVATIONS, QUICK_ACTIONS } from "../../constants/index.js";
import { PanelHeader } from "../common/PanelHeader.jsx";
import { Setpoint } from "../common/Setpoint.jsx";

export function ActionPanel({ enabled, onAction, onObserve }) {
  const [valve, setValve] = useState(50);
  const [water, setWater] = useState(7.5);
  const [heat, setHeat] = useState(100);

  return (
    <section className="actions">
      <PanelHeader title="Органы управления">
        <small>{enabled ? "доступны" : "сессия не запущена"}</small>
      </PanelHeader>
      <div className="quick-actions">
        {QUICK_ACTIONS.map(([type, target, caption]) => (
          <button
            disabled={!enabled}
            onClick={() => onAction(type, target)}
            key={`${type}-${target}`}
          >
            {caption}
          </button>
        ))}
      </div>
      <div className="setpoints">
        <Setpoint
          label="Открытие клапана"
          value={valve}
          setValue={setValve}
          min="0"
          max="100"
          unit="%"
          onApply={() =>
            onAction("set_control_valve", "FRC-405", {
              opening_pct: Number(valve),
            })
          }
          enabled={enabled}
        />
        <Setpoint
          label="Промывочная вода"
          value={water}
          setValue={setWater}
          min="0"
          max="20"
          step="0.5"
          unit="%"
          onApply={() =>
            onAction("set_wash_water", "ELOU", { ratio: Number(water) / 100 })
          }
          enabled={enabled}
        />
        <Setpoint
          label="Нагрузка печей"
          value={heat}
          setValue={setHeat}
          min="0"
          max="130"
          unit="%"
          onApply={() =>
            onAction("set_furnace_heat_load", "FURNACES", {
              heat_load_pct: Number(heat),
            })
          }
          enabled={enabled}
        />
      </div>
      <div className="panel-head observation-title">
        <h3>Осмотры и проверки</h3>
        <small>попадают в оценку</small>
      </div>
      <div className="observations">
        {OBSERVATIONS.map(([type, target, caption]) => (
          <button
            disabled={!enabled}
            className={type === "declare_deviation" ? "emphasis" : ""}
            onClick={() => onObserve(type, target)}
            key={`${type}-${target}`}
          >
            {caption}
          </button>
        ))}
      </div>
    </section>
  );
}
