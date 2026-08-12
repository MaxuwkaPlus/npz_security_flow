"""Разбор опубликованной конфигурации в объекты домена.

Версия сценария неизменяема, поэтому разбор чистый и результат можно кэшировать.
"""

from app.domain.clock import SimulationClock
from app.domain.commands import ControlPolicy
from app.domain.nuisance import NuisancePolicy
from app.domain.observations import ChecksPolicy
from app.domain.safety import SafetyPolicy
from app.domain.sagat import SagatPolicy
from app.domain.twin import Disturbance, TwinConfig
from app.infrastructure.db.models import ScenarioLevel, ScenarioVersion, TrainingSession

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


def control_policy(scenario: ScenarioVersion) -> ControlPolicy:
    return ControlPolicy.from_json(scenario.config_json.get("control_actions", {}))


def nuisance_policy(scenario: ScenarioVersion, level: ScenarioLevel) -> NuisancePolicy:
    """Интенсивность помех берётся из уровня сложности, состав — из версии сценария."""

    return NuisancePolicy.from_json(
        scenario.config_json.get("nuisance_alarms", {}), level.nuisance_alarm_rate
    )


def checks_policy(scenario: ScenarioVersion) -> ChecksPolicy:
    return ChecksPolicy.from_json(scenario.config_json.get("stage_checks", {}))


def sagat_policy(scenario: ScenarioVersion) -> SagatPolicy:
    return SagatPolicy.from_json(scenario.config_json.get("sagat", {}))


def safety_policy(scenario: ScenarioVersion) -> SafetyPolicy:
    return SafetyPolicy.from_json(scenario.config_json.get("safety", {}))


# Пока устойчивый режим не подтверждён, возмущения нет: момент вынесен за горизонт сценария.
NEVER_MS = 1 << 60


def disturbance_of(training_session: TrainingSession, armed_at_ms: int | None) -> Disturbance:
    """Скрытое возмущение сессии. Читается только расчётом и аудитом."""

    hidden = training_session.hidden_runtime_config_json["disturbance"]
    onset = NEVER_MS if armed_at_ms is None else armed_at_ms + int(hidden["onset_delay_ms"])
    return Disturbance.from_hidden_config(hidden, onset)


def disturbance_after_stage(training_session: TrainingSession) -> str:
    hidden = training_session.hidden_runtime_config_json["disturbance"]
    return str(hidden["after_stage_code"])
