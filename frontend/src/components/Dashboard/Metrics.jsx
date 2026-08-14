import { useMemo } from "react";
import { metricUnit, formatNumber } from "../../utils/helpers.js";
import { PanelHeader } from "../common/PanelHeader.jsx";

function metricSeverity(tag, value) {
  if (!tag) return "";

  const isCritical =
    (tag.critical_min != null && value < tag.critical_min) ||
    (tag.critical_max != null && value > tag.critical_max);
  if (isCritical) return "critical";

  const isWarning =
    (tag.warning_min != null && value < tag.warning_min) ||
    (tag.warning_max != null && value > tag.warning_max);
  return isWarning ? "warning" : "";
}

export function Metrics({ values, topology }) {
  const numericValues = useMemo(
    () =>
      Object.entries(values)
        .filter(([, value]) => typeof value === "number")
        .slice(0, 18),
    [values],
  );
  const thresholds = useMemo(
    () =>
      new Map(
        topology?.equipment
          .flatMap((equipment) => equipment.tags)
          .map((tag) => [tag.code, tag]) || [],
      ),
    [topology],
  );

  return (
    <section className="metrics">
      <PanelHeader title="Показания приборов">
        <small>обновляются из потока</small>
      </PanelHeader>
      {numericValues.length === 0 ? (
        <div className="metric-loading">Ожидание первого снимка процесса…</div>
      ) : (
        <div className="metric-grid">
          {numericValues.map(([code, value]) => {
            const tag = thresholds.get(code);
            const severity = metricSeverity(tag, value);

            return (
              <article className={`metric ${severity}`} key={code}>
                <small>{code.replaceAll("_", " ")}</small>
                <b>{formatNumber(value)}</b>
                <span>{tag?.unit || metricUnit(code)}</span>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
