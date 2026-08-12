"""Сквозной сценарий ЭЛОУ-АВТ, версия 1.

Все пороги, окна и веса демонстрационные (`provisional`) в смысле §23 технического
задания: они пригодны для показа и воспроизводимости, но не являются технологическим
нормативом до подтверждения технологом. Каркас времени взят из таблицы «время —
состояние» сценария (§47), состав этапов — из §7 технического задания.
"""

from dataclasses import dataclass, field
from typing import Any

from app.domain.rules import Rule, condition, rule
from app.infrastructure.seed.installation import (
    BRANCH_CONTROLLERS,
    ELOU_LOW_LEVEL_INTERLOCK_MM,
    NOMINAL_BRANCH_FLOW_TPH,
    T11_TEMPERATURE_LIMIT_C,
)

SCENARIO_CODE = "ELOU-AVT-FULL-RUN"
SCENARIO_VERSION = 1
SCENARIO_DURATION_MS = 3_900_000
STABILITY_CONFIRMATION_MS = 20_000


@dataclass(frozen=True)
class StageSpec:
    code: str
    nominal_duration_ms: int
    success: Rule
    required_checks: tuple[str, ...] = ()
    failure: Rule = field(default_factory=Rule)

    @property
    def timeout_ms(self) -> int:
        # Время — ориентир: этап закрывается по истечении двойной номинальной длительности.
        return self.nominal_duration_ms * 2


@dataclass(frozen=True)
class LevelSpec:
    level_no: int
    sensor_delay_ms: int
    nuisance_alarm_rate: float
    reaction_deadline_ms: int
    development_speed_factor: float
    hints_enabled: bool
    standby_pump_start_delay_ms: int


@dataclass(frozen=True)
class AlarmRuleSpec:
    code: str
    level: str
    equipment_code: str
    trigger: Rule
    clear: Rule
    message_template: str
    activation_delay_ms: int = 5_000
    ack_required: bool = True


@dataclass(frozen=True)
class DisturbanceSpec:
    code: str
    cause_code: str
    development: dict[str, Any]
    recovery: dict[str, Any]


@dataclass(frozen=True)
class ExpectedActionSpec:
    order_no: int
    action_type: str
    target_selector: str
    weight: float
    criticality: str = "normal"
    preconditions: tuple[str, ...] = ()
    valid_window_ms: int = 600_000
    expected_effect: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)


STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        "precheck",
        120_000,
        rule(),
        required_checks=("feed_system_ready", "heat_exchangers_ready", "elou_ready", "atmospheric_ready"),
    ),
    StageSpec(
        "feed_preparation",
        120_000,
        rule(condition("feed_pump_discharge_pressure_bar", ">=", 5.0), hold_ms=5_000),
    ),
    StageSpec("feed_startup", 180_000, rule(condition("min_branch_flow_ratio", ">=", 0.5), hold_ms=10_000)),
    StageSpec("t1_t3", 180_000, rule(condition("min_branch_flow_ratio", ">=", 0.90), hold_ms=15_000)),
    StageSpec("t4_t7", 180_000, rule(condition("flow_imbalance_ratio", "<=", 0.05), hold_ms=15_000)),
    StageSpec(
        "t7_t11",
        180_000,
        rule(
            condition("t11_max_temp_c", "<=", 140.0),
            condition("t11_min_temp_c", ">=", 120.0),
            hold_ms=15_000,
        ),
    ),
    StageSpec(
        "elou_feed_and_water",
        180_000,
        rule(
            condition("elou_wash_water_ratio", ">=", 0.05),
            condition("elou_wash_water_ratio", "<=", 0.10),
            hold_ms=15_000,
        ),
    ),
    StageSpec(
        "elou_stage_1", 180_000, rule(condition("elou_stage1_min_level_mm", ">=", 3700.0), hold_ms=20_000)
    ),
    StageSpec(
        "elou_stage_2", 180_000, rule(condition("elou_stage2_min_level_mm", ">=", 3700.0), hold_ms=20_000)
    ),
    StageSpec(
        "e15",
        180_000,
        rule(condition("e15_level_pct", ">=", 40.0), condition("e15_level_pct", "<=", 60.0), hold_ms=20_000),
    ),
    StageSpec(
        "post_elou_heating", 240_000, rule(condition("k1_feed_flow_ratio", ">=", 0.90), hold_ms=20_000)
    ),
    StageSpec(
        "k1",
        240_000,
        rule(
            condition("k1_bottom_temp_c", "<=", 280.0),
            condition("k1_level_pct", ">=", 40.0),
            hold_ms=20_000,
        ),
    ),
    StageSpec(
        "furnaces",
        240_000,
        rule(
            condition("furnace_heat_to_feed_ratio", ">=", 0.95),
            condition("furnace_heat_to_feed_ratio", "<=", 1.05),
            hold_ms=20_000,
        ),
    ),
    StageSpec("k2", 300_000, rule(condition("k2_stability_index", ">=", 0.85), hold_ms=20_000)),
    StageSpec(
        "side_draws_and_products",
        300_000,
        rule(
            condition("side_draw_stability_index", ">=", 0.85),
            condition("product_flow_stability_index", ">=", 0.85),
            hold_ms=20_000,
        ),
    ),
    # Устойчивый режим: обязательные параметры непрерывно в допустимой области (§16.6).
    StageSpec(
        "stable_mode",
        120_000,
        rule(
            condition("min_branch_flow_ratio", ">=", 0.95),
            condition("flow_imbalance_ratio", "<=", 0.05),
            condition("t11_max_temp_c", "<=", 140.0),
            condition("k1_feed_flow_ratio", ">=", 0.95),
            condition("k2_stability_index", ">=", 0.85),
            hold_ms=STABILITY_CONFIRMATION_MS,
        ),
    ),
    StageSpec("disturbance_monitoring", 180_000, rule(), required_checks=("declare_deviation",)),
    StageSpec(
        "diagnosis_and_correction",
        180_000,
        rule(),
        required_checks=("submit_diagnosis", "corrective_action"),
    ),
    StageSpec(
        "recovery",
        240_000,
        rule(condition("min_branch_flow_ratio", ">=", 0.95), hold_ms=STABILITY_CONFIRMATION_MS),
    ),
    StageSpec(
        "final_stabilization",
        180_000,
        rule(
            condition("flow_imbalance_ratio", "<=", 0.05),
            condition("t11_max_temp_c", "<=", 140.0),
            condition("k1_feed_flow_ratio", ">=", 0.95),
            condition("k2_stability_index", ">=", 0.85),
            condition("product_flow_stability_index", ">=", 0.85),
            hold_ms=STABILITY_CONFIRMATION_MS,
        ),
        required_checks=(
            "verify_t11",
            "verify_elou",
            "verify_e15",
            "verify_k1",
            "verify_furnaces",
            "verify_k2",
            "verify_products",
        ),
    ),
)

LEVELS: tuple[LevelSpec, ...] = (
    LevelSpec(1, 0, 0.4, 120_000, 0.80, True, 0),
    LevelSpec(2, 2_500, 2.0, 90_000, 1.00, True, 30_000),
    LevelSpec(3, 6_000, 4.5, 60_000, 1.60, False, 60_000),
)

# Основная цепочка эскалации L1…L5 (§11 ТЗ, §42 сценария) и защитные тревоги установки.
ALARM_RULES: tuple[AlarmRuleSpec, ...] = (
    AlarmRuleSpec(
        "flow_deviation_branch",
        "L1",
        "FEED-SYSTEM",
        rule(
            condition("plant_operating_mode", ">=", 1.0),
            condition("min_branch_flow_ratio", "<", 0.92),
        ),
        rule(condition("min_branch_flow_ratio", ">=", 0.95)),
        "Отклонение расхода сырьевой ветви",
    ),
    AlarmRuleSpec(
        "feed_flow_imbalance",
        "L2",
        "FEED-SYSTEM",
        rule(
            condition("plant_operating_mode", ">=", 1.0),
            condition("flow_imbalance_ratio", ">", 0.12),
        ),
        rule(condition("flow_imbalance_ratio", "<=", 0.08)),
        "Рассогласование трёх потоков сырой нефти",
    ),
    AlarmRuleSpec(
        "t11_temperature_deviation",
        "L3",
        "T-1_T-11",
        rule(condition("t11_max_temp_c", ">", 140.0)),
        rule(condition("t11_max_temp_c", "<=", 138.0)),
        "Температура после теплообменной группы выше ограничения",
    ),
    AlarmRuleSpec(
        "elou_load_imbalance",
        "L4",
        "ELOU",
        rule(condition("elou_load_imbalance_ratio", ">", 0.18)),
        rule(condition("elou_load_imbalance_ratio", "<=", 0.12)),
        "Изменение нагрузки ЭЛОУ",
    ),
    AlarmRuleSpec(
        "k1_feed_deviation",
        "L5",
        "K-1",
        rule(
            condition("k1_in_operation", ">=", 1.0),
            condition("k1_feed_flow_ratio", "<", 0.91),
        ),
        rule(condition("k1_feed_flow_ratio", ">=", 0.95)),
        "Отклонение подачи на К-1",
    ),
    AlarmRuleSpec(
        "elou_low_level_interlock",
        "L5",
        "ELOU",
        rule(condition("elou_hv_trip_count", ">", 0.0)),
        rule(condition("elou_hv_trip_count", "<=", 0.0)),
        "Уровень электродегидратора ниже 3500 мм: высоковольтная секция отключена",
        activation_delay_ms=0,
    ),
    AlarmRuleSpec(
        "unsafe_furnace_heat_to_feed",
        "L5",
        "FURNACES",
        rule(
            condition("furnace_online", ">=", 1.0),
            condition("furnace_heat_to_feed_ratio", ">", 1.25),
        ),
        rule(condition("furnace_heat_to_feed_ratio", "<=", 1.10)),
        "Опасное соотношение тепловой нагрузки печей и расхода сырья",
    ),
    AlarmRuleSpec(
        "k2_critical_instability",
        "L5",
        "K-2",
        rule(
            condition("k2_in_operation", ">=", 1.0),
            condition("k2_stability_index", "<", 0.55),
        ),
        rule(condition("k2_stability_index", ">=", 0.70)),
        "Критическое снижение устойчивости К-2",
    ),
)

