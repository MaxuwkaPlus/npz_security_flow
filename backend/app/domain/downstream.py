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
START_TRANSFER_PUMP = "start_transfer_pump"
SET_FURNACE_HEAT_LOAD = "set_furnace_heat_load"


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
    e15_load_time_constant_ms: int = 30_000
    e15_base_level_pct: float = 52.0
    # Насколько проседает уровень Е-15 при недоборе подачи.
    e15_level_sensitivity_pct: float = 80.0
    e15_level_time_constant_ms: int = 30_000
    k1_load_time_constant_ms: int = 30_000
    k1_base_pressure_bar: float = 1.60
    k1_pressure_sensitivity_bar: float = 1.80
    k1_base_top_temp_c: float = 138.0
    k1_top_temp_sensitivity_c: float = 49.0
    k1_base_bottom_temp_c: float = 268.0
    k1_bottom_temp_sensitivity_c: float = 65.0
    k1_base_level_pct: float = 50.0
    k1_level_sensitivity_pct: float = 65.0
    k1_time_constant_ms: int = 60_000
    furnace_nominal_heat_load_pct: float = 100.0
    furnace_max_heat_load_pct: float = 130.0
    furnace_base_outlet_temp_c: float = 340.0
    # Насколько перегревается продукт при избытке тепла на единицу расхода.
    furnace_outlet_temp_sensitivity_c: float = 112.0
    furnace_time_constant_ms: int = 60_000
    k2_load_time_constant_ms: int = 120_000
    k2_base_pressure_bar: float = 0.62
    k2_pressure_sensitivity_bar: float = 0.65
    k2_base_top_temp_c: float = 142.0
    k2_top_temp_sensitivity_c: float = 33.0
    k2_base_bottom_temp_c: float = 338.0
    k2_bottom_temp_sensitivity_c: float = 74.0
    # Устойчивость К-2 падает и от недобора сырья, и от перегрева печей.
    k2_stability_feed_sensitivity: float = 4.5
    k2_stability_heat_sensitivity: float = 2.0
    k2_time_constant_ms: int = 90_000
    side_draw_stability_sensitivity: float = 5.3
    product_stability_sensitivity: float = 5.9
    product_time_constant_ms: int = 120_000

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
class VesselState:
    """Е-15 и откачивающие насосы Н-20."""

    load_ratio: float
    level_pct: float
    transfer_pump_running: bool


@dataclass(frozen=True, slots=True)
class ColumnState:
    """Первая колонна К-1."""

    feed_ratio: float
    pressure_bar: float
    top_temp_c: float
    bottom_temp_c: float
    level_pct: float


@dataclass(frozen=True, slots=True)
class FurnaceState:
    """Печи П-1…П-3: тепловую нагрузку задаёт оператор, расход приходит из К-1."""

    heat_load_pct: float
    feed_ratio: float
    outlet_temp_c: float


@dataclass(frozen=True, slots=True)
class AtmosphericState:
    """К-2, боковые отборы и продуктовые линии."""

    load_ratio: float
    pressure_bar: float
    top_temp_c: float
    bottom_temp_c: float
    stability_index: float
    side_draw_stability_index: float
    product_stability_index: float


