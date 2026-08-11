"""Переходы между этапами сценария.

Этап закрывается, когда его условие успеха держится непрерывно `hold_ms` и выполнены
обязательные проверки. Время — ориентир, а не единственное условие: по истечении
`timeout_ms` этап закрывается с исходом `timeout`, и это фиксируется для оценки.
"""

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import StrEnum

from app.domain.rules import Rule


class StageOutcome(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Stage:
    code: str
    order_no: int
    success: Rule
    failure: Rule
    timeout_ms: int
    required_checks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StageDecision:
    outcome: StageOutcome | None
    next_stage_code: str | None
    # Момент, с которого условие успеха держится непрерывно; None — условие не выполнено.
    holding_since_ms: int | None

    @property
    def changed(self) -> bool:
        return self.outcome is not None


def evaluate_stage(
    stage: Stage,
    stages: Sequence[Stage],
    metrics: Mapping[str, float],
    *,
    entered_sim_time_ms: int,
    sim_time_ms: int,
    holding_since_ms: int | None,
    completed_checks: Set[str],
) -> StageDecision:
    if stage.failure.conditions and stage.failure.holds(metrics):
        return _finish(stage, stages, StageOutcome.FAILED)

    holding = _holding_since(stage, metrics, sim_time_ms, holding_since_ms)
    checks_done = set(stage.required_checks) <= completed_checks
    if checks_done and holding is not None and sim_time_ms - holding >= stage.success.hold_ms:
        return _finish(stage, stages, StageOutcome.SUCCESS)

    if sim_time_ms - entered_sim_time_ms >= stage.timeout_ms:
        return _finish(stage, stages, StageOutcome.TIMEOUT)

    return StageDecision(outcome=None, next_stage_code=None, holding_since_ms=holding)


def _holding_since(
    stage: Stage, metrics: Mapping[str, float], sim_time_ms: int, holding_since_ms: int | None
) -> int | None:
    if not stage.success.holds(metrics):
        return None
    return sim_time_ms if holding_since_ms is None else holding_since_ms


def _finish(stage: Stage, stages: Sequence[Stage], outcome: StageOutcome) -> StageDecision:
    return StageDecision(
        outcome=outcome, next_stage_code=next_stage_code(stage, stages), holding_since_ms=None
    )


def next_stage_code(stage: Stage, stages: Sequence[Stage]) -> str | None:
    """Следующий этап по порядку; None означает, что сценарий пройден до конца."""

    ordered = sorted(stages, key=lambda item: item.order_no)
    for index, item in enumerate(ordered):
        if item.code == stage.code:
            return ordered[index + 1].code if index + 1 < len(ordered) else None
    return None
