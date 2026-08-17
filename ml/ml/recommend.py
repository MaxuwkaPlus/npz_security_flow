"""Слабое место → профильный сценарий на следующее прохождение.

Рекомендация собирается из ручек, которые тренажёр уже умеет: уровень сложности,
первопричина, целевая ветвь и параметры уровня. Ничего нового ML не изобретает —
он выбирает значения из allowlist бэкенда и обязан пройти проверку `_validate`.

Текст здесь детерминированный. LLM (см. `llm.py`) может переписать его более
человеческим языком, но числа и выбранные ручки остаются из этого модуля.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from ml import config
from ml.data import SessionFacts
from ml.skills import SkillProfile, evaluate


@dataclass(frozen=True, slots=True)
class TrainingRecommendation:
    """Черновик следующего прохождения. Утверждает эксперт, а не ML."""

    session_id: str
    operator_id: str
    weak_skill: str | None
    # Остальные слабые навыки: тренируется первый, но эксперт должен видеть весь список.
    also_weak: tuple[str, ...]
    goal: str
    level_no: int
    disturbance_cause: str
    target_branch: int
    knobs: dict[str, Any]
    changed_knobs: tuple[str, ...]
    focus_steps: tuple[str, ...]
    evidence: tuple[str, ...] = ()
    rationale: str = ""
    skill_scores: dict[str, float | None] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "operator_id": self.operator_id,
            "weak_skill": self.weak_skill,
            "also_weak": list(self.also_weak),
            "goal": self.goal,
            "scenario": {
                "level_no": self.level_no,
                "disturbance_cause": self.disturbance_cause,
                "target_branch": self.target_branch,
                "knobs": self.knobs,
                "changed_knobs": list(self.changed_knobs),
                "focus_steps": list(self.focus_steps),
            },
            "evidence": list(self.evidence),
            "rationale": self.rationale,
            "skill_scores": self.skill_scores,
        }


def recommend(facts: SessionFacts) -> TrainingRecommendation:
    """Полный путь: факты прохождения → навыки → профильный сценарий."""

    return build(facts, evaluate(facts))


def build(facts: SessionFacts, profile: SkillProfile) -> TrainingRecommendation:
    weak = profile.weak_skill
    if weak is None:
        recipe = _mastered_recipe(facts)
        evidence = ("Слабых мест не выявлено: все проявившиеся навыки выше порога.",)
    else:
        recipe = config.TRAINING_RECIPES[weak.code]
        evidence = (f"{weak.name}: {weak.score:g} из 100 — {weak.evidence}.",)

    level_no = _shift_level(facts.level_no, recipe.level_shift)
    cause, cause_note = _choose_cause(facts, recipe.cause)
    knobs, changed = _apply_knobs(level_no, recipe.knobs)

    recommendation = TrainingRecommendation(
        session_id=facts.session_id,
        operator_id=facts.operator_id,
        weak_skill=weak.code if weak else None,
        also_weak=tuple(skill.code for skill in profile.weak_skills[1:]),
        goal=recipe.goal,
        level_no=level_no,
        disturbance_cause=cause,
        target_branch=_choose_branch(facts),
        knobs=knobs,
        changed_knobs=changed,
        focus_steps=recipe.focus_steps,
        evidence=evidence + cause_note + _context_evidence(facts),
        rationale=_rationale(facts, weak.code if weak else None, level_no, cause, changed),
        skill_scores={code: skill.score for code, skill in profile.skills.items()},
    )
    _validate(recommendation)
    return recommendation


def _mastered_recipe(facts: SessionFacts) -> config.TrainingRecipe:
    """Слабых мест нет — навык надо проверить в более трудных условиях.

    Смысл проверки в том, что устойчивость навыка видна не на лёгком уровне, а на
    разнице между лёгкими и сложными условиями (§16.9 технического задания).
    """

    return config.TrainingRecipe(
        goal=(
            "Закрепить навык в более сложных условиях: другая первопричина и меньше времени на реакцию"
            if facts.level_no < max(config.LEVELS)
            else "Подтвердить устойчивость навыка повтором на максимальном уровне с другой первопричиной"
        ),
        level_shift=1,
        cause="other",
        knobs={},
        focus_steps=("submit_diagnosis", "corrective_action", "verify_flow"),
    )


def _shift_level(level_no: int, shift: int) -> int:
    return max(min(config.LEVELS), min(max(config.LEVELS), level_no + shift))


def _choose_cause(facts: SessionFacts, policy: str) -> tuple[str, tuple[str, ...]]:
    """`same` — повторить знакомую причину, `other` — дать вторую.

    Причина прошлого прохождения восстановлена из диагноза оператора. Если оператор
    диагноз не заявил, восстановить нечего: берём первую причину и говорим об этом
    эксперту прямо, а не выдаём догадку за факт.
    """

    if facts.known_cause is None:
        note = (
            "Первопричина прошлого прохождения не восстановлена: диагноз не заявлен "
            "или назван за пределами двух известных причин.",
        )
        return config.DISTURBANCE_CAUSES[0], note

    if policy == "same":
        return facts.known_cause, ()
    other = next(cause for cause in config.DISTURBANCE_CAUSES if cause != facts.known_cause)
    return other, (f"Первопричина заменена на «{other}»: прошлое прохождение шло по другой причине.",)


def _choose_branch(facts: SessionFacts) -> int:
    """Целевая ветвь выбирается детерминированно от идентификаторов прохождения.

    Встроенный `hash()` для строк рандомизируется между запусками, поэтому берём
    sha256: одинаковый вход обязан давать одинаковую рекомендацию (§18 ТЗ).
    """

    digest = hashlib.sha256(f"{facts.operator_id}:{facts.session_id}".encode()).hexdigest()
    return config.TARGET_BRANCHES[int(digest, 16) % len(config.TARGET_BRANCHES)]


def _apply_knobs(level_no: int, overrides: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Базовый уровень плюс точечные правки под слабый навык."""

    base = config.BASE_LEVELS[level_no]
    knobs: dict[str, Any] = {
        "sensor_delay_ms": base.sensor_delay_ms,
        "nuisance_alarm_rate": base.nuisance_alarm_rate,
        "reaction_deadline_ms": base.reaction_deadline_ms,
        "development_speed_factor": base.development_speed_factor,
        "hints_enabled": base.hints_enabled,
        "standby_pump_start_delay_ms": base.standby_pump_start_delay_ms,
    }
    changed = tuple(name for name, value in overrides.items() if knobs.get(name) != value)
    knobs.update(overrides)
    return knobs, changed


