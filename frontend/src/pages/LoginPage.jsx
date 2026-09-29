import { useState } from "react";
import { PlatformHeader } from "../components/common/PlatformHeader.jsx";
import { PlatformFooter } from "../components/common/PlatformFooter.jsx";
import { PageHeading } from "../components/common/PageHeading.jsx";

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
    <div className="platform-shell">
      <PlatformHeader section="Вход в учебный комплекс">
        {onBack && <button onClick={onBack}>{backLabel}</button>}
      </PlatformHeader>
      <main className="page-content">
        <PageHeading section={eyebrow} title={title} description={lead} />
        <div className="login-layout">
          <form className="launch-card" onSubmit={submit}>
            <h2>Учётные данные</h2>
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
            {error && (
              <p className="banner negative" role="alert">
                {error}
              </p>
            )}
            <button className="primary launch" disabled={busy}>
              {busy ? "Проверка…" : "Войти"} <span>→</span>
            </button>
          </form>
          <aside className="login-guidance">
            <h2>Доступ к рабочему месту</h2>
            <p>
              Используйте учётную запись, выданную администратором. Доступные
              разделы определяются вашей ролью.
            </p>
            <p>
              Для самостоятельной тренировки вернитесь к пульту. Гостевой режим
              доступен, если он включён в настройках комплекса.
            </p>
          </aside>
        </div>
      </main>
      <PlatformFooter />
    </div>
  );
}
