"""Правила безопасности, определяемые технологом, а не оценкой постфактум.

Единственное такое правило MVP — опасная компенсация симптома тепловой нагрузкой
(§10.3 технического задания, §43 сценария): расход сырья упал, а оператор наращивает
нагрузку печей вместо восстановления подачи.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DANGEROUS_HEAT_COMPENSATION = "dangerous_heat_compensation"

SET_FURNACE_HEAT_LOAD = "set_furnace_heat_load"
HEAT_LOAD_METRIC = "furnace_heat_load_pct"
FEED_RATIO_METRIC = "min_branch_flow_ratio"


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    """Границы, при которых наращивание тепла считается опасным."""

    feed_ratio_threshold: float = 0.95

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "SafetyPolicy":
        return cls(feed_ratio_threshold=float(data.get("feed_ratio_threshold", 0.95)))


def is_dangerous_heat_compensation(
    action_type: str,
    before: Mapping[str, float],
    after: Mapping[str, float],
    policy: SafetyPolicy,
) -> bool:
    if action_type != SET_FURNACE_HEAT_LOAD:
        return False
    increased = after.get(HEAT_LOAD_METRIC, 0.0) > before.get(HEAT_LOAD_METRIC, 0.0)
    starved = before.get(FEED_RATIO_METRIC, 1.0) < policy.feed_ratio_threshold
    return increased and starved