# Возмущение вводится после подтверждения устойчивого режима (§10 ТЗ, §37 сценария).
# Задержка отсчитывается от завершения этапа, а не от начала сценария.
DISTURBANCE_ONSET = {
    "after_stage_code": "stable_mode",
    "earliest_delay_ms": 0,
    "latest_delay_ms": 120_000,
}
DISTURBANCE_ELIGIBLE_BRANCHES = [1, 2, 3]

# Каждая причина действует через собственный наблюдаемый признак: потеря
# производительности насоса видна по давлению, заедание регулятора — по расхождению
# командного и фактического положения. Именно это различие оператор и диагностирует.
DISTURBANCES: tuple[DisturbanceSpec, ...] = (
    DisturbanceSpec(
        "feed_pump_capacity_loss",
        "pump_capacity_loss",
        development={
            "ramp_duration_ms": 360_000,
            "target_branch_flow_loss": 0.38,
            "other_branch_flow_gain": 0.015,
            "target_branch_pressure_drop_bar": 1.15,
            "pump_discharge_pressure_drop_bar": 1.0,
            "valve_actual_offset_pct": 0.0,
        },
        recovery={"correct_action_type": "switch_to_standby_pump", "recovery_duration_ms": 180_000},
    ),
    DisturbanceSpec(
        "flow_control_valve_stiction",
        "valve_stiction",
        development={
            "ramp_duration_ms": 360_000,
            # Расход падает не сам по себе, а вслед за фактическим положением регулятора.
            "target_branch_flow_loss": 0.0,
            "other_branch_flow_gain": 0.015,
            "target_branch_pressure_drop_bar": 0.75,
            "pump_discharge_pressure_drop_bar": -0.25,
            "valve_actual_offset_pct": 42.0,
        },
        recovery={"correct_action_type": "restore_flow_control", "recovery_duration_ms": 180_000},
    ),
)

BRANCH_CONTROLLER_CODES = [BRANCH_CONTROLLERS[branch] for branch in sorted(BRANCH_CONTROLLERS)]

# Allowlist органов управления: всё, что вне списка и диапазонов, отклоняется сервером.
CONTROL_ACTIONS: dict[str, Any] = {
    "start_feed_pump": {"targets": ["N-1", "N-1A"]},
    "switch_to_standby_pump": {"targets": ["N-1A"]},
    "set_control_valve": {
        "targets": BRANCH_CONTROLLER_CODES,
        "value_bounds": {"opening_pct": [0.0, 100.0]},
    },
    "restore_flow_control": {"targets": BRANCH_CONTROLLER_CODES},
    # Вода на смешение: 5–10 % от расхода нефти по регламенту, ввод ограничен 20 %.
    "set_wash_water": {"targets": ["ELOU"], "value_bounds": {"ratio": [0.0, 0.20]}},
    "start_transfer_pump": {"targets": ["N-20", "N-20A", "N-20B"]},
    "set_furnace_heat_load": {
        "targets": ["FURNACES"],
        "value_bounds": {"heat_load_pct": [0.0, 130.0]},
    },
}

