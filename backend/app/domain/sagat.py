"""SAGAT-контрольные вопросы.

Ситуационная осведомлённость проверяется тремя уровнями: что изменилось, что это
означает и что произойдёт дальше (§16.7 технического задания).

Эталонный ответ не задаётся текстом, а вычисляется из состояния установки в момент
контрольной точки. Это принципиально: §23 запрещает выдумывать эталонные ответы,
а вычисленный ответ всегда соответствует тому, что оператор реально видел.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

FULL_SCORE = 1.0
PARTIAL_SCORE = 0.5
NO_SCORE = 0.0

YES = "yes"
NO = "no"
RISING = "rising"
FALLING = "falling"
STEADY = "steady"


class QuestionKind(StrEnum):
    WHAT_CHANGED = "what_changed"
    WHAT_IT_MEANS = "what_it_means"
    WHAT_HAPPENS_NEXT = "what_happens_next"


class AnswerRule(StrEnum):
    """Как из состояния установки получается эталонный ответ."""

    VALUE = "value"
    THRESHOLD = "threshold"
    TREND = "trend"


@dataclass(frozen=True, slots=True)
class SagatQuestion:
    code: str
    kind: str
    prompt: str
    options: tuple[str, ...]
    rule: str
    metric: str
    threshold: float = 0.0
    trend_tolerance: float = 0.0

    def expected_answer(
        self, metrics: Mapping[str, float], earlier_metrics: Mapping[str, float]
    ) -> str | None:
        current = metrics.get(self.metric)
        if current is None:
            return None
        if self.rule == AnswerRule.VALUE:
            return str(int(current))
        if self.rule == AnswerRule.THRESHOLD:
            return YES if current > self.threshold else NO
        previous = earlier_metrics.get(self.metric)
        if previous is None:
            return STEADY
        delta = current - previous
        if delta > self.trend_tolerance:
            return RISING
        if delta < -self.trend_tolerance:
            return FALLING
        return STEADY

    def score(self, given: str, expected: str | None) -> float:
        if expected is None or given not in self.options:
            return NO_SCORE
        if given == expected:
            return FULL_SCORE
        # Направление угадано не полностью: ответ «без изменений» вместо тренда
        # показывает частичное понимание, а противоположный тренд — нет.
        if self.rule == AnswerRule.TREND and STEADY in (given, expected):
            return PARTIAL_SCORE
        return NO_SCORE


@dataclass(frozen=True, slots=True)
class SagatCheckpointSpec:
    code: str
    after_stage_code: str
    answer_deadline_ms: int
    questions: tuple[SagatQuestion, ...]


@dataclass(frozen=True, slots=True)
class SagatPolicy:
    checkpoints: tuple[SagatCheckpointSpec, ...]
    # На сколько назад смотрит вопрос о тренде.
    trend_window_ms: int = 30_000

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "SagatPolicy":
        return cls(
            checkpoints=tuple(
                SagatCheckpointSpec(
                    code=item["code"],
                    after_stage_code=item["after_stage_code"],
                    answer_deadline_ms=int(item.get("answer_deadline_ms", 120_000)),
                    questions=tuple(
                        SagatQuestion(
                            code=question["code"],
                            kind=question["kind"],
                            prompt=question["prompt"],
                            options=tuple(question["options"]),
                            rule=question["rule"],
                            metric=question["metric"],
                            threshold=float(question.get("threshold", 0.0)),
                            trend_tolerance=float(question.get("trend_tolerance", 0.0)),
                        )
                        for question in item.get("questions", ())
                    ),
                )
                for item in data.get("checkpoints", ())
            ),
            trend_window_ms=int(data.get("trend_window_ms", 30_000)),
        )

    def triggered_by(self, stage_code: str) -> SagatCheckpointSpec | None:
        return next((item for item in self.checkpoints if item.after_stage_code == stage_code), None)

    def checkpoint(self, code: str) -> SagatCheckpointSpec | None:
        return next((item for item in self.checkpoints if item.code == code), None)


def situation_awareness_score(earned: float, maximum: float) -> float:
    """`situation_awareness = earned / maximum × 100` (§16.7)."""

    return 0.0 if maximum <= 0 else round(earned / maximum * 100, 2)


def score_answers(
    questions: Sequence[SagatQuestion],
    answers: Mapping[str, str],
    metrics: Mapping[str, float],
    earlier_metrics: Mapping[str, float],
) -> dict[str, float]:
    return {
        question.code: question.score(
            answers.get(question.code, ""), question.expected_answer(metrics, earlier_metrics)
        )
        for question in questions
    }