@dataclass(frozen=True, slots=True)
class DownstreamState:
    elou: ElouState
    vessel: VesselState
    k1: ColumnState
    furnaces: FurnaceState
    k2: AtmosphericState

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
            },
            "vessel": {
                "load_ratio": self.vessel.load_ratio,
                "level_pct": self.vessel.level_pct,
                "transfer_pump_running": self.vessel.transfer_pump_running,
            },
            "k1": {
                "feed_ratio": self.k1.feed_ratio,
                "pressure_bar": self.k1.pressure_bar,
                "top_temp_c": self.k1.top_temp_c,
                "bottom_temp_c": self.k1.bottom_temp_c,
                "level_pct": self.k1.level_pct,
            },
            "furnaces": {
                "heat_load_pct": self.furnaces.heat_load_pct,
                "feed_ratio": self.furnaces.feed_ratio,
                "outlet_temp_c": self.furnaces.outlet_temp_c,
            },
            "k2": {
                "load_ratio": self.k2.load_ratio,
                "pressure_bar": self.k2.pressure_bar,
                "top_temp_c": self.k2.top_temp_c,
                "bottom_temp_c": self.k2.bottom_temp_c,
                "stability_index": self.k2.stability_index,
                "side_draw_stability_index": self.k2.side_draw_stability_index,
                "product_stability_index": self.k2.product_stability_index,
            },
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "DownstreamState":
        elou = data.get("elou", {})
        vessel = data.get("vessel", {})
        k1 = data.get("k1", {})
        furnaces = data.get("furnaces", {})
        k2 = data.get("k2", {})
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
            ),
            vessel=VesselState(
                load_ratio=float(vessel.get("load_ratio", 0.0)),
                level_pct=float(vessel.get("level_pct", 0.0)),
                transfer_pump_running=bool(vessel.get("transfer_pump_running", False)),
            ),
            k1=ColumnState(
                feed_ratio=float(k1.get("feed_ratio", 0.0)),
                pressure_bar=float(k1.get("pressure_bar", 0.0)),
                top_temp_c=float(k1.get("top_temp_c", 0.0)),
                bottom_temp_c=float(k1.get("bottom_temp_c", 0.0)),
                level_pct=float(k1.get("level_pct", 0.0)),
            ),
            furnaces=FurnaceState(
                heat_load_pct=float(furnaces.get("heat_load_pct", 0.0)),
                feed_ratio=float(furnaces.get("feed_ratio", 0.0)),
                outlet_temp_c=float(furnaces.get("outlet_temp_c", 0.0)),
            ),
            k2=AtmosphericState(
                load_ratio=float(k2.get("load_ratio", 0.0)),
                pressure_bar=float(k2.get("pressure_bar", 0.0)),
                top_temp_c=float(k2.get("top_temp_c", 0.0)),
                bottom_temp_c=float(k2.get("bottom_temp_c", 0.0)),
                stability_index=float(k2.get("stability_index", 0.0)),
                side_draw_stability_index=float(k2.get("side_draw_stability_index", 0.0)),
                product_stability_index=float(k2.get("product_stability_index", 0.0)),
            ),
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
        ),
        vessel=VesselState(load_ratio=0.0, level_pct=0.0, transfer_pump_running=False),
        k1=ColumnState(feed_ratio=0.0, pressure_bar=0.0, top_temp_c=0.0, bottom_temp_c=0.0, level_pct=0.0),
        furnaces=FurnaceState(heat_load_pct=100.0, feed_ratio=0.0, outlet_temp_c=0.0),
        k2=AtmosphericState(
            load_ratio=0.0,
            pressure_bar=0.0,
            top_temp_c=0.0,
            bottom_temp_c=0.0,
            stability_index=0.0,
            side_draw_stability_index=0.0,
            product_stability_index=0.0,
        ),
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
    vessel = _step_vessel(state.vessel, config, stage2_load_ratio, commands, dt_ms)
    k1 = _step_k1(state.k1, config, vessel, dt_ms)
    furnaces = _step_furnaces(state.furnaces, config, k1, commands, dt_ms)
    k2 = _step_k2(state.k2, config, furnaces, dt_ms)
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
        ),
        vessel=vessel,
        k1=k1,
        furnaces=furnaces,
        k2=k2,
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


def _step_vessel(
    vessel: VesselState,
    config: DownstreamConfig,
    inlet_ratio: float,
    commands: Sequence[Command],
    dt_ms: int,
) -> VesselState:
    """Е-15 принимает поток после ЭЛОУ; дальше его качают насосы Н-20."""

    running = vessel.transfer_pump_running or any(
        command.action_type == START_TRANSFER_PUMP for command in commands
    )
    load_ratio = approach(vessel.load_ratio, inlet_ratio, dt_ms, config.e15_load_time_constant_ms)
    if is_online(load_ratio, config):
        target_level = config.e15_base_level_pct - config.e15_level_sensitivity_pct * max(
            0.0, 1.0 - load_ratio
        )
    else:
        target_level = 0.0
    return VesselState(
        load_ratio=load_ratio,
        level_pct=clamp(
            approach(vessel.level_pct, target_level, dt_ms, config.e15_level_time_constant_ms), 0.0, 100.0
        ),
        transfer_pump_running=running,
    )


def _step_k1(k1: ColumnState, config: DownstreamConfig, vessel: VesselState, dt_ms: int) -> ColumnState:
    """К-1 получает сырьё, только пока работают откачивающие насосы Н-20."""

    inlet_ratio = vessel.load_ratio if vessel.transfer_pump_running else 0.0
    feed_ratio = approach(k1.feed_ratio, inlet_ratio, dt_ms, config.k1_load_time_constant_ms)
    if not is_online(feed_ratio, config):
        return ColumnState(
            feed_ratio=feed_ratio, pressure_bar=0.0, top_temp_c=0.0, bottom_temp_c=0.0, level_pct=0.0
        )

    deficit = max(0.0, 1.0 - feed_ratio)
    tau = config.k1_time_constant_ms
    return ColumnState(
        feed_ratio=feed_ratio,
        pressure_bar=approach(
            k1.pressure_bar,
            config.k1_base_pressure_bar - config.k1_pressure_sensitivity_bar * deficit,
            dt_ms,
            tau,
        ),
        top_temp_c=approach(
            k1.top_temp_c, config.k1_base_top_temp_c - config.k1_top_temp_sensitivity_c * deficit, dt_ms, tau
        ),
        # Меньше сырья при той же тепловой нагрузке — низ колонны греется сильнее.
        bottom_temp_c=approach(
            k1.bottom_temp_c,
            config.k1_base_bottom_temp_c + config.k1_bottom_temp_sensitivity_c * deficit,
            dt_ms,
            tau,
        ),
        level_pct=clamp(
            approach(
                k1.level_pct,
                config.k1_base_level_pct - config.k1_level_sensitivity_pct * deficit,
                dt_ms,
                tau,
            ),
            0.0,
            100.0,
        ),
    )


