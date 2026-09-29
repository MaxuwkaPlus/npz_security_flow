import { SessionList } from "../components/Sessions/SessionList.jsx";
import { StartSessionForm } from "../components/Forms/StartSessionForm.jsx";
import { PlatformHeader } from "../components/common/PlatformHeader.jsx";
import { PlatformFooter } from "../components/common/PlatformFooter.jsx";
import { PageHeading } from "../components/common/PageHeading.jsx";

export function StartPage({
  auth,
  scenarios,
  sessions,
  onStart,
  onOpen,
  onRefresh,
  onNavigate,
}) {
  const canAssign = auth.can("session.create");
  // Инструктор заводит прохождение любому оператору; тот, кто занимается сам,
  // подписывает его собственным идентификатором и выбрать чужой не может.
  const canChooseOperator = auth.can("session.control");

  return (
    <div className="platform-shell">
      <PlatformHeader section="Учебный комплекс">
        <span className="identity-caption">
          {auth.isGuest ? "Гостевой доступ" : auth.user.display_name}
        </span>
        {auth.isGuest ? (
          <button onClick={() => onNavigate("login")}>Войти в систему</button>
        ) : (
          <button onClick={auth.logout}>Выйти</button>
        )}
      </PlatformHeader>
      <nav className="section-nav" aria-label="Разделы комплекса">
        <span aria-current="page">Подготовка к тренировке</span>
        <button onClick={() => onNavigate("expert")}>Кабинет эксперта</button>
      </nav>
      <main className="start-page page-content">
        <PageHeading
          section="Практическая подготовка"
          title="Тренировка оператора"
          description={
            canChooseOperator
              ? "Назначьте прохождение оператору, ведите сессию и разберите результат."
              : canAssign
                ? "Выберите сценарий и уровень подготовки. Продолжить начатую тренировку можно в списке прохождений."
                : "Откройте назначенное вам прохождение, чтобы продолжить тренировку или посмотреть результат."
          }
        >
          <div className="heading-note">
            <span>Объект подготовки</span>
            <strong>Установка ЭЛОУ-АВТ</strong>
            <small>От подготовки сырья до стабилизации процесса</small>
          </div>
        </PageHeading>

        <div className={`start-column ${canAssign ? "" : "sessions-only"}`}>
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
        <section
          className="training-outline"
          aria-labelledby="training-outline-title"
        >
          <h2 id="training-outline-title">Порядок работы</h2>
          <ol>
            <li>
              <span>01</span>
              <div>
                <h3>Подготовка</h3>
                <p>Выберите сценарий и откройте рабочее место оператора.</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <h3>Прохождение</h3>
                <p>
                  Контролируйте параметры, выполняйте команды и фиксируйте
                  наблюдения.
                </p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <h3>Разбор результата</h3>
                <p>
                  Изучите оценку действий, осведомлённости и субъективной
                  нагрузки.
                </p>
              </div>
            </li>
          </ol>
        </section>
      </main>
      <PlatformFooter />
    </div>
  );
}
