import { StartSessionForm } from "../components/Forms/StartSessionForm.jsx";

export function StartPage({ scenarios, onStart }) {
  return (
    <main className="start-page">
      <div className="hero">
        <span className="eyebrow">УЧЕБНЫЙ КОМПЛЕКС</span>
        <h1>
          Пульт оператора
          <br />
          <em>ЭЛОУ-АВТ</em>
        </h1>
        <p>
          Управляйте технологической цепочкой, реагируйте на тревоги и
          подтвердите стабильность установки.
        </p>
        <div className="hero-line" />
      </div>
      <StartSessionForm scenarios={scenarios} onStart={onStart} />
    </main>
  );
}