def _context_evidence(facts: SessionFacts) -> tuple[str, ...]:
    """Числа прохождения, на которые эксперт смотрит при проверке рекомендации."""

    lines = [f"Уровень прошлого прохождения: {facts.level_no}, статус: {facts.status}."]
    if facts.detection_time_ms is not None:
        lines.append(
            f"Обнаружение отклонения: {facts.detection_time_ms // 1000} с "
            f"при дедлайне {facts.reaction_deadline_ms // 1000} с."
        )
    if facts.reaction_time_ms is not None:
        lines.append(f"Корректирующее действие: {facts.reaction_time_ms // 1000} с от первой тревоги.")
    lines.append(
        f"Downstream-проверок закрыто {facts.downstream_checks_done} из {len(config.DOWNSTREAM_CHECKS)}."
    )
    return tuple(lines)


def _rationale(
    facts: SessionFacts,
    weak_skill: str | None,
    level_no: int,
    cause: str,
    changed: tuple[str, ...],
) -> str:
    """Шаблонное объяснение. Работает всегда, в том числе без запущенной LLM."""

    if weak_skill is None:
        head = "Слабых мест в прошлом прохождении не выявлено."
    else:
        head = f"Слабое место прошлого прохождения — {config.SKILL_NAMES[weak_skill].lower()}."
    level_note = (
        f"уровень остаётся {level_no}"
        if level_no == facts.level_no
        else f"уровень меняется с {facts.level_no} на {level_no}"
    )
    knob_note = f", изменены параметры: {', '.join(changed)}" if changed else ""
    return f"{head} Следующее прохождение: {level_note}, первопричина «{cause}»{knob_note}."


def _validate(recommendation: TrainingRecommendation) -> None:
    """Рекомендация обязана состоять только из значений, известных тренажёру.

    Проверка стоит на выходе модуля: дальше рекомендация уходит эксперту и в
    конфигурацию сценария, и там неизвестный код был бы уже ошибкой конфигурации.
    """

    if recommendation.level_no not in config.LEVELS:
        raise ValueError(f"Недопустимый уровень: {recommendation.level_no}")
    if recommendation.disturbance_cause not in config.DISTURBANCE_CAUSES:
        raise ValueError(f"Неизвестная первопричина: {recommendation.disturbance_cause}")
    if recommendation.target_branch not in config.TARGET_BRANCHES:
        raise ValueError(f"Недопустимая ветвь: {recommendation.target_branch}")
    unknown = set(recommendation.focus_steps) - set(config.EXPECTED_STEPS)
    if unknown:
        raise ValueError(f"Шаги вне эталонной последовательности: {sorted(unknown)}")
