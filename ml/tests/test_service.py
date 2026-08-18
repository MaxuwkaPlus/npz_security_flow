"""Контрактные проверки ручек сервиса.

Живая база тренажёра в тестах не нужна: чтение журнала уже проверено в `test_skills`,
здесь важно поведение самих ручек — гейт эксперта, коды ошибок и то, что рекомендация
всегда уходит в очередь как черновик.
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from ml import config, data, service


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Очередь предложений — во временной базе, чтобы тест не трогал рабочую.
    monkeypatch.setattr(config, "ML_DB", tmp_path / "ml.db")
    # LLM в тестах не поднята: сервис обязан работать на шаблонном тексте.
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://127.0.0.1:1")
    return TestClient(service.app)


@pytest.fixture
def session_facts(monkeypatch):
    """Подменяет чтение живой сессии одним известным прохождением."""

    facts = data.SessionFacts(
        session_id="s1",
        operator_id="o1",
        source="backend",
        level_no=2,
        status="completed",
        outcome="stabilized",
        sim_time_ms=3_900_000,
        reaction_deadline_ms=90_000,
        first_alarm_ms=3_200_000,
        declared_deviation_ms=3_230_000,
        diagnosis_submitted=True,
        diagnosis_correct=True,
        correct_action_ms=3_260_000,
        verify_flow_done=False,
        downstream_checks_done=0,
        alarms_total=4,
        alarm_ack_delay_avg_ms=15_000,
        known_cause="feed_pump_capacity_loss",
    )
    monkeypatch.setattr(service.data, "load_backend_session", lambda session_id: facts)
    return facts


def test_health_reports_llm_state(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["llm_available"] is False


def test_session_list_shows_weak_spot_and_newest_first(client, session_facts, monkeypatch):
    """Разбор эксперт начинает со списка: сверху свежее прохождение, у каждого — слабое место."""

    older = replace(session_facts, session_id="s0", verify_flow_done=True, downstream_checks_done=7)
    monkeypatch.setattr(service.data, "load_backend_sessions", lambda: [older, session_facts])

    items = client.get("/ml/v1/sessions").json()["items"]

    assert [item["session_id"] for item in items] == ["s1", "s0"]
    assert items[0]["weak_skill"] == "verification"
    assert items[1]["weak_skill"] is None


def test_advice_returns_recommendation_and_creates_draft(client, session_facts):
    """Рекомендация по сессии сразу попадает в очередь эксперта как черновик."""

    body = client.get("/ml/v1/sessions/s1/advice").json()

    assert body["audience"] == "expert"
    assert body["requires_expert_approval"] is True
    assert body["recommendation"]["weak_skill"] == "verification"
    assert body["proposal_id"]

    queue = client.get("/ml/v1/proposals", params={"status": "draft"}).json()
    assert queue["total"] == 1
    assert queue["items"][0]["session_id"] == "s1"


def test_repeated_advice_keeps_one_draft(client, session_facts):
    """Пересчёт по ходу прохождения не заваливает эксперта копиями."""

    client.get("/ml/v1/sessions/s1/advice")
    client.get("/ml/v1/sessions/s1/advice")

    assert client.get("/ml/v1/proposals", params={"status": "draft"}).json()["total"] == 1


def test_advice_can_skip_the_queue(client, session_facts):
    body = client.get("/ml/v1/sessions/s1/advice", params={"save": False}).json()

    assert body["proposal_id"] is None
    assert client.get("/ml/v1/proposals").json()["total"] == 0


def test_unknown_session_gives_404(client, monkeypatch):
    monkeypatch.setattr(service.data, "load_backend_session", lambda session_id: None)

    assert client.get("/ml/v1/sessions/нет/advice").status_code == 404


def test_expert_approval_flow(client, session_facts):
    proposal_id = client.get("/ml/v1/sessions/s1/advice").json()["proposal_id"]

    approved = client.post(
        f"/ml/v1/proposals/{proposal_id}/approve", json={"expert_id": "expert-1", "comment": "берём"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    # Повторное решение по тому же предложению не принимается.
    repeated = client.post(f"/ml/v1/proposals/{proposal_id}/reject", json={"expert_id": "expert-2"})
    assert repeated.status_code == 409


def test_mining_over_corpus_creates_scenario_drafts(client):
    body = client.post("/ml/v1/scenario-proposals/mine", params={"source": "corpus"}).json()

    assert body["sessions_analysed"] == 36
    assert body["total"] > 0
    assert all(item["proposal_id"] for item in body["items"])

    drafts = client.get("/ml/v1/proposals", params={"kind": "new_scenario"}).json()
    assert drafts["total"] == body["total"]


def test_unknown_source_is_rejected(client):
    assert client.post("/ml/v1/scenario-proposals/mine", params={"source": "прод"}).status_code == 400
