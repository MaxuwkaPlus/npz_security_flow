import { ProposalQueue } from "../components/Expert/ProposalQueue.jsx";
import { SessionReview } from "../components/Expert/SessionReview.jsx";
import { SystemicFindings } from "../components/Expert/SystemicFindings.jsx";
import { useExpert } from "../hooks/useExpert.js";

export function ExpertPage({ auth, onBack }) {
  const expert = useExpert(auth.user.username);

  return (
    <main className="report-page expert-page">
      <header>
        <button onClick={onBack}>← К пульту</button>
        <span className="eyebrow">КАБИНЕТ ЭКСПЕРТА</span>
        <h1>Разбор прохождений и решения по сценариям</h1>
        <p>
          Рекомендации системы носят предварительный характер и вступают в силу только
          после вашего утверждения.
        </p>

        {/* Подпись и состояние сервиса — это состояние рабочего места, а не текст.
            Двумя плитками они читаются с одного взгляда и не растягивают шапку. */}
        <div className="workplace-state">
          <span className="state-tile">
            <small>Подпись решений · сменить нельзя</small>
            <b>{auth.user.display_name}</b>
            <code>{auth.user.username}</code>
          </span>

          <span className={`state-tile ${expert.health ? "online" : "offline"}`}>
            <small>Сервис рекомендаций</small>
            <b>
              <i className="state-dot" />
              {expert.health ? "доступен" : "недоступен"}
            </b>
            <code>
              {expert.health
                ? expert.health.llm_available
                  ? expert.health.llm_model
                  : "шаблоны, модель не запущена"
                : "тренажёр работает без него"}
            </code>
          </span>
        </div>
      </header>

      {expert.error && <p className="banner negative">{expert.error}</p>}

      <div className="report-grid">
        <SessionReview
          advice={expert.advice}
          busy={expert.busy}
          sessions={expert.sessions}
          selectedId={expert.selectedId}
          onSelect={expert.selectSession}
        />

        <ProposalQueue
          busy={expert.busy}
          proposals={expert.proposals}
          onReview={expert.review}
        />

        <SystemicFindings
          busy={expert.busy}
          findings={expert.findings}
          onMine={expert.mine}
        />

        <section className="report-card wide memo">
          <h2>Границы роли</h2>
          <ul>
            <li>
              <b>Инструктор</b> выбирает сценарий и уровень, создаёт и ведёт сессию,
              смотрит отчёт и журнал, но не изменяет скрытые параметры после запуска
              прохождения.
            </li>
            <li>
              <b>Методист</b> управляет версиями установки, сценария, правил тревог и
              оценки. Опубликованная версия не редактируется задним числом — изменение
              оформляется новой версией.
            </li>
            <li>
              <b>Оператор</b> выхода этой страницы не видит: подсказка во время
              прохождения обесценила бы проверку навыка.
            </li>
          </ul>

          <h3>Как читать оценку</h3>
          <ul>
            <li>
              Баллы навыков и выбор параметров сценария считаются детерминированно: те же
              версии конфигурации, seed и журнал действий дают тот же результат. Языковая
              модель формулирует только текст.
            </li>
            <li>
              Навык может быть не оценён: проверять результат нечего, если корректирующего
              действия не было. Такой навык не становится слабым местом.
            </li>
            <li>
              Любое опасное действие выводит безопасность в слабые места независимо от
              арифметики штрафов.
            </li>
            <li>
              Пороги навыков, штрафы и параметры уровней помечены в конфигурации как
              демонстрационные и подлежат согласованию с технологом установки.
            </li>
          </ul>
        </section>
      </div>
    </main>
  );
}
