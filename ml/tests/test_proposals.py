"""Проверка очереди предложений: гейт эксперта должен быть непроходим сам собой."""

import pytest

from ml import proposals


@pytest.fixture
def conn(tmp_path):
    connection = proposals.connect(tmp_path / "ml.db")
    yield connection
    connection.close()


def _draft(conn, dedup_key: str = "session-1"):
    return proposals.save_draft(
        conn,
        kind=proposals.KIND_NEXT_SESSION,
        dedup_key=dedup_key,
        title="Отработать проверку последствий",
        payload={"level_no": 1},
        evidence=["downstream-проверок закрыто 0 из 7"],
        operator_id="o1",
        session_id="session-1",
    )


def test_new_proposal_waits_for_expert(conn):
    """Свежее предложение всегда черновик: само оно ничего не меняет."""

    draft = _draft(conn)

    assert draft.status == proposals.STATUS_DRAFT
    assert draft.reviewed_by is None
    assert [item.id for item in proposals.list_proposals(conn, status="draft")] == [draft.id]


def test_repeated_draft_updates_the_same_record(conn):
    """Пересчёт по ходу сессии обновляет черновик, а не плодит записи."""

    first = _draft(conn)
    proposals.save_draft(
        conn,
        kind=proposals.KIND_NEXT_SESSION,
        dedup_key="session-1",
        title="Отработать диагностику",
        payload={"level_no": 2},
        evidence=["заявлена неверная первопричина"],
        session_id="session-1",
    )

    drafts = proposals.list_proposals(conn, status="draft")
    assert len(drafts) == 1
    assert drafts[0].id == first.id
    assert drafts[0].payload == {"level_no": 2}


def test_expert_decision_is_recorded(conn):
    approved = proposals.review(conn, _draft(conn).id, status="approved", expert_id="expert-1", comment="ок")

    assert approved.status == proposals.STATUS_APPROVED
    assert approved.reviewed_by == "expert-1"
    assert approved.review_comment == "ок"


def test_decision_cannot_be_rewritten(conn):
    """Утверждённое предложение нельзя переиграть: это журнал решений эксперта."""

    draft = _draft(conn)
    proposals.review(conn, draft.id, status="approved", expert_id="expert-1")

    with pytest.raises(proposals.ProposalAlreadyReviewed):
        proposals.review(conn, draft.id, status="rejected", expert_id="expert-2")


def test_new_draft_appears_after_previous_one_is_closed(conn):
    """Решённое предложение освобождает тему: по ней снова можно предложить черновик."""

    first = _draft(conn)
    proposals.review(conn, first.id, status="rejected", expert_id="expert-1", comment="не то")
    second = _draft(conn)

    assert second.id != first.id
    assert len(proposals.list_proposals(conn)) == 2


def test_unknown_proposal_is_reported(conn):
    with pytest.raises(proposals.ProposalNotFound):
        proposals.get(conn, "нет такого")