def heat_to_feed_ratio(state: DownstreamState, config: DownstreamConfig) -> float:
    """Отношение тепловой нагрузки печей к относительному расходу сырья.

    Главный показатель §30 сценария: если расход упал, а нагрузку не снизили,
    отношение растёт — это и есть опасная компенсация симптома.
    """

    furnaces = state.furnaces
    if not is_online(furnaces.feed_ratio, config):
        return 0.0
    heat = furnaces.heat_load_pct / config.furnace_nominal_heat_load_pct
    return heat / max(furnaces.feed_ratio, config.section_min_load_ratio)


def _step_furnaces(
    furnaces: FurnaceState,
    config: DownstreamConfig,
    k1: ColumnState,
    commands: Sequence[Command],
    dt_ms: int,
) -> FurnaceState:
    heat_load = furnaces.heat_load_pct
    for command in commands:
        if command.action_type == SET_FURNACE_HEAT_LOAD:
            requested = float(command.value.get("heat_load_pct", heat_load))
            heat_load = clamp(requested, 0.0, config.furnace_max_heat_load_pct)

    feed_ratio = approach(furnaces.feed_ratio, k1.feed_ratio, dt_ms, config.k1_load_time_constant_ms)
    if not is_online(feed_ratio, config):
        return FurnaceState(heat_load_pct=heat_load, feed_ratio=feed_ratio, outlet_temp_c=0.0)

    excess = max(0.0, heat_load / config.furnace_nominal_heat_load_pct / feed_ratio - 1.0)
    target = config.furnace_base_outlet_temp_c + config.furnace_outlet_temp_sensitivity_c * excess
    return FurnaceState(
        heat_load_pct=heat_load,
        feed_ratio=feed_ratio,
        outlet_temp_c=approach(furnaces.outlet_temp_c, target, dt_ms, config.furnace_time_constant_ms),
    )


def _step_k2(
    k2: AtmosphericState, config: DownstreamConfig, furnaces: FurnaceState, dt_ms: int
) -> AtmosphericState:
    load_ratio = approach(k2.load_ratio, furnaces.feed_ratio, dt_ms, config.k2_load_time_constant_ms)
    if not is_online(load_ratio, config):
        return AtmosphericState(
            load_ratio=load_ratio,
            pressure_bar=0.0,
            top_temp_c=0.0,
            bottom_temp_c=0.0,
            stability_index=0.0,
            side_draw_stability_index=0.0,
            product_stability_index=0.0,
        )

    deficit = max(0.0, 1.0 - load_ratio)
    heat_excess = max(
        0.0, furnaces.heat_load_pct / config.furnace_nominal_heat_load_pct / max(load_ratio, 0.05) - 1.0
    )
    tau = config.k2_time_constant_ms
    stability = clamp(
        1.0
        - config.k2_stability_feed_sensitivity * deficit
        - config.k2_stability_heat_sensitivity * heat_excess,
        0.0,
        1.0,
    )
    return AtmosphericState(
        load_ratio=load_ratio,
        pressure_bar=approach(
            k2.pressure_bar,
            config.k2_base_pressure_bar + config.k2_pressure_sensitivity_bar * deficit,
            dt_ms,
            tau,
        ),
        top_temp_c=approach(
            k2.top_temp_c, config.k2_base_top_temp_c + config.k2_top_temp_sensitivity_c * deficit, dt_ms, tau
        ),
        bottom_temp_c=approach(
            k2.bottom_temp_c,
            config.k2_base_bottom_temp_c + config.k2_bottom_temp_sensitivity_c * (deficit + heat_excess),
            dt_ms,
            tau,
        ),
        stability_index=approach(k2.stability_index, stability, dt_ms, tau),
        side_draw_stability_index=approach(
            k2.side_draw_stability_index,
            clamp(1.0 - config.side_draw_stability_sensitivity * deficit, 0.0, 1.0),
            dt_ms,
            config.product_time_constant_ms,
        ),
        product_stability_index=approach(
            k2.product_stability_index,
            clamp(1.0 - config.product_stability_sensitivity * deficit, 0.0, 1.0),
            dt_ms,
            config.product_time_constant_ms,
        ),
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
