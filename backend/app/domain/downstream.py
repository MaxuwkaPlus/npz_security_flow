"""Цепочка установки после Т-1…Т-11.

Возмущение распространяется каскадом апериодических звеньев: сначала ЭЛОУ, затем
Е-15 и Н-20, потом К-1, печи и К-2. Каждое звено видит уже сглаженный сигнал
предыдущего, поэтому запаздывание нарастает вниз по цепочке само — так, как описано
в §39 сценария, а не набором отдельных подобранных задержек.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from typing import Any

from app.domain.commands import Command
from app.domain.dynamics import approach, clamp

SET_WASH_WATER = "set_wash_water"

ELOU_SECTION_CODE = "ELOU"


@dataclass(frozen=True, slots=True)
class DownstreamConfig:
    # Участок считается работающим, когда до него дошла заметная доля нагрузки.
    section_min_load_ratio: float = 0.10
    elou_load_time_constant_ms: int = 60_000
    elou_stage2_time_constant_ms: int = 30_000
    # Доля сырьевого рассогласования, доходящая до параллельных ветвей ЭЛОУ.
    elou_imbalance_transfer: float = 0.92
    elou_stage1_base_level_mm: float = 3820.0
    elou_stage2_base_level_mm: float = 3840.0
    # Насколько падает уровень при недоборе полной нагрузки.
    elou_stage1_level_sensitivity_mm: float = 4600.0
    elou_stage2_level_sensitivity_mm: float = 4200.0
    # Блокировка высоковольтной секции по уровню (сценарий, §25).
    elou_low_level_interlock_mm: float = 3500.0
    elou_temperature_offset_c: float = -2.0
    elou_level_time_constant_ms: int = 30_000
    # Уровень, при котором ступень считается выведенной в работу и защита взводится.
    elou_operating_level_mm: float = 3700.0
    wash_water_max_ratio: float = 0.20

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "DownstreamConfig":
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass(frozen=True, slots=True)
class ElouState:
    """Блок ЭЛОУ: две ступени обезвоживания и обессоливания."""

    wash_water_ratio: float
    load_ratio: float
    stage2_load_ratio: float
    imbalance_ratio: float
    stage1_level_mm: float
    stage2_level_mm: float
    temperature_c: float
    # Защита по низкому уровню взводится только после вывода ступени в работу:
    # при наполнении аппарата уровень законно ниже блокировочного.
    stage1_in_operation: bool
    stage2_in_operation: bool


@dataclass(frozen=True, slots=True)
class DownstreamState:
    elou: ElouState

    def to_json(self) -> dict[str, Any]:
        return {
            "elou": {
                "wash_water_ratio": self.elou.wash_water_ratio,
                "load_ratio": self.elou.load_ratio,
                "stage2_load_ratio": self.elou.stage2_load_ratio,
                "imbalance_ratio": self.elou.imbalance_ratio,
                "stage1_level_mm": self.elou.stage1_level_mm,
                "stage2_level_mm": self.elou.stage2_level_mm,
                "temperature_c": self.elou.temperature_c,
                "stage1_in_operation": self.elou.stage1_in_operation,
                "stage2_in_operation": self.elou.stage2_in_operation,
            }
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "DownstreamState":
        elou = data.get("elou", {})
        return cls(
            elou=ElouState(
                wash_water_ratio=float(elou.get("wash_water_ratio", 0.0)),
                load_ratio=float(elou.get("load_ratio", 0.0)),
                stage2_load_ratio=float(elou.get("stage2_load_ratio", 0.0)),
                imbalance_ratio=float(elou.get("imbalance_ratio", 0.0)),
                stage1_level_mm=float(elou.get("stage1_level_mm", 0.0)),
                stage2_level_mm=float(elou.get("stage2_level_mm", 0.0)),
                temperature_c=float(elou.get("temperature_c", 0.0)),
                stage1_in_operation=bool(elou.get("stage1_in_operation", False)),
                stage2_in_operation=bool(elou.get("stage2_in_operation", False)),
            )
        )


def initial_downstream_state() -> DownstreamState:
    """Установка подготовлена, но поток по цепочке ещё не пошёл."""

    return DownstreamState(
        elou=ElouState(
            wash_water_ratio=0.0,
            load_ratio=0.0,
            stage2_load_ratio=0.0,
            imbalance_ratio=0.0,
            stage1_level_mm=0.0,
            stage2_level_mm=0.0,
            temperature_c=0.0,
            stage1_in_operation=False,
            stage2_in_operation=False,
        )
    )


def step_downstream(
    state: DownstreamState,
    config: DownstreamConfig,
    *,
    feed_ratio: float,
    flow_imbalance_ratio: float,
    feed_temperature_c: float,
    dt_ms: int,
    commands: Sequence[Command] = (),
) -> DownstreamState:
    elou = _apply_commands(state.elou, config, commands)

    load_ratio = approach(elou.load_ratio, feed_ratio, dt_ms, config.elou_load_time_constant_ms)
    stage2_load_ratio = approach(
        elou.stage2_load_ratio, load_ratio, dt_ms, config.elou_stage2_time_constant_ms
    )
    imbalance = approach(
        elou.imbalance_ratio,
        flow_imbalance_ratio * config.elou_imbalance_transfer,
        dt_ms,
        config.elou_load_time_constant_ms,
    )
    stage1_level = _level(
        elou.stage1_level_mm,
        load_ratio,
        config,
        config.elou_stage1_base_level_mm,
        config.elou_stage1_level_sensitivity_mm,
        dt_ms,
    )
    stage2_level = _level(
        elou.stage2_level_mm,
        stage2_load_ratio,
        config,
        config.elou_stage2_base_level_mm,
        config.elou_stage2_level_sensitivity_mm,
        dt_ms,
    )
    return DownstreamState(
        elou=replace(
            elou,
            load_ratio=load_ratio,
            stage2_load_ratio=stage2_load_ratio,
            imbalance_ratio=imbalance,
            stage1_level_mm=stage1_level,
            stage2_level_mm=stage2_level,
            stage1_in_operation=elou.stage1_in_operation or stage1_level >= config.elou_operating_level_mm,
            stage2_in_operation=elou.stage2_in_operation or stage2_level >= config.elou_operating_level_mm,
            temperature_c=(
                feed_temperature_c + config.elou_temperature_offset_c
                if is_online(load_ratio, config)
                else 0.0
            ),
        )
    )


def is_online(load_ratio: float, config: DownstreamConfig) -> bool:
    return load_ratio >= config.section_min_load_ratio


def hv_trip_count(state: DownstreamState, config: DownstreamConfig) -> int:
    """Число ступеней с уровнем ниже блокировочного: высоковольтная секция отключена."""

    stages = (
        (state.elou.stage1_in_operation, state.elou.stage1_level_mm),
        (state.elou.stage2_in_operation, state.elou.stage2_level_mm),
    )
    return sum(
        1 for in_operation, level in stages if in_operation and level < config.elou_low_level_interlock_mm
    )


def _apply_commands(elou: ElouState, config: DownstreamConfig, commands: Sequence[Command]) -> ElouState:
    for command in commands:
        if command.action_type != SET_WASH_WATER:
            continue
        requested = float(command.value.get("ratio", elou.wash_water_ratio))
        elou = replace(elou, wash_water_ratio=clamp(requested, 0.0, config.wash_water_max_ratio))
    return elou


def _level(
    current: float,
    load_ratio: float,
    config: DownstreamConfig,
    base_level_mm: float,
    sensitivity_mm: float,
    dt_ms: int,
) -> float:
    if not is_online(load_ratio, config):
        return approach(current, 0.0, dt_ms, config.elou_level_time_constant_ms)
    target = base_level_mm - sensitivity_mm * max(0.0, 1.0 - load_ratio)
    return approach(current, max(0.0, target), dt_ms, config.elou_level_time_constant_ms)
