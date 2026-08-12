"""Детерминированный упрощённый двойник сырьевой части и Т-1…Т-11.

Модель намеренно простая и полностью воспроизводимая: измерительного шума нет, все
коэффициенты приходят из версии сценария. Причинность обеспечивают апериодические
звенья — команда не меняет установку мгновенно (§6 технического задания).

Ключевая технологическая связь этапа: при снижении расхода через теплообменную цепочку
проходит меньше сырья, а тепловая нагрузка остаётся прежней, поэтому температура после
Т-1…Т-11 растёт. Именно это оператор видит как вторичный симптом (сценарий, §38–39).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from typing import Any

from app.domain.commands import Command
from app.domain.downstream import (
    DownstreamConfig,
    DownstreamState,
    initial_downstream_state,
    step_downstream,
)
from app.domain.dynamics import approach, clamp

BRANCH_COUNT = 3

START_FEED_PUMP = "start_feed_pump"
SET_CONTROL_VALVE = "set_control_valve"
SWITCH_TO_STANDBY_PUMP = "switch_to_standby_pump"
RESTORE_FLOW_CONTROL = "restore_flow_control"


@dataclass(frozen=True, slots=True)
class TwinConfig:
    branch_controller_codes: tuple[str, ...] = ("FRC-404", "FRC-405", "FRC-406")
    nominal_branch_flow_tph: float = 100.0
    nominal_branch_pressure_bar: float = 5.0
    nominal_pump_discharge_pressure_bar: float = 6.0
    ambient_temp_c: float = 25.0
    # Прирост температуры после Т-1…Т-11 при номинальном расходе и прогретой установке.
    t11_duty_c: float = 105.0
    # Показатель чувствительности температуры к падению расхода.
    t11_flow_sensitivity: float = 0.35
    t11_temperature_limit_c: float = 140.0
    t11_temperature_margin_span_c: float = 15.0
    flow_time_constant_ms: int = 60_000
    pressure_time_constant_ms: int = 20_000
    temperature_time_constant_ms: int = 90_000
    warmup_time_constant_ms: int = 300_000
    warmup_min_flow_ratio: float = 0.5
    # Расход, при котором установка считается выведенной на режим.
    operating_mode_flow_ratio: float = 0.95
    # Коэффициенты участков после Т-1…Т-11 разбираются отдельным конфигом.
    downstream: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "TwinConfig":
        known = {field.name for field in fields(cls)}
        values = {key: value for key, value in data.items() if key in known}
        if "branch_controller_codes" in values:
            values["branch_controller_codes"] = tuple(values["branch_controller_codes"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class Disturbance:
    """Скрытое возмущение в виде, нужном расчёту. В операторский DTO не попадает."""

    target_branch: int
    onset_sim_time_ms: int
    correct_action_type: str
    ramp_duration_ms: int = 360_000
    recovery_duration_ms: int = 180_000
    target_branch_flow_loss: float = 0.0
    other_branch_flow_gain: float = 0.0
    target_branch_pressure_drop_bar: float = 0.0
    pump_discharge_pressure_drop_bar: float = 0.0
    valve_actual_offset_pct: float = 0.0

    @classmethod
    def from_hidden_config(cls, data: Mapping[str, Any]) -> "Disturbance":
        development = data.get("development", {})
        recovery = data.get("recovery", {})
        return cls(
            target_branch=int(data["target_branch"]),
            onset_sim_time_ms=int(data["onset_sim_time_ms"]),
            correct_action_type=str(recovery.get("correct_action_type", "")),
            ramp_duration_ms=int(development.get("ramp_duration_ms", 360_000)),
            recovery_duration_ms=int(recovery.get("recovery_duration_ms", 180_000)),
            target_branch_flow_loss=float(development.get("target_branch_flow_loss", 0.0)),
            other_branch_flow_gain=float(development.get("other_branch_flow_gain", 0.0)),
            target_branch_pressure_drop_bar=float(development.get("target_branch_pressure_drop_bar", 0.0)),
            pump_discharge_pressure_drop_bar=float(development.get("pump_discharge_pressure_drop_bar", 0.0)),
            valve_actual_offset_pct=float(development.get("valve_actual_offset_pct", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class BranchState:
    flow_tph: float
    pressure_bar: float
    valve_command_pct: float
    valve_actual_pct: float
    outlet_temp_c: float


@dataclass(frozen=True, slots=True)
class PlantState:
    branches: tuple[BranchState, ...]
    pump_running: bool
    active_pump_code: str
    pump_discharge_pressure_bar: float
    warmup: float
    severity: float
    corrected: bool
    # Один раз выведенная на режим установка остаётся «в режиме»: дальнейшее падение
    # расхода — уже отклонение, а не продолжающийся пуск.
    operating_mode: bool
    downstream: DownstreamState

    def to_json(self) -> dict[str, Any]:
        return {
            "branches": [
                {
                    "flow_tph": branch.flow_tph,
                    "pressure_bar": branch.pressure_bar,
                    "valve_command_pct": branch.valve_command_pct,
                    "valve_actual_pct": branch.valve_actual_pct,
                    "outlet_temp_c": branch.outlet_temp_c,
                }
                for branch in self.branches
            ],
            "pump_running": self.pump_running,
            "active_pump_code": self.active_pump_code,
            "pump_discharge_pressure_bar": self.pump_discharge_pressure_bar,
            "warmup": self.warmup,
            "severity": self.severity,
            "corrected": self.corrected,
            "operating_mode": self.operating_mode,
            "downstream": self.downstream.to_json(),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "PlantState":
        return cls(
            branches=tuple(
                BranchState(
                    flow_tph=float(branch["flow_tph"]),
                    pressure_bar=float(branch["pressure_bar"]),
                    valve_command_pct=float(branch["valve_command_pct"]),
                    valve_actual_pct=float(branch["valve_actual_pct"]),
                    outlet_temp_c=float(branch["outlet_temp_c"]),
                )
                for branch in data["branches"]
            ),
            pump_running=bool(data["pump_running"]),
            active_pump_code=str(data["active_pump_code"]),
            pump_discharge_pressure_bar=float(data["pump_discharge_pressure_bar"]),
            warmup=float(data["warmup"]),
            severity=float(data["severity"]),
            corrected=bool(data["corrected"]),
            operating_mode=bool(data.get("operating_mode", False)),
            downstream=DownstreamState.from_json(data.get("downstream", {})),
        )


def initial_state(config: TwinConfig) -> PlantState:
    """Установка подготовлена к работе: схема собрана, поток ещё не подан."""

    branch = BranchState(
        flow_tph=0.0,
        pressure_bar=0.0,
        valve_command_pct=100.0,
        valve_actual_pct=100.0,
        outlet_temp_c=config.ambient_temp_c,
    )
    return PlantState(
        branches=tuple(branch for _ in range(BRANCH_COUNT)),
        pump_running=False,
        active_pump_code="N-1",
        pump_discharge_pressure_bar=0.0,
        warmup=0.0,
        severity=0.0,
        corrected=False,
        operating_mode=False,
        downstream=initial_downstream_state(),
    )


def step(
    state: PlantState,
    config: TwinConfig,
    disturbance: Disturbance,
    *,
    sim_time_ms: int,
    dt_ms: int,
    commands: Sequence[Command] = (),
) -> PlantState:
    """Одно состояние установки на следующий момент симуляционного времени."""

    state = _apply_commands(state, config, disturbance, commands)
    severity = _advance_severity(state, disturbance, sim_time_ms, dt_ms)
    pump_pressure = _pump_pressure(state, config, disturbance, severity, dt_ms)

    branches = tuple(
        _step_branch(branch, index + 1, state, config, disturbance, severity, dt_ms)
        for index, branch in enumerate(state.branches)
    )
    total_ratio = sum(branch.flow_tph for branch in branches) / (
        config.nominal_branch_flow_tph * BRANCH_COUNT
    )
    warmup = approach(
        state.warmup,
        1.0 if total_ratio >= config.warmup_min_flow_ratio else 0.0,
        dt_ms,
        config.warmup_time_constant_ms,
    )
    min_flow_ratio = min(branch.flow_tph for branch in branches) / config.nominal_branch_flow_tph
    flows = [branch.flow_tph for branch in branches]
    mean_flow = sum(flows) / BRANCH_COUNT
    downstream = step_downstream(
        state.downstream,
        DownstreamConfig.from_json(config.downstream),
        feed_ratio=total_ratio,
        flow_imbalance_ratio=(max(flows) - min(flows)) / mean_flow if mean_flow > 1.0 else 0.0,
        feed_temperature_c=sum(branch.outlet_temp_c for branch in branches) / BRANCH_COUNT,
        dt_ms=dt_ms,
        commands=commands,
    )
    return replace(
        state,
        branches=branches,
        pump_discharge_pressure_bar=pump_pressure,
        warmup=warmup,
        severity=severity,
        operating_mode=state.operating_mode or min_flow_ratio >= config.operating_mode_flow_ratio,
        downstream=downstream,
    )


def _apply_commands(
    state: PlantState, config: TwinConfig, disturbance: Disturbance, commands: Sequence[Command]
) -> PlantState:
    branches = list(state.branches)
    pump_running = state.pump_running
    active_pump_code = state.active_pump_code
    corrected = state.corrected

    for command in commands:
        if command.action_type in (START_FEED_PUMP, SWITCH_TO_STANDBY_PUMP):
            pump_running = True
            active_pump_code = command.target_code
        elif command.action_type in (SET_CONTROL_VALVE, RESTORE_FLOW_CONTROL):
            index = _branch_index(config, command.target_code)
            if index is not None:
                branches[index] = replace(
                    branches[index], valve_command_pct=_opening(command, branches[index])
                )
        if _is_corrective(command, config, disturbance):
            corrected = True

    return replace(
        state,
        branches=tuple(branches),
        pump_running=pump_running,
        active_pump_code=active_pump_code,
        corrected=corrected,
    )


def _opening(command: Command, branch: BranchState) -> float:
    if command.action_type == RESTORE_FLOW_CONTROL:
        return 100.0
    return clamp(float(command.value.get("opening_pct", branch.valve_command_pct)), 0.0, 100.0)


def _is_corrective(command: Command, config: TwinConfig, disturbance: Disturbance) -> bool:
    """Действие устраняет причину, только если совпадает и тип, и адрес воздействия."""

    if command.action_type != disturbance.correct_action_type:
        return False
    index = _branch_index(config, command.target_code)
    if index is None:
        # Насосное воздействие адресуется оборудованием, а не сырьевой ветвью.
        return True
    return index + 1 == disturbance.target_branch


def _advance_severity(state: PlantState, disturbance: Disturbance, sim_time_ms: int, dt_ms: int) -> float:
    if state.corrected:
        return max(0.0, state.severity - dt_ms / disturbance.recovery_duration_ms)
    if sim_time_ms < disturbance.onset_sim_time_ms:
        return 0.0
    return min(1.0, state.severity + dt_ms / disturbance.ramp_duration_ms)


def _pump_pressure(
    state: PlantState, config: TwinConfig, disturbance: Disturbance, severity: float, dt_ms: int
) -> float:
    target = 0.0
    if state.pump_running:
        target = config.nominal_pump_discharge_pressure_bar
        target -= disturbance.pump_discharge_pressure_drop_bar * severity
    return approach(state.pump_discharge_pressure_bar, target, dt_ms, config.pressure_time_constant_ms)


def _step_branch(
    branch: BranchState,
    branch_no: int,
    state: PlantState,
    config: TwinConfig,
    disturbance: Disturbance,
    severity: float,
    dt_ms: int,
) -> BranchState:
    is_target = branch_no == disturbance.target_branch
    valve_actual = branch.valve_command_pct
    if is_target:
        valve_actual -= disturbance.valve_actual_offset_pct * severity
    valve_actual = clamp(valve_actual, 0.0, 100.0)

    flow_factor = valve_actual / 100.0
    if is_target:
        flow_factor *= 1.0 - disturbance.target_branch_flow_loss * severity
    else:
        flow_factor *= 1.0 + disturbance.other_branch_flow_gain * severity
    target_flow = config.nominal_branch_flow_tph * flow_factor if state.pump_running else 0.0
    flow = approach(branch.flow_tph, max(0.0, target_flow), dt_ms, config.flow_time_constant_ms)

    target_pressure = 0.0
    if state.pump_running:
        target_pressure = config.nominal_branch_pressure_bar
        if is_target:
            target_pressure -= disturbance.target_branch_pressure_drop_bar * severity
    pressure = approach(branch.pressure_bar, target_pressure, dt_ms, config.pressure_time_constant_ms)

    return BranchState(
        flow_tph=flow,
        pressure_bar=pressure,
        valve_command_pct=branch.valve_command_pct,
        valve_actual_pct=valve_actual,
        outlet_temp_c=_step_temperature(branch, flow, state.warmup, config, dt_ms),
    )


def _step_temperature(
    branch: BranchState, flow_tph: float, warmup: float, config: TwinConfig, dt_ms: int
) -> float:
    # Меньше расход при той же тепловой нагрузке — выше температура на выходе цепочки.
    flow_ratio = max(flow_tph / config.nominal_branch_flow_tph, 0.05)
    target = config.ambient_temp_c + config.t11_duty_c * warmup * flow_ratio**-config.t11_flow_sensitivity
    return approach(branch.outlet_temp_c, target, dt_ms, config.temperature_time_constant_ms)


def _branch_index(config: TwinConfig, target_code: str) -> int | None:
    codes = config.branch_controller_codes
    return codes.index(target_code) if target_code in codes else None
