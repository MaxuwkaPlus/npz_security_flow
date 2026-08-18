import { useState } from "react";

const KIND_LABELS = {
  next_session: "Следующее прохождение оператора",
  scenario_change: "Правка сценария",
  new_scenario: "Новый сценарий",
};

const STATUS_LABELS = {
  draft: "ждёт решения",
  approved: "утверждено",
  rejected: "отклонено",
};

function Proposal({ proposal, busy, onReview }) {
  const [comment, setComment] = useState("");
  const isDraft = proposal.status === "draft";

  return (
    <article className={`proposal ${proposal.status}`}>
      <header>
        <div>
          <span className="eyebrow">{KIND_LABELS[proposal.kind] || proposal.kind}</span>
          <h3>{proposal.title}</h3>
        </div>
        <span className={`status ${proposal.status}`}>
          {STATUS_LABELS[proposal.status] || proposal.status}
        </span>
      </header>

      {proposal.operator_id && (
        <p className="hint">
          Оператор: {proposal.operator_id}
          {proposal.session_id && ` · сессия ${proposal.session_id.slice(0, 8)}`}
        </p>
      )}

      <ul>
        {proposal.evidence.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      {isDraft ? (
        <div className="review">
          <input
            value={comment}
            placeholder="Комментарий эксперта (необязательно)"
            maxLength="1000"
            onChange={(event) => setComment(event.target.value)}
          />
          <button
            className="primary"
            disabled={busy === proposal.id}
            onClick={() => onReview(proposal.id, "approve", comment)}
          >
            Утвердить
          </button>
          <button
            className="danger"
            disabled={busy === proposal.id}
            onClick={() => onReview(proposal.id, "reject", comment)}
          >
            Отклонить
          </button>
        </div>
      ) : (
        <p className="hint">
          {STATUS_LABELS[proposal.status]}: {proposal.reviewed_by}
          {proposal.review_comment && ` — «${proposal.review_comment}»`}
        </p>
      )}
    </article>
  );
}

export function ProposalQueue({ busy, proposals, onReview }) {
  const drafts = proposals.filter((proposal) => proposal.status === "draft");
  const decided = proposals.filter((proposal) => proposal.status !== "draft");

  return (
    <section className="report-card wide">
      <h2>Очередь предложений</h2>
      <p className="hint">
        Ни одно предложение не попадает в тренажёр автоматически. Решение принимается один
        раз и остаётся в журнале.
      </p>

      {drafts.length === 0 && (
        <p className="hint">
          Черновиков нет. Они появляются после разбора прохождения или анализа всех
          операторов.
        </p>
      )}
      {drafts.map((proposal) => (
        <Proposal key={proposal.id} proposal={proposal} busy={busy} onReview={onReview} />
      ))}

      {decided.length > 0 && (
        <>
          <h3>Решения</h3>
          {decided.map((proposal) => (
            <Proposal key={proposal.id} proposal={proposal} busy={busy} onReview={onReview} />
          ))}
        </>
      )}
    </section>
  );
}
