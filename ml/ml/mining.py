"""Поиск системных проблем по результатам всех операторов.

Отличие от `recommend.py`: там речь про одного человека и его следующее прохождение,
здесь — про всю группу и про сам тренажёр. Если половина операторов проваливает один
и тот же шаг, дело уже не в конкретном человеке: не хватает сценария, который этот
шаг отрабатывает. Такое предложение уходит методической комиссии.

Выводы не делаются на трёх прохождениях: пока сессий меньше `MINING.min_sessions`,
модуль честно возвращает пустой список.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ml import config
from ml.data import SessionFacts
from ml.skills import SkillProfile, evaluate, weak_share


@dataclass(frozen=True, slots=True)
class Finding:
    """Одна системная проблема и сценарий, который её закрывает."""

    code: str  # weak_skill | missed_step
    skill: str
    share: float
    sessions: int
    summary: str
    step: str | None = None
    scenario: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Тема находки. По ней очередь эксперта отличает одну проблему от другой.

        Шаг входит в ключ: пропуск проверки расхода и пропуск downstream-проверок
        относятся к одному навыку, но это две разные проблемы и два разных сценария.
        """

        return f"{self.code}:{self.step or self.skill}"

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "code": self.code,
            "skill": self.skill,
            "step": self.step,
            "share": self.share,
            "sessions": self.sessions,
            "summary": self.summary,
            "scenario": self.scenario,
        }


# Шаги, выполнение которых видно по фактам прохождения, и как это проверить.
STEP_CHECKS: dict[str, Any] = {
    "declare_deviation": lambda facts: facts.declared_deviation_ms is not None,
    "submit_diagnosis": lambda facts: facts.diagnosis_correct,
    "corrective_action": lambda facts: facts.correct_action_ms is not None,
    "verify_flow": lambda facts: facts.verify_flow_done,
    "verify_downstream": lambda facts: facts.downstream_checks_done == len(config.DOWNSTREAM_CHECKS),
}

# Каким навыком закрывается проваленный шаг: от него берётся методика тренировки.
SKILL_BY_STEP = {
    "declare_deviation": "detection",
    "submit_diagnosis": "diagnosis",
    "corrective_action": "correction",
    "verify_flow": "verification",
    "verify_downstream": "verification",
}


def mine(sessions: list[SessionFacts]) -> list[Finding]:
    """Все системные проблемы, от самой массовой к менее массовой."""

    # Смысл имеют только прохождения, в которых возмущение дошло до оператора:
    # в остальных разбирать нечего, и они бы занижали любую долю.
    relevant = [facts for facts in sessions if facts.disturbance_happened]
    if len(relevant) < config.MINING.min_sessions:
        return []

    profiles = [evaluate(facts) for facts in relevant]
    findings = _weak_skill_findings(profiles, relevant) + _missed_step_findings(relevant)
    return sorted(findings, key=lambda finding: finding.share, reverse=True)


def _weak_skill_findings(profiles: list[SkillProfile], sessions: list[SessionFacts]) -> list[Finding]:
    """Навык, слабый у слишком большой доли операторов."""

    findings = []
    for skill_code, share in weak_share(profiles).items():
        if share < config.MINING.min_weak_share:
            continue
        evaluated = sum(1 for profile in profiles if profile.skills[skill_code].score is not None)
        findings.append(
            Finding(
                code="weak_skill",
                skill=skill_code,
                share=share,
                sessions=evaluated,
                summary=(
                    f"Навык «{config.SKILL_NAMES[skill_code]}» слаб у {share:.0%} операторов "
                    f"({evaluated} прохождений с этим навыком)."
                ),
                scenario=_scenario_for(skill_code, sessions),
            )
        )
    return findings


def _missed_step_findings(sessions: list[SessionFacts]) -> list[Finding]:
    """Шаг эталонной последовательности, который выполняет слишком мало операторов."""

    findings = []
    for step, is_done in STEP_CHECKS.items():
        done = sum(1 for facts in sessions if is_done(facts))
        completion = done / len(sessions)
        if completion >= config.MINING.min_step_completion_rate:
            continue
        skill_code = SKILL_BY_STEP[step]
        findings.append(
            Finding(
                code="missed_step",
                skill=skill_code,
                share=round(1 - completion, 2),
                sessions=len(sessions),
                step=step,
                summary=(
                    f"Шаг «{step}» выполняют лишь {completion:.0%} операторов "
                    f"({done} из {len(sessions)} прохождений)."
                ),
                scenario=_scenario_for(skill_code, sessions, focus_step=step),
            )
        )
    return findings


def _scenario_for(
    skill_code: str, sessions: list[SessionFacts], focus_step: str | None = None
) -> dict[str, Any]:
    """Черновик сценария: методика берётся из той же таблицы, что и личные рекомендации.

    Обе первопричины включены сознательно: системный навык должен работать независимо
    от того, насос это или регулятор.
    """

    recipe = config.TRAINING_RECIPES[skill_code]
    level_no = Counter(facts.level_no for facts in sessions).most_common(1)[0][0]
    base = config.BASE_LEVELS[level_no]
    knobs = {
        "sensor_delay_ms": base.sensor_delay_ms,
        "nuisance_alarm_rate": base.nuisance_alarm_rate,
        "reaction_deadline_ms": base.reaction_deadline_ms,
        "development_speed_factor": base.development_speed_factor,
        "hints_enabled": base.hints_enabled,
        "standby_pump_start_delay_ms": base.standby_pump_start_delay_ms,
    }
    knobs.update(recipe.knobs)

    focus_steps = recipe.focus_steps
    if focus_step == "verify_downstream":
        focus_steps = config.DOWNSTREAM_CHECKS
    elif focus_step is not None:
        focus_steps = (focus_step,)

    return {
        "target_skill": skill_code,
        "goal": recipe.goal,
        "level_no": level_no,
        "disturbance_causes": list(config.DISTURBANCE_CAUSES),
        "knobs": knobs,
        "focus_steps": list(focus_steps),
    }
