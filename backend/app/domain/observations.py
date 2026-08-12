"""Наблюдения оператора и обязательные проверки этапов.

Сам факт открытия экрана ничего не доказывает: проверка становится доменным событием
только когда оператор явно её зафиксировал (§10.1 технического задания). Соответствие
«наблюдение → закрытая проверка» описано в версии сценария, а не зашито в код.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ObservationType(StrEnum):
    DECLARE_DEVIATION = "declare_deviation"
    COMPARE_FLOWS = "compare_flows"
    INSPECT_PRESSURE = "inspect_pressure"
    INSPECT_EQUIPMENT = "inspect_equipment"
    VERIFY_RESULT = "verify_result"


@dataclass(frozen=True, slots=True)
class ObservationFact:
    observation_type: str
    target_code: str


@dataclass(frozen=True, slots=True)
class CheckRule:
    """Чем закрывается обязательная проверка этапа."""

    code: str
    observation_type: str | None = None
    target_code: str | None = None
    action_types: tuple[str, ...] = ()
    by_diagnosis: bool = False

    def closed_by_observation(self, fact: ObservationFact) -> bool:
        if self.observation_type is None or self.observation_type != fact.observation_type:
            return False
        return self.target_code is None or self.target_code == fact.target_code

    def closed_by_action(self, action_type: str) -> bool:
        return action_type in self.action_types


@dataclass(frozen=True, slots=True)
class ChecksPolicy:
    rules: tuple[CheckRule, ...]

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ChecksPolicy":
        return cls(
            rules=tuple(
                CheckRule(
                    code=code,
                    observation_type=spec.get("observation_type"),
                    target_code=spec.get("target_code"),
                    action_types=tuple(spec.get("action_types", ())),
                    by_diagnosis=bool(spec.get("by_diagnosis", False)),
                )
                for code, spec in data.items()
            )
        )

    def completed(
        self,
        observations: Sequence[ObservationFact],
        applied_action_types: Iterable[str],
        has_diagnosis: bool,
    ) -> frozenset[str]:
        action_types = set(applied_action_types)
        closed = set()
        for rule in self.rules:
            if (
                (rule.by_diagnosis and has_diagnosis)
                or any(rule.closed_by_observation(fact) for fact in observations)
                or any(rule.closed_by_action(action_type) for action_type in action_types)
            ):
                closed.add(rule.code)
        return frozenset(closed)

    def observation_targets(self, observation_type: str) -> frozenset[str]:
        """Допустимые адреса наблюдения этого типа; пусто — адрес не ограничен."""

        return frozenset(
            rule.target_code
            for rule in self.rules
            if rule.observation_type == observation_type and rule.target_code is not None
        )