# Чем закрывается обязательная проверка этапа. Оператор фиксирует проверку явно,
# поэтому соответствие «наблюдение → проверка» описано здесь, а не выводится из UI.
STAGE_CHECKS: dict[str, Any] = {
    "feed_system_ready": {"observation_type": "inspect_equipment", "target_code": "FEED-SYSTEM"},
    "heat_exchangers_ready": {"observation_type": "inspect_equipment", "target_code": "T-1_T-11"},
    "elou_ready": {"observation_type": "inspect_equipment", "target_code": "ELOU"},
    "atmospheric_ready": {"observation_type": "inspect_equipment", "target_code": "K-2"},
    "declare_deviation": {"observation_type": "declare_deviation", "target_code": "FEED-SYSTEM"},
    "compare_flows": {"observation_type": "compare_flows", "target_code": "FEED-SYSTEM"},
    "inspect_pressure": {"observation_type": "inspect_pressure", "target_code": "FEED-SYSTEM"},
    "inspect_pump": {"observation_type": "inspect_equipment", "target_code": "N-1"},
    "submit_diagnosis": {"by_diagnosis": True},
    "corrective_action": {"action_types": ["switch_to_standby_pump", "restore_flow_control"]},
    "verify_flow": {"observation_type": "verify_result", "target_code": "FEED-SYSTEM"},
    "verify_t11": {"observation_type": "verify_result", "target_code": "T-1_T-11"},
    "verify_elou": {"observation_type": "verify_result", "target_code": "ELOU"},
    "verify_e15": {"observation_type": "verify_result", "target_code": "V-15"},
    "verify_k1": {"observation_type": "verify_result", "target_code": "K-1"},
    "verify_furnaces": {"observation_type": "verify_result", "target_code": "FURNACES"},
    "verify_k2": {"observation_type": "verify_result", "target_code": "K-2"},
    "verify_products": {"observation_type": "verify_result", "target_code": "PRODUCTS"},
}

# Второстепенные тревоги вспомогательных систем: методический шум, интенсивность
# которого задаёт уровень сложности. Технологического смысла для сценария не несут.
NUISANCE_ALARMS: dict[str, Any] = {
    "provisional": True,
    "level": "L0",
    "duration_ms": 120_000,
    "alarms": [
        {
            "code": f"nuisance_auxiliary_{index}",
            "equipment_code": "AUX-SYSTEM",
            "message": f"Второстепенная тревога вспомогательной системы №{index}",
        }
        for index in range(1, 5)
    ],
}

