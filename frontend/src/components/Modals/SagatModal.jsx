import { useState } from "react";

export function SagatModal({ checkpoint, onSubmit }) {
  const [answers, setAnswers] = useState({});

  if (!checkpoint) return null;

  return (
    <div className="modal-backdrop">
      <form
        className="modal"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(answers);
        }}
      >
        <span className="eyebrow">SAGAT · СИТУАЦИОННАЯ ОСВЕДОМЛЁННОСТЬ</span>
        <h2>Оцените текущую обстановку</h2>
        <p>Симуляция продолжает работу. Ответьте до истечения времени.</p>
        {checkpoint.questions.map((question) => (
          <fieldset key={question.code}>
            <legend>{question.prompt}</legend>
            {question.options.map((option) => (
              <label key={option}>
                <input
                  required
                  type="radio"
                  name={question.code}
                  value={option}
                  onChange={() =>
                    setAnswers((current) => ({
                      ...current,
                      [question.code]: option,
                    }))
                  }
                />
                {option}
              </label>
            ))}
          </fieldset>
        ))}
        <button className="primary">Отправить ответы</button>
      </form>
    </div>
  );
}
