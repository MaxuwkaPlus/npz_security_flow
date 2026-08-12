"""Итог прохождения и текстовые выводы отчёта (§17 технического задания).

Выводы собираются из детерминированных шаблонов по зафиксированным фактам: одна и та
же сессия всегда даёт одни и те же формулировки.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class Outcome(StrEnum):
    STABILIZED = "stabilized"
    NOT_STABILIZED = "not_stabilized"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class ConclusionFacts:
    """Факты, из которых складываются словесные выводы."""

    deviation_declared: bool
    diagnosis_correct: bool
    correct_action_done: bool
    dangerous_actions: int
    downstream_checks_done: int
    downstream_checks_total: int
    detection_time_ms: int | None
    reaction_deadline_ms: int
    unacknowledged_alarms: int


def outcome_of(status: str, parameters_in_range: bool) -> Outcome:
    if status == "aborted":
        return Outcome.ABORTED
    return Outcome.STABILIZED if parameters_in_range else Outcome.NOT_STABILIZED


def conclusions(facts: ConclusionFacts) -> list[str]:
    lines: list[str] = []
    lines.append(_detection_line(facts))
    lines.append(_diagnosis_line(facts))
    lines.append(_downstream_line(facts))
    if facts.dangerous_actions:
        lines.append("Компенсирует симптом тепловой нагрузкой вместо восстановления расхода.")
    if facts.unacknowledged_alarms:
        lines.append(f"Оставляет без подтверждения тревог: {facts.unacknowledged_alarms}.")
    return lines


def _detection_line(facts: ConclusionFacts) -> str:
    if not facts.deviation_declared:
        return "Отклонение не зафиксировано оператором явно."
    if facts.detection_time_ms is None:
        return "Отклонение зафиксировано, время обнаружения не определено."
    if facts.detection_time_ms <= facts.reaction_deadline_ms:
        return "Быстро обнаруживает отклонение."
    return "Обнаруживает отклонение позже допустимого времени реакции."


def _diagnosis_line(facts: ConclusionFacts) -> str:
    if facts.diagnosis_correct and facts.correct_action_done:
        return "Правильно определяет первопричину и устраняет её."
    if facts.diagnosis_correct:
        return "Правильно диагностирует причину, но не выполняет корректирующее действие."
    if facts.correct_action_done:
        return "Устраняет причину, хотя диагноз указан неверно."
    return "Первопричина не установлена и не устранена."


def _downstream_line(facts: ConclusionFacts) -> str:
    if facts.downstream_checks_total == 0:
        return "Downstream-проверки для этого сценария не определены."
    if facts.downstream_checks_done == facts.downstream_checks_total:
        return "Прослеживает последствия по всей цепочке установки."
    if facts.downstream_checks_done == 0:
        return "Не проверяет downstream-последствия после воздействия."
    return (
        "Проверяет последствия частично: "
        f"{facts.downstream_checks_done} из {facts.downstream_checks_total} участков."
    )


def efficiency_retention(level_one: float, level_three: float) -> float | None:
    """`level_3 / level_1 × 100` (§16.9). Без первого уровня показатель не определён."""

    return None if level_one <= 0 else round(level_three / level_one * 100, 2)


def absolute_drop(level_one: float, level_three: float) -> float:
    return round(level_one - level_three, 2)


def longest_deviating_parameters(
    deviation_ms_by_metric: Sequence[tuple[str, int]], limit: int = 5
) -> list[dict[str, int | str]]:
    """Параметры, дольше всего находившиеся вне допустимой области."""

    ordered = sorted(deviation_ms_by_metric, key=lambda item: item[1], reverse=True)
    return [{"metric": metric, "out_of_range_ms": value} for metric, value in ordered[:limit] if value > 0]
