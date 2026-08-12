"""Движок тревог.

Тревога включается, когда условие правила держится непрерывно `activation_delay_ms`,
и снимается только по собственному условию снятия — гистерезису. Вторичные тревоги
поэтому исчезают сами, когда оператор устранил первопричину (сценарий, §42), а не
удаляются вручную.
"""

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import StrEnum

from app.domain.rules import Rule


class AlarmLevel(StrEnum):
    # L0 — второстепенная тревога: методический шум, не технологический признак.
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class AlarmState(StrEnum):
    ACTIVE_UNACKNOWLEDGED = "active_unacknowledged"
    ACTIVE_ACKNOWLEDGED = "active_acknowledged"
    CLEARED = "cleared"


@dataclass(frozen=True, slots=True)
class AlarmRule:
    code: str
    level: str
    equipment_code: str
    trigger: Rule
    clear: Rule
    activation_delay_ms: int
    ack_required: bool
    message: str


@dataclass(frozen=True, slots=True)
class AlarmDecision:
    raised: tuple[str, ...]
    cleared: tuple[str, ...]
    # Код правила → момент, с которого условие держится непрерывно.
    pending_since: Mapping[str, int]


def evaluate(
    rules: Sequence[AlarmRule],
    metrics: Mapping[str, float],
    *,
    active_codes: Set[str],
    pending_since: Mapping[str, int],
    sim_time_ms: int,
) -> AlarmDecision:
    raised: list[str] = []
    cleared: list[str] = []
    pending: dict[str, int] = {}

    for rule in rules:
        if rule.code in active_codes:
            if rule.clear.holds(metrics):
                cleared.append(rule.code)
            continue
        if not rule.trigger.holds(metrics):
            continue
        since = pending_since.get(rule.code, sim_time_ms)
        if sim_time_ms - since >= rule.activation_delay_ms:
            raised.append(rule.code)
        else:
            pending[rule.code] = since

    return AlarmDecision(raised=tuple(raised), cleared=tuple(cleared), pending_since=pending)
