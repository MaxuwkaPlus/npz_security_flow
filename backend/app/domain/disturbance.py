"""Выбор скрытых параметров возмущения (§10 технического задания).

Выбор детерминирован: одинаковые версия сценария, уровень и `random_seed` дают одно и
то же возмущение. Результат хранится в `hidden_runtime_config_json` и никогда не
попадает в операторский API или WebSocket.
"""

import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DisturbanceOption:
    """Вариант возмущения из опубликованной конфигурации сценария."""

    code: str
    cause_code: str
    eligible_branches: tuple[int, ...]
    earliest_sim_time_ms: int
    latest_sim_time_ms: int
    development: dict[str, Any]
    recovery: dict[str, Any]


@dataclass(frozen=True, slots=True)
class HiddenDisturbance:
    code: str
    cause_code: str
    target_branch: int
    onset_sim_time_ms: int
    development: dict[str, Any]
    recovery: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def select_disturbance(
    options: Sequence[DisturbanceOption],
    random_seed: int,
    development_speed_factor: float,
) -> HiddenDisturbance:
    """Выбирает шаблон, целевую ветвь и момент начала по seed сессии."""

    if not options:
        raise ValueError("В версии сценария нет ни одного шаблона возмущения")

    generator = random.Random(random_seed)
    option = generator.choice(sorted(options, key=lambda item: item.code))
    if not option.eligible_branches:
        raise ValueError(f"Шаблон возмущения {option.code} не указывает целевые ветви")

    target_branch = generator.choice(sorted(option.eligible_branches))
    onset_sim_time_ms = generator.randint(option.earliest_sim_time_ms, option.latest_sim_time_ms)

    development = dict(option.development)
    # Уровень сложности меняет только скорость развития, а не саму причину.
    ramp_duration_ms = development.get("ramp_duration_ms")
    if isinstance(ramp_duration_ms, int | float) and development_speed_factor > 0:
        development["ramp_duration_ms"] = int(ramp_duration_ms / development_speed_factor)

    return HiddenDisturbance(
        code=option.code,
        cause_code=option.cause_code,
        target_branch=target_branch,
        onset_sim_time_ms=onset_sim_time_ms,
        development=development,
        recovery=dict(option.recovery),
    )
