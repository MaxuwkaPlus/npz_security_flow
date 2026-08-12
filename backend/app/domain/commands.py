"""Команды оператора: допустимые воздействия и их проверка.

Allowlist органов управления и диапазоны значений берутся из версии сценария (§18
технического задания). Технологических блокировок сырьевой части исходные материалы
не определяют, поэтому здесь их нет: блокировка ЭЛОУ по уровню 3500 мм появится
вместе с моделью ЭЛОУ.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ActionStatus(StrEnum):
    ACCEPTED = "accepted"
    APPLIED = "applied"
    REJECTED = "rejected"


class ActionClassification(StrEnum):
    """Классы действий из §10.2. Большинство определяется оценкой после окна эффекта."""

    CORRECT = "correct"
    UNNECESSARY = "unnecessary"
    INEFFECTIVE = "ineffective"
    DANGEROUS = "dangerous"
    OUT_OF_SEQUENCE = "out_of_sequence"
    REPEATED = "repeated"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNVERIFIED = "unverified"


class RejectionReason(StrEnum):
    UNKNOWN_ACTION_TYPE = "unknown_action_type"
    TARGET_NOT_ALLOWED = "target_not_allowed"
    MISSING_VALUE = "missing_value"
    VALUE_OUT_OF_RANGE = "value_out_of_range"


@dataclass(frozen=True, slots=True)
class Command:
    """Принятая команда в виде, понятном расчёту установки."""

    action_type: str
    target_code: str
    value: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActionSpec:
    action_type: str
    targets: frozenset[str]
    value_bounds: Mapping[str, tuple[float, float]]

    def check(self, target_code: str, value: Mapping[str, float]) -> RejectionReason | None:
        if target_code not in self.targets:
            return RejectionReason.TARGET_NOT_ALLOWED
        for name, (low, high) in self.value_bounds.items():
            if name not in value:
                return RejectionReason.MISSING_VALUE
            if not low <= float(value[name]) <= high:
                return RejectionReason.VALUE_OUT_OF_RANGE
        return None


@dataclass(frozen=True, slots=True)
class ControlPolicy:
    """Что оператору вообще разрешено делать в этой версии сценария."""

    actions: Mapping[str, ActionSpec]

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ControlPolicy":
        return cls(
            actions={
                action_type: ActionSpec(
                    action_type=action_type,
                    targets=frozenset(spec.get("targets", ())),
                    value_bounds={
                        name: (float(bounds[0]), float(bounds[1]))
                        for name, bounds in spec.get("value_bounds", {}).items()
                    },
                )
                for action_type, spec in data.items()
            }
        )

    def check(self, action_type: str, target_code: str, value: Mapping[str, float]) -> RejectionReason | None:
        spec = self.actions.get(action_type)
        if spec is None:
            return RejectionReason.UNKNOWN_ACTION_TYPE
        return spec.check(target_code, value)
