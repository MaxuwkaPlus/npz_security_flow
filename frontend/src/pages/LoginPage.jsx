import { useState } from "react";

const DEFAULT_LEAD =
  "Доступ разграничен по ролям: обучаемый проходит сценарии, инструктор ведёт " +
  "обучение, эксперт разбирает результаты, администратор ИБ работает с журналом доступа.";

/**
 * Экран входа. Один и тот же для всех закрытых разделов — меняются только
 * заголовок и пояснение, потому что различаются не правила входа, а то, куда
 * человек идёт: в кабинет эксперта или на рабочее место администратора ИБ.
 */
export function LoginPage({
  onLogin,
  busy,
  error,
  eyebrow = "УЧЕБНЫЙ КОМПЛЕКС",
  title = "Вход в систему",
  lead = DEFAULT_LEAD,
  onBack,
  backLabel = "← К пульту",
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const submit = (event) => {
    event.preventDefault();
    onLogin(username.trim(), password);
  };

  return (
    <main className="start-page">
      <div className="hero">
        <span className="eyebrow">{eyebrow}</span>
        <h1>
          Пульт оператора
          <br />
          <em>ЭЛОУ-АВТ</em>
        </h1>
        <p>{lead}</p>
        <div className="hero-line" />
        {onBack && (
          <div className="hero-links">
            <button className="expert-link" onClick={onBack}>
              {backLabel}
            </button>
          </div>
        )}
      </div>

      <form className="launch-card" onSubmit={submit}>
        <h2>{title}</h2>
        <label>
          Учётная запись
          <input
            value={username}
            maxLength="64"
            autoComplete="username"
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label>
          Пароль
          <input
            type="password"
            value={password}
            maxLength="256"
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error && <p className="banner negative">{error}</p>}
        <button className="primary launch" disabled={busy}>
          {busy ? "Проверка…" : "Войти"} <span>→</span>
        </button>
      </form>
    </main>
  );
}