# Коэффициенты упрощённого двойника. Значения демонстрационные (§23 ТЗ).
PROCESS_MODEL: dict[str, Any] = {
    "provisional": True,
    "branch_controller_codes": BRANCH_CONTROLLER_CODES,
    "nominal_branch_flow_tph": NOMINAL_BRANCH_FLOW_TPH,
    "nominal_branch_pressure_bar": 5.0,
    "nominal_pump_discharge_pressure_bar": 6.0,
    "ambient_temp_c": 25.0,
    "t11_duty_c": 105.0,
    "t11_flow_sensitivity": 0.35,
    "t11_temperature_limit_c": T11_TEMPERATURE_LIMIT_C,
    "t11_temperature_margin_span_c": 15.0,
    "flow_time_constant_ms": 60_000,
    "pressure_time_constant_ms": 20_000,
    "temperature_time_constant_ms": 90_000,
    "warmup_time_constant_ms": 300_000,
    "warmup_min_flow_ratio": 0.5,
    "downstream": {
        "provisional": True,
        "section_min_load_ratio": 0.10,
        "elou_load_time_constant_ms": 60_000,
        "elou_stage2_time_constant_ms": 30_000,
        "elou_imbalance_transfer": 0.92,
        "elou_stage1_base_level_mm": 3820.0,
        "elou_stage2_base_level_mm": 3840.0,
        "elou_stage1_level_sensitivity_mm": 4600.0,
        "elou_stage2_level_sensitivity_mm": 4200.0,
        "elou_low_level_interlock_mm": ELOU_LOW_LEVEL_INTERLOCK_MM,
        "elou_temperature_offset_c": -2.0,
        "elou_level_time_constant_ms": 30_000,
        "elou_operating_level_mm": 3700.0,
        "e15_load_time_constant_ms": 30_000,
        "e15_base_level_pct": 52.0,
        "e15_level_sensitivity_pct": 80.0,
        "e15_level_time_constant_ms": 30_000,
        "k1_load_time_constant_ms": 30_000,
        "k1_base_pressure_bar": 1.60,
        "k1_pressure_sensitivity_bar": 1.80,
        "k1_base_top_temp_c": 138.0,
        "k1_top_temp_sensitivity_c": 49.0,
        "k1_base_bottom_temp_c": 268.0,
        "k1_bottom_temp_sensitivity_c": 65.0,
        "k1_base_level_pct": 50.0,
        "k1_level_sensitivity_pct": 65.0,
        "k1_time_constant_ms": 60_000,
        "k1_operating_feed_ratio": 0.95,
        "furnace_nominal_heat_load_pct": 100.0,
        "furnace_max_heat_load_pct": 130.0,
        "furnace_base_outlet_temp_c": 340.0,
        "furnace_outlet_temp_sensitivity_c": 112.0,
        "furnace_time_constant_ms": 60_000,
        "k2_load_time_constant_ms": 120_000,
        "k2_base_pressure_bar": 0.62,
        "k2_pressure_sensitivity_bar": 0.65,
        "k2_base_top_temp_c": 142.0,
        "k2_top_temp_sensitivity_c": 33.0,
        "k2_bottom_temp_offset_c": -2.0,
        "k2_bottom_temp_sensitivity_c": 20.0,
        "k2_stability_feed_sensitivity": 4.5,
        "k2_stability_heat_sensitivity": 2.0,
        "k2_operating_stability_index": 0.85,
        "k2_time_constant_ms": 90_000,
        "side_draw_stability_sensitivity": 5.3,
        "product_stability_sensitivity": 5.9,
        "product_time_constant_ms": 120_000,
        "wash_water_max_ratio": 0.20,
    },
}

# Эталонная последовательность действий оператора (§10.1 ТЗ, §40 сценария).
EXPECTED_ACTIONS: tuple[ExpectedActionSpec, ...] = (
    ExpectedActionSpec(1, "declare_deviation", "FEED-SYSTEM", 1.0),
    ExpectedActionSpec(2, "compare_flows", "FEED-SYSTEM", 1.0),
    ExpectedActionSpec(3, "inspect_pressure", "FEED-SYSTEM", 1.0),
    ExpectedActionSpec(4, "inspect_equipment", "N-1", 1.0),
    ExpectedActionSpec(5, "inspect_equipment", "disturbance_target_controller", 1.0),
    ExpectedActionSpec(
        6,
        "submit_diagnosis",
        "FEED-SYSTEM",
        2.0,
        criticality="critical",
        preconditions=("compare_flows", "inspect_equipment"),
    ),
    ExpectedActionSpec(
        7,
        "corrective_action",
        "disturbance_target_branch",
        3.0,
        criticality="critical",
        preconditions=("submit_diagnosis",),
        expected_effect={"metric": "min_branch_flow_ratio", "op": ">=", "value": 0.95},
        verification={"required_observations": ["verify_flow"], "window_ms": 120_000},
    ),
    ExpectedActionSpec(
        8,
        "verify_result",
        "FEED-SYSTEM",
        2.0,
        criticality="critical",
        preconditions=("corrective_action",),
    ),
    ExpectedActionSpec(
        9,
        "verify_downstream",
        "PRODUCTS",
        2.0,
        preconditions=("verify_result",),
        verification={"required_targets": ["T-1_T-11", "ELOU", "V-15", "K-1", "FURNACES", "K-2", "PRODUCTS"]},
    ),
)

SCENARIO_CONFIG: dict[str, Any] = {
    "provisional": True,
    "tick_interval_ms": 1_000,
    "snapshot_interval_ms": 5_000,
    "stability_confirmation_ms": STABILITY_CONFIRMATION_MS,
    "situation_code": "feed_branch_flow_loss",
    "disturbance_onset": DISTURBANCE_ONSET,
    "eligible_target_branches": DISTURBANCE_ELIGIBLE_BRANCHES,
    "process_model": PROCESS_MODEL,
    "control_actions": CONTROL_ACTIONS,
    "nuisance_alarms": NUISANCE_ALARMS,
    "stage_checks": STAGE_CHECKS,
    # Опасная компенсация: наращивание тепла при уже упавшем расходе сырья.
    "safety": {"provisional": True, "feed_ratio_threshold": 0.95},
}
