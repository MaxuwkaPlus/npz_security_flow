import { useState } from "react";
import { TLX_SCALES } from "../../constants/index.js";

const initialValues = Object.fromEntries(
  TLX_SCALES.map(([key]) => [key, 5]),
);

export function TlxModal({ isOpen, onSubmit }) {
  const [values, setValues] = useState(initialValues);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop">
      <form
        className="modal tlx"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(values);
        }}
      >
        <span className="eyebrow">NASA-TLX</span>
        <h2>Субъективная нагрузка</h2>
        <p>Эта анкета не изменяет итоговый балл прохождения.</p>
        {TLX_SCALES.map(([key, label]) => (
          <label className="range" key={key}>
            <span>
              {label}
              <b>{values[key]}</b>
            </span>
            <input
              type="range"
              min="0"
              max="10"
              value={values[key]}
              onChange={(event) =>
                setValues((current) => ({
                  ...current,
                  [key]: Number(event.target.value),
                }))
              }
            />
          </label>
        ))}
        <button className="primary">Завершить и открыть отчёт</button>
      </form>
    </div>
  );
}
