"""Классификация команд оператора (§10.2 технического задания).

Синтаксически допустимая команда не является правильной: окончательный класс
корректирующего действия известен только после окна наблюдения эффекта (§8.3).
Поэтому классификация идёт в два приёма — сразу после применения и по окончании окна.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.domain.commands import ActionClassification
from app.domain.rules import Condition, condition


@dataclass(frozen=True, slots=True)
class AppliedAction:
    """Ранее применённая команда — для распознавания повторов."""

    action_type: str
    target_code: str
    value: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class EffectRule:
    """Каким наблюдаемым изменением подтверждается эффект корректирующего действия."""

    check: Condition | None
    window_ms: int
    requires_verification: bool

    @classmethod
    def from_json(cls, expected_effect: Mapping[str, Any], verification: Mapping[str, Any]) -> "EffectRule":
        check = None
        if {"metric", "op", "value"} <= set(expected_effect):
            check = condition(
                str(expected_effect["metric"]), str(expected_effect["op"]), float(expected_effect["value"])
            )
        window = int(verification.get("window_ms", 120_000))
        return cls(check=check, window_ms=window, requires_verification=bool(verification))

    def holds(self, metrics: Mapping[str, float]) -> bool:
        return self.check is None or self.check.holds(metrics)


@dataclass(frozen=True, slots=True)
class ImmediateVerdict:
    """Что известно о команде сразу после применения."""

    classification: ActionClassification | None
    evaluation_window_ms: int | None
    requires_verification: bool


def classify_on_apply(
    action: AppliedAction,
    *,
    is_corrective_type: bool,
    removed_root_cause: bool,
    diagnosis_submitted: bool,
    previous_actions: Sequence[AppliedAction],
    effect: EffectRule | None,
) -> ImmediateVerdict:
    if action in previous_actions:
        # Повтор уже принятой команды без новой необходимости.
        return ImmediateVerdict(ActionClassification.REPEATED, None, False)

    if not is_corrective_type:
        # Штатное управление пуском и режимом классификации не требует.
        return ImmediateVerdict(None, None, False)

    if not diagnosis_submitted:
        # Воздействие до обязательной диагностики (§10.2).
        return ImmediateVerdict(ActionClassification.OUT_OF_SEQUENCE, None, True)

    if not removed_root_cause:
        # Тип действия верный, но адрес не тот: причина осталась.
        return ImmediateVerdict(ActionClassification.INEFFECTIVE, None, True)

    window = effect.window_ms if effect is not None else None
    requires = effect.requires_verification if effect is not None else True
    return ImmediateVerdict(None, window, requires)


def classify_effect(effect: EffectRule | None, metrics: Mapping[str, float]) -> ActionClassification:
    """Окно наблюдения истекло: подтвердился ожидаемый эффект или нет."""

    if effect is not None and not effect.holds(metrics):
        return ActionClassification.INEFFECTIVE
    return ActionClassification.CORRECT
