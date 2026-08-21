import { SessionList } from "../components/Sessions/SessionList.jsx";
import { StartSessionForm } from "../components/Forms/StartSessionForm.jsx";

export function StartPage({ auth, scenarios, sessions, onStart, onOpen, onRefresh, onNavigate }) {
  const canAssign = auth.can("session.create");
  // Инструктор заводит прохождение любому оператору; тот, кто занимается сам,
  // подписывает его собственным идентификатором и выбрать чужой не может.
  const canChooseOperator = auth.can("session.control");

  return (
    <main className="start-page">
      <div className="hero">
        <span className="eyebrow">
          {auth.isGuest
            ? "Самостоятельное прохождение · без входа"
            : `${auth.user.display_name} · ${auth.user.roles.join(", ")}`}
        </span>
        <h1>
          Пульт оператора
          <br />
          <em>ЭЛОУ-АВТ</em>
        </h1>
        <p>
          {canChooseOperator
            ? "Назначьте прохождение оператору, ведите сессию и разберите результат."
            : canAssign
              ? "Выберите сценарий и уровень, запустите установку, реагируйте на тревоги и подтвердите стабильность."
              : "Откройте назначенное вам прохождение. Управляйте установкой, реагируйте на тревоги и подтвердите стабильность."}
        </p>
        <div className="hero-line" />
        <div className="hero-links">
          {/* Кабинет эксперта виден всем, но за ним экран входа: решения там
              подписываются учётной записью. */}
          <button className="expert-link" onClick={() => onNavigate("expert")}>
            Кабинет эксперта →
          </button>
          {/* Гостю предлагать «выйти» не из чего: он не входил. Ему нужен вход —
              под обучаемым, инструктором или экспертом. */}
          {auth.isGuest ? (
            <button className="expert-link" onClick={() => onNavigate("login")}>
              Войти по учётной записи
            </button>
          ) : (
            <button className="expert-link" onClick={auth.logout}>
              Выйти
            </button>
          )}
        </div>
      </div>

      <div className="start-column">
        {canAssign && (
          <StartSessionForm
            scenarios={scenarios}
            onStart={onStart}
            operatorId={auth.user.username}
            canChooseOperator={canChooseOperator}
          />
        )}
        <SessionList
          sessions={sessions}
          title={canChooseOperator ? "Прохождения" : "Ваши прохождения"}
          hint={
            canChooseOperator
              ? "Сессию ведёт инструктор: запуск, пауза и досрочное прекращение доступны здесь."
              : "Откройте прохождение, чтобы продолжить его или посмотреть отчёт."
          }
          onOpen={onOpen}
          onRefresh={onRefresh}
        />
      </div>
    </main>
  );
}
