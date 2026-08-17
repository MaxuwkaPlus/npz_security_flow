"""Проверка договора с LLM: сервис обязан работать и без неё."""

import json

import httpx

from ml import llm


def test_text_falls_back_to_template_without_llm(monkeypatch):
    """Сервер не поднят — рекомендация всё равно получает текст."""

    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "http://127.0.0.1:1")

    text = llm.describe_recommendation(
        {
            "weak_skill": "verification",
            "rationale": "Слабое место — проверка результата.",
            "scenario": {"focus_steps": ["verify_flow", "verify_k1"]},
        }
    )

    assert text["source"] == "template"
    assert text["title"]
    assert "verify_flow" in text["instructor_note"]


def test_availability_check_survives_dead_server(monkeypatch):
    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "http://127.0.0.1:1")
    assert llm.available() is False


def test_llm_answer_is_used_when_valid(monkeypatch):
    """Валидный ответ модели подставляется как есть и помечается источником."""

    def fake_post(url, **kwargs):
        answer = {"title": "Заголовок", "summary": "Кратко", "instructor_note": "Смотреть за проверками"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    text = llm.describe_recommendation({"weak_skill": "verification"})

    assert text == {
        "title": "Заголовок",
        "summary": "Кратко",
        "instructor_note": "Смотреть за проверками",
        "source": "llm",
    }


def test_incomplete_llm_answer_is_rejected(monkeypatch):
    """Ответ без обязательного поля не подставляется: лучше шаблон, чем дыра в тексте."""

    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"title": "Только заголовок"}'}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    text = llm.describe_recommendation({"weak_skill": "verification", "rationale": "текст"})

    assert text["source"] == "template"
