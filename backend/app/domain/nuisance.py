"""Второстепенные тревоги.

Методический раздражитель, а не технологический признак: уровень сложности задаёт их
интенсивность (§9 технического задания), чтобы проверить работу оператора под потоком
тревог. Появление детерминировано seed сессии и симуляционным временем, поэтому
повторный прогон даёт тот же поток помех.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MINUTE_MS = 60_000


@dataclass(frozen=True, slots=True)
class NuisanceAlarm:
    code: str
    equipment_code: str
    message: str


@dataclass(frozen=True, slots=True)
class NuisancePolicy:
    alarms: tuple[NuisanceAlarm, ...]
    duration_ms: int
    level: str
    rate_per_minute: float

    @classmethod
    def from_json(cls, data: Mapping[str, Any], rate_per_minute: float) -> "NuisancePolicy":
        return cls(
            alarms=tuple(
                NuisanceAlarm(
                    code=item["code"],
                    equipment_code=item["equipment_code"],
                    message=item["message"],
                )
                for item in data.get("alarms", ())
            ),
            duration_ms=int(data.get("duration_ms", 120_000)),
            level=str(data.get("level", "L0")),
            rate_per_minute=rate_per_minute,
        )

    def due(
        self, seed: int, sim_time_ms: int, tick_interval_ms: int, active_codes: Sequence[str]
    ) -> NuisanceAlarm | None:
        """Какая второстепенная тревога должна появиться на этом шаге."""

        if not self.alarms or self.rate_per_minute <= 0:
            return None
        probability = self.rate_per_minute * tick_interval_ms / MINUTE_MS
        if _uniform(seed, sim_time_ms, "occurrence") >= probability:
            return None
        available = [alarm for alarm in self.alarms if alarm.code not in active_codes]
        if not available:
            return None
        index = int(_uniform(seed, sim_time_ms, "choice") * len(available))
        return available[min(index, len(available) - 1)]


def _uniform(seed: int, sim_time_ms: int, salt: str) -> float:
    """Воспроизводимое псевдослучайное число из seed и момента времени."""

    digest = hashlib.blake2b(f"{seed}:{sim_time_ms}:{salt}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64
