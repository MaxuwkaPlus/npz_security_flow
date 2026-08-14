import { PROCESS_GROUPS } from "../../constants/index.js";

function stageMarker(index) {
  if (index === 0) return "feed";
  if (index === 2) return "elou";
  if (index === 4) return "k";
  return "";
}

export function ProcessMap({ topology, stage }) {
  return (
    <section className="process-map">
      <div className="map-head">
        <span>Мнемосхема установки</span>
        <small>{topology?.name || "загрузка состава…"}</small>
      </div>
      <div className="flow">
        {PROCESS_GROUPS.map(([name, codes], index) => (
          <div
            className={`node ${stage?.includes(stageMarker(index)) ? "active" : ""}`}
            key={name}
          >
            <b>{name}</b>
            <small>{codes}</small>
            {index < PROCESS_GROUPS.length - 1 && <i>→</i>}
          </div>
        ))}
      </div>
    </section>
  );
}
