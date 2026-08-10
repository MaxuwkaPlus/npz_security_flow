"""Декларативные условия конфигурации.

Пороги этапов, тревог и блокировок хранятся в версии сценария как JSON, а не в коде.
Правило — конъюнкция сравнений метрики с числом; непрерывность выполнения (`hold_ms`)
отслеживает вызывающая сторона, потому что она владеет симуляционным временем.
"""

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

OPERATORS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


@dataclass(frozen=True, slots=True)
class Condition:
    metric: str
    op: str
    value: float

    def holds(self, metrics: Mapping[str, float]) -> bool:
        current = metrics.get(self.metric)
        return current is not None and OPERATORS[self.op](current, self.value)

    def to_json(self) -> dict[str, Any]:
        return {"metric": self.metric, "op": self.op, "value": self.value}


@dataclass(frozen=True, slots=True)
class Rule:
    """Пустое правило истинно: этап или тревога без метрик управляется временем и проверками."""

    conditions: tuple[Condition, ...] = ()
    hold_ms: int = 0

    def holds(self, metrics: Mapping[str, float]) -> bool:
        return all(condition.holds(metrics) for condition in self.conditions)

    def to_json(self) -> dict[str, Any]:
        return {"all": [condition.to_json() for condition in self.conditions], "hold_ms": self.hold_ms}


def condition(metric: str, op: str, value: float) -> Condition:
    if op not in OPERATORS:
        raise ValueError(f"Неизвестный оператор сравнения: {op}")
    return Condition(metric=metric, op=op, value=value)


def rule(*conditions: Condition, hold_ms: int = 0) -> Rule:
    return Rule(conditions=conditions, hold_ms=hold_ms)


def parse_rule(data: Mapping[str, Any]) -> Rule:
    conditions = tuple(
        condition(item["metric"], item["op"], float(item["value"])) for item in data.get("all", [])
    )
    return Rule(conditions=conditions, hold_ms=int(data.get("hold_ms", 0)))
