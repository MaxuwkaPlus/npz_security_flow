"""Небольшая локальная LLM через llama.cpp.

Модель поднимается отдельным процессом и говорит по OpenAI-совместимому протоколу:

    llama-server -hf unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M \\
        --port 8080 --ctx-size 8192 --jinja

Роль модели узкая и намеренно ограниченная: она формулирует текст для эксперта по уже
посчитанным фактам. Ни одного числа, кода первопричины или значения ручки она не
выбирает — иначе рекомендация перестала бы быть воспроизводимой.

Ответ запрашивается по JSON-схеме (`response_format`), поэтому разбирать свободный
текст не нужно. Если сервер не запущен, отвечает не по схеме или молчит дольше
таймаута, работает шаблонный текст: сервис остаётся рабочим без LLM.
"""

import json
from typing import Any

import httpx

from ml import config

SYSTEM_PROMPT = (
    "Ты методист-инструктор тренажёра операторов нефтепереработки. "
    "Пишешь коротко, по-русски, деловым языком, для эксперта-человека. "
    "Используешь только те факты и числа, которые даны во входных данных. "
    "Не придумываешь новые параметры, пороги, оборудование и причины. "
    # Модель охотно дописывает «риск аварии 100%» и подобные оценки, которых во
    # входных данных нет. Для документа, который читает эксперт, это недопустимо.
    "Не добавляешь свои проценты, цифры и оценки последствий: если числа нет во "
    "входных данных, о нём не пишешь."
)

# Схемы ответа. Только текстовые поля: числа и коды уже посчитаны кодом.
RECOMMENDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 120},
        "summary": {"type": "string", "maxLength": 600},
        "instructor_note": {"type": "string", "maxLength": 600},
    },
    "required": ["title", "summary", "instructor_note"],
    "additionalProperties": False,
}

SCENARIO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 120},
        "purpose": {"type": "string", "maxLength": 600},
        "expected_outcome": {"type": "string", "maxLength": 600},
    },
    "required": ["title", "purpose", "expected_outcome"],
    "additionalProperties": False,
}


def available() -> bool:
    """Проверка, что llama-server поднят. Нужна ручке `/health` и CLI."""

    try:
        response = httpx.get(f"{config.LLM_BASE_URL}/health", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def describe_recommendation(recommendation: dict[str, Any]) -> dict[str, str]:
    """Текст к рекомендации для следующего прохождения."""

    facts = {
        "слабое_место": recommendation.get("weak_skill"),
        "цель_тренировки": recommendation.get("goal"),
        "баллы_навыков": recommendation.get("skill_scores"),
        "сценарий": recommendation.get("scenario"),
        "факты": recommendation.get("evidence"),
    }
    task = (
        "Объясни эксперту, зачем оператору именно такое следующее прохождение. "
        "title — короткий заголовок-утверждение без вопросительных знаков, "
        "например «Отработать проверку последствий на первом уровне». "
        "summary — 2-3 предложения о слабом месте со ссылкой на числа из фактов. "
        "instructor_note — на что инструктору смотреть во время прохождения."
    )
    generated = _generate(task, facts, RECOMMENDATION_SCHEMA)
    if generated is None:
        return _recommendation_template(recommendation)
    return {**generated, "source": "llm"}


def describe_scenario_proposal(finding: dict[str, Any]) -> dict[str, str]:
    """Текст к предложению нового сценария по результатам всех операторов."""

    task = (
        "Опиши предлагаемый учебный сценарий для методической комиссии. "
        "title — название сценария. "
        "purpose — какую системную проблему операторов он закрывает, со ссылкой на числа. "
        "expected_outcome — по какому наблюдаемому признаку считать, что навык отработан."
    )
    generated = _generate(task, finding, SCENARIO_SCHEMA)
    if generated is None:
        return _scenario_template(finding)
    return {**generated, "source": "llm"}


def _generate(task: str, facts: dict[str, Any], schema: dict[str, Any]) -> dict[str, str] | None:
    """Один запрос к модели. Любая неудача — не ошибка сервиса, а отказ от текста."""

    payload = {
        "model": config.LLM_MODEL,
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{task}\n\nДанные:\n{json.dumps(facts, ensure_ascii=False, indent=2)}",
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": schema, "strict": True},
        },
    }
    try:
        response = httpx.post(
            f"{config.LLM_BASE_URL}/v1/chat/completions",
            json=payload,
            timeout=config.LLM_TIMEOUT_S,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        answer = json.loads(content)
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError):
        return None

    return _validated(answer, schema)


def _validated(answer: Any, schema: dict[str, Any]) -> dict[str, str] | None:
    """Схему обещает сервер, но проверяем сами: чужой ответ доверия не имеет."""

    if not isinstance(answer, dict):
        return None
    result: dict[str, str] = {}
    for field, spec in schema["properties"].items():
        value = answer.get(field)
        if not isinstance(value, str) or not value.strip():
            return None
        result[field] = value.strip()[: spec["maxLength"]]
    return result


def _recommendation_template(recommendation: dict[str, Any]) -> dict[str, str]:
    """Детерминированный текст на случай, когда LLM недоступна."""

    weak = recommendation.get("weak_skill")
    scenario = recommendation.get("scenario", {})
    name = config.SKILL_NAMES.get(weak or "", "устойчивость навыка")
    return {
        "title": f"Следующее прохождение: {name.lower()}",
        "summary": str(recommendation.get("rationale", "")),
        "instructor_note": "Смотреть за шагами: " + ", ".join(scenario.get("focus_steps", [])),
        "source": "template",
    }


def _scenario_template(finding: dict[str, Any]) -> dict[str, str]:
    name = config.SKILL_NAMES.get(str(finding.get("skill", "")), "общий навык")
    return {
        "title": f"Учебный сценарий: {name.lower()}",
        "purpose": str(finding.get("summary", "")),
        "expected_outcome": (
            f"Навык считается отработанным, когда «{name}» выходит выше "
            f"{config.WEAK_SKILL_THRESHOLD:g} баллов у большинства операторов."
        ),
        "source": "template",
    }
