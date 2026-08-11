"""Разбор опубликованной конфигурации в объекты домена.

Версия сценария неизменяема, поэтому разбор чистый и результат можно кэшировать.
"""

from app.domain.clock import SimulationClock
from app.domain.twin import Disturbance, TwinConfig
from app.infrastructure.db.models import ScenarioVersion, TrainingSession

DEFAULT_TICK_INTERVAL_MS = 1_000
DEFAULT_SNAPSHOT_INTERVAL_MS = 5_000


def simulation_clock(scenario: ScenarioVersion) -> SimulationClock:
    config = scenario.config_json
    return SimulationClock(
        tick_interval_ms=int(config.get("tick_interval_ms", DEFAULT_TICK_INTERVAL_MS)),
        snapshot_interval_ms=int(config.get("snapshot_interval_ms", DEFAULT_SNAPSHOT_INTERVAL_MS)),
        duration_ms=scenario.duration_ms,
    )


def twin_config(scenario: ScenarioVersion) -> TwinConfig:
    return TwinConfig.from_json(scenario.config_json.get("process_model", {}))


def disturbance_of(training_session: TrainingSession) -> Disturbance:
    """Скрытое возмущение сессии. Читается только расчётом и аудитом."""

    return Disturbance.from_hidden_config(training_session.hidden_runtime_config_json["disturbance"])
