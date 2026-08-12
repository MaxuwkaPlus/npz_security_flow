"""Детерминированная оценка прохождения (§16 технического задания).

Каждый штраф связан с правилом и зафиксированным фактом, поэтому итог объясним и
воспроизводим из журнала. Веса и штрафы приходят из версии политики оценки, в коде
их нет.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

MAX_SCORE = 100.0


class Dimension(StrEnum):
    SAFETY = "safety"
    ACTION_CORRECTNESS = "action_correctness"
    PROCESS_STABILITY = "process_stability"
    REACTION_SPEED = "reaction_speed"


@dataclass(frozen=True, slots=True)
class ScoreEvent:
    """Одно объяснимое изменение балла."""

    dimension: str
    delta: float
    rule_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class ScoringPolicy:
    weights: Mapping[str, float]
    penalties: Mapping[str, float]
    stability: Mapping[str, float]
    reaction: Mapping[str, Any]

    @classmethod
    def from_json(
        cls,
        weights: Mapping[str, Any],
        penalties: Mapping[str, Any],
        stability: Mapping[str, Any],
        reaction: Mapping[str, Any],
    ) -> "ScoringPolicy":
        return cls(
            weights={key: float(value) for key, value in weights.items() if isinstance(value, int | float)},
            penalties={
                key: float(value) for key, value in penalties.items() if isinstance(value, int | float)
            },
            stability={
                key: float(value) for key, value in stability.items() if isinstance(value, int | float)
            },
            reaction=dict(reaction),
        )


@dataclass(frozen=True, slots=True)
class SessionFacts:
    """Факты прохождения, собранные из журнала сессии."""

    dangerous_actions: int = 0
    out_of_sequence_actions: int = 0
    repeated_actions: int = 0
    unverified_actions: int = 0
    unacknowledged_alarms: int = 0
    critical_area_ms: int = 0
    completed_step_weight: float = 0.0
    total_step_weight: float = 0.0
    normalized_deviation_seconds: float = 0.0
    first_visible_alarm_ms: int | None = None
    first_correct_action_ms: int | None = None
    recovery_time_ms: int | None = None
    sagat_earned: float = 0.0
    sagat_maximum: float = 0.0
    raw_nasa_tlx: float | None = None


@dataclass(frozen=True, slots=True)
class SessionScores:
    safety: float
    action_correctness: float
    process_stability: float
    reaction_speed: float
    resultiveness: float
    situation_awareness: float
    recovery_time_ms: int | None
    raw_nasa_tlx: float | None
    events: tuple[ScoreEvent, ...] = field(default_factory=tuple)


def calculate(policy: ScoringPolicy, facts: SessionFacts) -> SessionScores:
    events: list[ScoreEvent] = []
    safety = _safety(policy, facts, events)
    correctness = _action_correctness(facts, events)
    stability = _process_stability(policy, facts, events)
    reaction = _reaction_speed(policy, facts, events)

    weights = policy.weights
    resultiveness = (
        weights.get("safety", 0.0) * safety
        + weights.get("action_correctness", 0.0) * correctness
        + weights.get("process_stability", 0.0) * stability
        + weights.get("reaction_speed", 0.0) * reaction
    )
    return SessionScores(
        safety=safety,
        action_correctness=correctness,
        process_stability=stability,
        reaction_speed=reaction,
        resultiveness=_bounded(resultiveness),
        situation_awareness=_ratio_score(facts.sagat_earned, facts.sagat_maximum),
        recovery_time_ms=facts.recovery_time_ms,
        raw_nasa_tlx=facts.raw_nasa_tlx,
        events=tuple(events),
    )


def _safety(policy: ScoringPolicy, facts: SessionFacts, events: list[ScoreEvent]) -> float:
    """Начинается со 100 и снижается за опасные действия и пропущенные тревоги (§16.2)."""

    score = MAX_SCORE
    deductions = (
        ("dangerous_action", facts.dangerous_actions, "опасных действий"),
        ("missed_alarm", facts.unacknowledged_alarms, "неподтверждённых тревог"),
        ("unverified_action", facts.unverified_actions, "действий без проверки результата"),
        ("out_of_sequence_action", facts.out_of_sequence_actions, "нарушений последовательности"),
        ("repeated_action", facts.repeated_actions, "повторных команд"),
    )
    for rule_code, count, label in deductions:
        penalty = policy.penalties.get(rule_code, 0.0) * count
        if penalty > 0:
            score -= penalty
            events.append(ScoreEvent(Dimension.SAFETY, -penalty, rule_code, f"{count} {label}"))

    intervals = facts.critical_area_ms // 10_000
    critical_penalty = policy.penalties.get("critical_area_per_10s", 0.0) * intervals
    if critical_penalty > 0:
        score -= critical_penalty
        events.append(
            ScoreEvent(
                Dimension.SAFETY,
                -critical_penalty,
                "critical_area_per_10s",
                f"{facts.critical_area_ms // 1000} с в критической области",
            )
        )
    return _bounded(score)


def _action_correctness(facts: SessionFacts, events: list[ScoreEvent]) -> float:
    """`выполненный вес эталонных шагов / максимальный вес × 100` (§16.3)."""

    score = _ratio_score(facts.completed_step_weight, facts.total_step_weight)
    events.append(
        ScoreEvent(
            Dimension.ACTION_CORRECTNESS,
            score,
            "expected_steps",
            f"{facts.completed_step_weight:g} из {facts.total_step_weight:g} веса эталонных шагов",
        )
    )
    return score


def _process_stability(policy: ScoringPolicy, facts: SessionFacts, events: list[ScoreEvent]) -> float:
    """Интегральный штраф: длительное отклонение весит больше короткого (§16.4)."""

    per_second = policy.stability.get("penalty_per_normalized_deviation_second", 0.0)
    penalty = per_second * facts.normalized_deviation_seconds
    score = _bounded(MAX_SCORE - penalty)
    if penalty > 0:
        events.append(
            ScoreEvent(
                Dimension.PROCESS_STABILITY,
                -round(penalty, 2),
                "integral_deviation",
                f"{facts.normalized_deviation_seconds:.1f} нормированных секунд отклонения",
            )
        )
    return score


def _reaction_speed(policy: ScoringPolicy, facts: SessionFacts, events: list[ScoreEvent]) -> float:
    """Отсчёт с первого доступного оператору признака, а не со скрытого начала (§16.5)."""

    target_ms = float(policy.reaction.get("target_reaction_ms", 0) or 0)
    if facts.first_visible_alarm_ms is None:
        events.append(
            ScoreEvent(Dimension.REACTION_SPEED, MAX_SCORE, "no_deviation", "отклонение не возникало")
        )
        return MAX_SCORE
    if facts.first_correct_action_ms is None:
        events.append(
            ScoreEvent(Dimension.REACTION_SPEED, 0.0, "no_correct_action", "корректное действие не начато")
        )
        return 0.0

    actual_ms = max(1, facts.first_correct_action_ms - facts.first_visible_alarm_ms)
    score = _bounded(MAX_SCORE * min(1.0, target_ms / actual_ms)) if target_ms > 0 else MAX_SCORE
    events.append(
        ScoreEvent(
            Dimension.REACTION_SPEED,
            score,
            "reaction_time",
            f"{actual_ms // 1000} с до корректного действия",
        )
    )
    return score


def _ratio_score(earned: float, maximum: float) -> float:
    return 0.0 if maximum <= 0 else _bounded(earned / maximum * MAX_SCORE)


def _bounded(value: float) -> float:
    return round(max(0.0, min(MAX_SCORE, value)), 2)
