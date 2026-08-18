import { useState } from "react";
import { ProposalQueue } from "../components/Expert/ProposalQueue.jsx";
import { SessionReview } from "../components/Expert/SessionReview.jsx";
import { SystemicFindings } from "../components/Expert/SystemicFindings.jsx";
import { useExpert } from "../hooks/useExpert.js";

export function ExpertPage({ onBack }) {
  const [expertId, setExpertId] = useState("expert-1");
  const expert = useExpert(expertId);

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
        <label className="expert-id">
          Эксперт
          <input
            value={expertId}
            maxLength="64"
            onChange={(event) => setExpertId(event.target.value)}
          />
        </label>
        <p className="hint">
          {expert.health
            ? `Сервис рекомендаций доступен · формулировки: ${
                expert.health.llm_available ? expert.health.llm_model : "шаблоны, модель не запущена"
              }`
            : "Сервис рекомендаций недоступен. Тренажёр работает без него."}
        </p>
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
