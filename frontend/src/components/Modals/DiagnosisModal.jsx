import { useState } from "react";

const initialDiagnosis = {
  affected_area_code: "FEED-SYSTEM",
  deviation_code: "flow_deviation",
  suspected_cause_code: "flow_control_fault",
  confidence: "0.7",
};

export function DiagnosisModal({ isOpen, onClose, onSubmit }) {
  const [diagnosis, setDiagnosis] = useState(initialDiagnosis);

  if (!isOpen) return null;

  const update = (field) => (event) => {
    setDiagnosis((current) => ({ ...current, [field]: event.target.value }));
  };

  return (
    <div className="modal-backdrop">
      <div className="dialog" role="dialog" aria-modal="true">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({ ...diagnosis, confidence: Number(diagnosis.confidence) });
          }}
        >
          <button className="close" type="button" onClick={onClose}>
            ×
          </button>
          <span className="eyebrow">ФИКСАЦИЯ ДИАГНОЗА</span>
          <h2>Предполагаемая причина</h2>
          <p>
            Сервер не оценивает диагноз сразу — результат будет отражён только в
            отчёте.
          </p>
          <label>
            Затронутый участок
            <input
              value={diagnosis.affected_area_code}
              onChange={update("affected_area_code")}
              required
            />
          </label>
          <label>
            Отклонение
            <input
              value={diagnosis.deviation_code}
              onChange={update("deviation_code")}
              required
            />
          </label>
          <label>
            Предполагаемая причина
            <input
              value={diagnosis.suspected_cause_code}
              onChange={update("suspected_cause_code")}
              required
            />
          </label>
          <label>
            Уверенность: {Math.round(diagnosis.confidence * 100)}%
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={diagnosis.confidence}
              onChange={update("confidence")}
            />
          </label>
          <button className="primary">Зафиксировать диагноз</button>
        </form>
      </div>
    </div>
  );
}
