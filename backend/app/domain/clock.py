"""Симуляционное время сценария.

Это отдельные часы, не связанные с системными: они идут только на работающей сессии,
двигаются фиксированным шагом и останавливаются на паузе.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SimulationClock:
    tick_interval_ms: int
    snapshot_interval_ms: int
    duration_ms: int

    def __post_init__(self) -> None:
        if self.tick_interval_ms <= 0:
            raise ValueError("Шаг симуляции должен быть положительным")
        if self.snapshot_interval_ms % self.tick_interval_ms != 0:
            raise ValueError("Интервал снимков должен быть кратен шагу симуляции")

    def advance(self, sim_time_ms: int) -> int:
        """Следующий момент симуляционного времени, не выходящий за длительность сценария."""

        return min(sim_time_ms + self.tick_interval_ms, self.duration_ms)

    def is_finished(self, sim_time_ms: int) -> bool:
        return sim_time_ms >= self.duration_ms

    def is_snapshot_due(self, sim_time_ms: int) -> bool:
        return sim_time_ms % self.snapshot_interval_ms == 0
