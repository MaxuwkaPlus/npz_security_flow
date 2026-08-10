#!/usr/bin/env python3
"""Generate a deterministic synthetic ELOU-AVT operator-training corpus.

The corpus follows the through scenario described by the team: preparation,
three crude-feed branches, T-1...T-11, ELOU, E-15, K-1, furnaces, K-2,
product stabilization, a hidden gradual feed-branch degradation, recovery,
verification, and final reporting.

Only the Python standard library is required. The process equations are an MVP
surrogate and must be calibrated with an ELOU-AVT technologist before use with
real operators.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any


DATASET_VERSION = "1.0.0-synthetic-elou-avt"
SCENARIO_ID = "elou_avt_throughput_branch_degradation"
SCENARIO_VERSION = "1.0.0"
SNAPSHOT_INTERVAL_S = 5
PREDICTION_HORIZON_S = 30
SESSION_DURATION_S = 3900
NOMINAL_BRANCH_FLOW_TPH = 100.0
NOMINAL_TOTAL_FLOW_TPH = 300.0
T11_LIMIT_C = 140.0


def field(name: str, dtype: str, unit: str, role: str, nullable: bool, normalization: str, description: str) -> dict[str, Any]:
    return {
        "field_name": name,
        "dtype": dtype,
        "unit": unit,
        "model_role": role,
        "nullable": int(nullable),
        "normalization": normalization,
        "description": description,
    }


SCHEMA: list[dict[str, Any]] = [
    field("dataset_version", "string", "-", "identifier", False, "none", "Версия схемы синтетического корпуса."),
    field("snapshot_id", "string", "-", "identifier", False, "none", "Уникальный идентификатор временного среза."),
    field("session_id", "string", "-", "group_key", False, "none", "Идентификатор прохождения; разбиение выполняется только целыми сессиями."),
    field("split", "category", "-", "split_key", False, "none", "Готовое разбиение train/validation/test по session_id."),
    field("is_synthetic", "int8", "0/1", "audit_only", False, "none", "1 для синтетических данных; не является признаком."),
    field("random_seed", "int32", "-", "audit_only", False, "none", "Seed сессии для полного воспроизведения."),
    field("sim_time_s", "int32", "s", "context_feature", False, "divide by 3900 or StandardScaler on train", "Симуляционное время от начала сквозного сценария."),
    field("snapshot_interval_s", "int16", "s", "audit_only", False, "none", "Шаг снимков состояния; 5 секунд."),
    field("scenario_id", "category", "-", "grouping_only", False, "one-hot only in multi-scenario model", "Идентификатор сквозного сценария ЭЛОУ-АВТ."),
    field("scenario_version", "string", "-", "audit_only", False, "none", "Версия сценария и правил генерации."),
    field("stage_code", "category", "-", "context_feature", False, "one-hot or native categorical", "Текущий технологический этап сценария."),
    field("scenario_progress_ratio", "float32", "0..1", "context_feature", False, "already normalized", "Доля пройденного времени сценария."),
    field("difficulty_level", "int8", "1..3", "context_feature", False, "ordinal unchanged", "Уровень сложности: скорость развития, помехи, подсказки и дедлайн."),
    field("operator_profile", "category", "-", "audit_only", False, "exclude: synthetic generator latent variable", "Синтетический профиль поведения оператора."),
    field("disturbance_cause", "category", "-", "audit_only", False, "exclude: hidden root-cause leakage", "Скрытая первопричина снижения расхода."),
    field("disturbance_target_branch", "int8", "1..3", "audit_only", False, "exclude: hidden scenario configuration", "Ветвь, в которой развивается скрытое возмущение."),
    field("disturbance_onset_s", "int32", "s", "audit_only", False, "exclude: future/scenario leakage", "Скрытый момент начала возмущения."),
    field("disturbance_active_true", "int8", "0/1", "audit_only", False, "exclude: unavailable to operator", "Истинный флаг активности возмущения."),
    field("disturbance_severity_true", "float32", "0..1", "audit_only", False, "exclude: latent state leakage", "Истинная интенсивность возмущения цифрового двойника."),
    field("sensor_delay_s", "float32", "s", "context_feature", False, "divide by configured maximum", "Задержка отображаемых измерений."),
    field("nuisance_alarm_rate_min", "float32", "alarms/min", "context_feature", False, "log1p then StandardScaler on train", "Интенсивность второстепенных тревог."),
    field("reaction_deadline_s", "float32", "s", "context_feature", False, "divide reaction times by this value", "Допустимое время до начала корректного защитного действия."),
    field("hints_enabled", "int8", "0/1", "context_feature", False, "unchanged", "Доступны ли оператору учебные подсказки."),
]

for branch in (1, 2, 3):
    SCHEMA.extend([
        field(f"branch_{branch}_flow_tph", "float32", "t/h", "raw_feature", False, "prefer branch flow ratio or StandardScaler on train", f"Отображаемый расход сырой нефти по ветви №{branch}."),
        field(f"branch_{branch}_flow_ratio", "float32", "ratio", "derived_feature", False, "divide by nominal branch flow", f"Расход ветви №{branch} относительно номинала 100 т/ч."),
        field(f"branch_{branch}_pressure_bar", "float32", "bar", "raw_feature", False, "divide by nominal pressure or StandardScaler on train", f"Давление сырья по ветви №{branch}."),
        field(f"branch_{branch}_valve_command_pct", "float32", "%", "raw_feature", False, "divide by 100", f"Командное положение регулирующего органа ветви №{branch}."),
        field(f"branch_{branch}_valve_actual_pct", "float32", "%", "raw_feature", False, "divide by 100", f"Фактическое положение регулирующего органа ветви №{branch}."),
        field(f"branch_{branch}_t11_outlet_temp_c", "float32", "degC", "raw_feature", False, "use temperature margin and StandardScaler on train", f"Температура ветви №{branch} после предварительного теплообмена Т-1…Т-11."),
    ])

SCHEMA.extend([
    field("total_feed_flow_tph", "float32", "t/h", "raw_feature", False, "divide by 300 or StandardScaler on train", "Суммарный расход трёх сырьевых потоков."),
    field("min_branch_flow_ratio", "float32", "ratio", "derived_feature", False, "already normalized", "Минимальный относительный расход среди трёх ветвей."),
    field("flow_imbalance_ratio", "float32", "ratio", "derived_feature", False, "already normalized; robust clipping only for linear models", "Размах расходов трёх ветвей, делённый на их среднее."),
    field("lowest_flow_branch_code", "category", "-", "derived_feature", False, "one-hot or native categorical", "Номер ветви с минимальным отображаемым расходом; observable derived value."),
    field("feed_pump_discharge_pressure_bar", "float32", "bar", "raw_feature", False, "divide by nominal pressure", "Давление на выкиде работающего сырьевого насоса."),
    field("t11_combined_outlet_temp_c", "float32", "degC", "raw_feature", False, "use t11_temperature_margin_norm", "Средняя температура трёх потоков после Т-1…Т-11."),
    field("t11_temperature_margin_norm", "float32", "ratio", "derived_feature", False, "already domain-normalized; keep negative values", "(140 - максимальная температура ветви) / 15; 0 на ограничении, отрицательное значение выше ограничения."),
    field("min_branch_flow_change_30s_pct", "float32", "% nominal/30s", "derived_feature", False, "StandardScaler fitted on train", "Изменение минимального расхода ветви за предыдущие 30 секунд."),
    field("t11_max_temp_change_30s_c", "float32", "degC/30s", "derived_feature", False, "StandardScaler fitted on train", "Изменение максимальной температуры после Т-1…Т-11 за 30 секунд."),
    field("elou_wash_water_ratio", "float32", "ratio", "raw_feature", False, "already a ratio", "Расход промывочной воды относительно расхода нефти."),
    field("elou_stage1_min_level_mm", "float32", "mm", "raw_feature", False, "divide by configured nominal level", "Минимальный уровень в Э-1/Э-3/Э-5."),
    field("elou_stage2_min_level_mm", "float32", "mm", "raw_feature", False, "divide by configured nominal level", "Минимальный уровень в Э-2/Э-4/Э-6."),
    field("elou_temperature_c", "float32", "degC", "raw_feature", False, "StandardScaler fitted on train", "Температура нефти на участке ЭЛОУ."),
    field("elou_load_imbalance_ratio", "float32", "ratio", "derived_feature", False, "already normalized", "Рассогласование нагрузки параллельных ветвей ЭЛОУ."),
    field("elou_hv_trip_count", "int8", "count", "derived_feature", False, "unchanged", "Количество отключённых высоковольтных секций из-за низкого уровня."),
    field("e15_level_pct", "float32", "%", "raw_feature", False, "divide by 100", "Уровень в Е-15."),
    field("n20_state", "category", "-", "raw_feature", False, "one-hot or native categorical", "Состояние насосов Н-20: OFF/RUNNING/DEGRADED."),
    field("k1_feed_flow_ratio", "float32", "ratio", "derived_feature", False, "already normalized", "Подача на К-1 относительно требуемого режима."),
    field("k1_pressure_bar", "float32", "bar", "raw_feature", False, "divide by configured nominal pressure", "Давление К-1."),
    field("k1_top_temp_c", "float32", "degC", "raw_feature", False, "StandardScaler fitted on train", "Температура верха К-1."),
    field("k1_bottom_temp_c", "float32", "degC", "raw_feature", False, "use margin to limit 280 degC", "Температура низа К-1."),
    field("k1_level_pct", "float32", "%", "raw_feature", False, "divide by 100", "Уровень в К-1."),
    field("furnace_feed_flow_ratio", "float32", "ratio", "derived_feature", False, "already normalized", "Расход сырья через печи относительно номинала."),
    field("furnace_outlet_temp_c", "float32", "degC", "raw_feature", False, "StandardScaler fitted on train", "Температура продукта на выходе печей."),
    field("furnace_heat_load_pct", "float32", "%", "raw_feature", False, "divide by 100", "Тепловая нагрузка печей."),
    field("furnace_heat_to_feed_ratio", "float32", "ratio", "derived_feature", False, "already normalized", "Отношение тепловой нагрузки к относительному расходу сырья."),
    field("k2_pressure_bar", "float32", "bar", "raw_feature", False, "divide by configured maximum", "Давление верха К-2."),
    field("k2_top_temp_c", "float32", "degC", "raw_feature", False, "use margin to limit 148 degC", "Температура верха К-2."),
    field("k2_bottom_temp_c", "float32", "degC", "raw_feature", False, "use margin to limit 350 degC", "Температура низа К-2."),
    field("k2_stability_index", "float32", "0..1", "derived_feature", False, "already normalized", "Агрегированный индекс устойчивости К-2."),
    field("side_draw_stability_index", "float32", "0..1", "derived_feature", False, "already normalized", "Устойчивость боковых отборов К-3/1…К-3/3."),
    field("product_flow_stability_index", "float32", "0..1", "derived_feature", False, "already normalized", "Устойчивость продуктовых потоков."),
    field("deviating_parameters_count", "int16", "count", "derived_feature", False, "unchanged or StandardScaler on train", "Число одновременно отклонённых технологических параметров."),
    field("critical_parameters_count", "int16", "count", "derived_feature", False, "unchanged", "Число параметров в критической области."),
    field("active_alarms_count", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Количество активных тревог."),
    field("critical_alarms_count", "int16", "count", "behavior_feature", False, "unchanged", "Количество активных критических тревог уровня 4–5."),
    field("nuisance_alarms_count", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Количество активных второстепенных тревог."),
    field("unack_alarms_count", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Количество активных неподтверждённых тревог."),
    field("alarm_level_max", "category", "L0..L5", "behavior_feature", False, "ordinal or native categorical", "Максимальный уровень активной технологической тревоги."),
    field("alarm_rate_30s", "float32", "alarms/min", "behavior_feature", False, "log1p then StandardScaler on train", "Темп появления тревог за последние 30 секунд."),
    field("time_since_primary_alarm_s", "float32", "s", "behavior_feature", True, "impute -1 plus missing flag", "Время с первой тревоги отклонения расхода."),
    field("max_alarm_age_s", "float32", "s", "behavior_feature", True, "impute -1 plus missing flag", "Максимальный возраст активной тревоги."),
    field("alarms_ack_30s", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Подтверждения тревог за последние 30 секунд."),
    field("operator_actions_30s", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Все зафиксированные действия оператора за 30 секунд."),
    field("correct_actions_30s", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Корректные действия за 30 секунд."),
    field("incorrect_actions_30s", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Ошибочные действия за 30 секунд."),
    field("dangerous_actions_30s", "int16", "count", "behavior_feature", False, "unchanged", "Опасные компенсации за 30 секунд."),
    field("repeated_actions_30s", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Повторные команды за 30 секунд."),
    field("cancelled_actions_30s", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Отменённые оператором команды за 30 секунд."),
    field("sequence_violations_30s", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Нарушения эталонной последовательности за 30 секунд."),
    field("result_checks_30s", "int16", "count", "behavior_feature", False, "unchanged", "Явные проверки результата корректирующего действия за 30 секунд."),
    field("observation_checks_30s", "int16", "count", "behavior_feature", False, "log1p then StandardScaler on train", "Диагностические просмотры и сравнения параметров за 30 секунд."),
    field("time_since_last_action_s", "float32", "s", "behavior_feature", True, "impute -1 plus missing flag", "Время с последнего действия оператора."),
    field("deviation_declared", "int8", "0/1", "behavior_feature", False, "unchanged", "Оператор явно зафиксировал отклонение."),
    field("diagnosis_code", "category", "-", "behavior_feature", False, "one-hot or native categorical", "Текущая гипотеза оператора: none/pump/valve/heat/sensor/unknown."),
    field("correct_response_started", "int8", "0/1", "behavior_feature", False, "unchanged", "Начато первое действие, устраняющее истинную первопричину."),
    field("reaction_elapsed_s", "float32", "s", "behavior_feature", True, "divide by reaction_deadline_s; impute -1 before alarm", "Время реакции от первичной тревоги до корректного действия либо текущее ожидание."),
    field("reaction_overdue_s", "float32", "s", "behavior_feature", False, "divide by reaction_deadline_s; keep raw", "Просрочка корректного действия относительно дедлайна; не константна."),
    field("sequence_progress_ratio", "float32", "0..1", "behavior_feature", False, "already normalized", "Доля выполненных шагов эталонной карты действий."),
    field("expected_step_code", "category", "-", "behavior_feature", False, "one-hot or native categorical", "Следующий ожидаемый шаг эталонной последовательности."),
    field("verification_required", "int8", "0/1", "behavior_feature", False, "unchanged", "После корректирующего действия требуется проверка последствий."),
    field("verification_completed", "int8", "0/1", "behavior_feature", False, "unchanged", "Все обязательные проверки результата завершены."),
    field("verification_missing", "int8", "0/1", "behavior_feature", False, "unchanged", "Проверка просрочена или не выполнена."),
    field("time_since_unverified_action_s", "float32", "s", "behavior_feature", True, "divide by verification window; impute -1", "Время с корректирующего действия без полной проверки."),
    field("downstream_checks_completed_count", "int8", "count", "behavior_feature", False, "unchanged", "Количество завершённых downstream-проверок: Т-11, ЭЛОУ, Е-15, К-1, печи, К-2, продукты."),
    field("label_valid", "int8", "0/1", "label_metadata", False, "filter label_valid == 1", "Будущее окно 30 секунд полностью наблюдалось."),
    field("risk_next_30s", "int8", "0/1", "target", True, "do not normalize", "1, если критическое событие наступит строго после t и не позднее t+30 секунд; пусто для неполного окна."),
    field("time_to_critical_event_s", "float32", "s", "label_metadata", True, "exclude from X", "Время до ближайшего будущего критического события."),
    field("target_event_type", "category", "-", "label_metadata", True, "exclude from X", "Тип ближайшего будущего критического события."),
])


MODEL_COLUMNS = {
    "continuous": [
        "sim_time_s", "scenario_progress_ratio", "sensor_delay_s", "nuisance_alarm_rate_min", "reaction_deadline_s",
        *[f"branch_{b}_{suffix}" for b in (1, 2, 3) for suffix in ("flow_tph", "flow_ratio", "pressure_bar", "valve_command_pct", "valve_actual_pct", "t11_outlet_temp_c")],
        "total_feed_flow_tph", "min_branch_flow_ratio", "flow_imbalance_ratio", "feed_pump_discharge_pressure_bar",
        "t11_combined_outlet_temp_c", "t11_temperature_margin_norm", "min_branch_flow_change_30s_pct", "t11_max_temp_change_30s_c",
        "elou_wash_water_ratio", "elou_stage1_min_level_mm", "elou_stage2_min_level_mm", "elou_temperature_c", "elou_load_imbalance_ratio",
        "e15_level_pct", "k1_feed_flow_ratio", "k1_pressure_bar", "k1_top_temp_c", "k1_bottom_temp_c", "k1_level_pct",
        "furnace_feed_flow_ratio", "furnace_outlet_temp_c", "furnace_heat_load_pct", "furnace_heat_to_feed_ratio",
        "k2_pressure_bar", "k2_top_temp_c", "k2_bottom_temp_c", "k2_stability_index", "side_draw_stability_index", "product_flow_stability_index",
        "alarm_rate_30s", "time_since_primary_alarm_s", "max_alarm_age_s", "time_since_last_action_s",
        "reaction_elapsed_s", "reaction_overdue_s", "sequence_progress_ratio", "time_since_unverified_action_s",
    ],
    "count": [
        "elou_hv_trip_count", "deviating_parameters_count", "critical_parameters_count", "active_alarms_count", "critical_alarms_count",
        "nuisance_alarms_count", "unack_alarms_count", "alarms_ack_30s", "operator_actions_30s", "correct_actions_30s",
        "incorrect_actions_30s", "dangerous_actions_30s", "repeated_actions_30s", "cancelled_actions_30s", "sequence_violations_30s",
        "result_checks_30s", "observation_checks_30s", "downstream_checks_completed_count",
    ],
    "binary": [
        "hints_enabled", "deviation_declared", "correct_response_started", "verification_required", "verification_completed", "verification_missing",
    ],
    "categorical": [
        "stage_code", "difficulty_level", "lowest_flow_branch_code", "n20_state", "alarm_level_max", "diagnosis_code", "expected_step_code",
    ],
    "target": "risk_next_30s",
    "group_key": "session_id",
    "filter": "label_valid == 1",
    "excluded": [
        "dataset_version", "snapshot_id", "session_id", "split", "is_synthetic", "random_seed", "snapshot_interval_s", "scenario_id",
        "scenario_version", "operator_profile", "disturbance_cause", "disturbance_target_branch", "disturbance_onset_s",
        "disturbance_active_true", "disturbance_severity_true", "label_valid", "time_to_critical_event_s", "target_event_type",
    ],
}


STAGES = [
    (0, "precheck"), (120, "feed_preparation"), (240, "feed_startup"), (420, "t1_t3"), (600, "t4_t7"),
    (780, "t7_t11"), (960, "elou_feed_and_water"), (1140, "elou_stage_1"), (1320, "elou_stage_2"),
    (1500, "e15"), (1680, "post_elou_heating"), (1920, "k1"), (2160, "furnaces"), (2400, "k2"),
    (2700, "side_draws_and_products"), (3000, "stable_mode"), (3120, "disturbance_monitoring"),
    (3300, "diagnosis_and_correction"), (3480, "recovery"), (3720, "final_stabilization"),
]


PROFILE_CONFIG = {
    "expert": {"detect": 20, "sd": 6, "diagnosis": 0.98, "verify": 0.98, "danger": 0.01, "step": 5},
    "slow": {"detect": 80, "sd": 15, "diagnosis": 0.90, "verify": 0.82, "danger": 0.05, "step": 10},
    "alarm_overload": {"detect": 70, "sd": 18, "diagnosis": 0.72, "verify": 0.55, "danger": 0.16, "step": 10},
    "wrong_diagnosis": {"detect": 45, "sd": 10, "diagnosis": 0.15, "verify": 0.35, "danger": 0.78, "step": 8},
    "no_verification": {"detect": 35, "sd": 8, "diagnosis": 0.92, "verify": 0.03, "danger": 0.06, "step": 6},
    "chaotic": {"detect": 60, "sd": 22, "diagnosis": 0.52, "verify": 0.30, "danger": 0.42, "step": 7},
}


LEVEL_CONFIG = {
    1: {"sensor_delay": 0.0, "nuisance_rate": 0.4, "deadline": 120.0, "hints": 1, "ramp_duration": 360, "recovery": 180},
    2: {"sensor_delay": 2.5, "nuisance_rate": 2.0, "deadline": 90.0, "hints": 1, "ramp_duration": 285, "recovery": 225},
    3: {"sensor_delay": 6.0, "nuisance_rate": 4.5, "deadline": 60.0, "hints": 0, "ramp_duration": 225, "recovery": 285},
}


EXPECTED_STEPS = [
    "declare_deviation", "compare_flows", "check_pressure", "check_pump", "check_valve", "submit_diagnosis", "corrective_action", "verify_flow", "verify_downstream",
]


def stable_split(session_id: str) -> str:
    bucket = int(hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def ceil5(value: float) -> int:
    return int(math.ceil(value / SNAPSHOT_INTERVAL_S) * SNAPSHOT_INTERVAL_S)


def round_value(value: Any, digits: int = 4) -> Any:
    return round(value, digits) if isinstance(value, float) else value


def stage_for_time(t: int, disturbance_at: int, correct_action_at: int | None, severity: float) -> str:
    if t >= disturbance_at:
        if correct_action_at is not None and t >= correct_action_at:
            return "final_stabilization" if severity < 0.05 else "recovery"
        return "diagnosis_and_correction" if t >= disturbance_at + 180 else "disturbance_monitoring"
    current = STAGES[0][1]
    for start, code in STAGES:
        if start > t or start >= 3120:
            break
        current = code
    return current


def add_action(actions: list[dict[str, Any]], session_id: str, time_s: int, kind: str, target: str, classification: str, expected_step: str | None = None, result_check: bool = False, observation: bool = False) -> None:
    actions.append({
        "action_id": f"{session_id}-A{len(actions)+1:03d}", "session_id": session_id, "sim_time_s": int(time_s), "action_type": kind,
        "target_code": target, "classification": classification, "expected_step_code": expected_step or "none",
        "is_correct": int(classification == "correct"), "is_incorrect": int(classification in {"incorrect", "out_of_sequence"}),
        "is_dangerous": int(classification == "dangerous"), "is_repeated": int(classification == "repeated"),
        "is_cancelled": int(classification == "cancelled"), "is_sequence_violation": int(classification == "out_of_sequence"),
        "is_result_check": int(result_check), "is_observation": int(observation),
    })


def build_actions(rng: random.Random, session_id: str, profile: str, difficulty: int, cause: str, primary_alarm_at: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = PROFILE_CONFIG[profile]
    level = LEVEL_CONFIG[difficulty]
    detection_delay = max(5.0, rng.gauss(cfg["detect"] * (1 + 0.12 * (difficulty - 1)), cfg["sd"]))
    detection_at = ceil5(primary_alarm_at + detection_delay)
    diagnosis_correct = rng.random() < clamp(cfg["diagnosis"] - 0.05 * (difficulty - 1), 0.02, 0.99)
    verify = rng.random() < clamp(cfg["verify"] - 0.04 * (difficulty - 1), 0.0, 0.99)
    dangerous = rng.random() < clamp(cfg["danger"] + 0.05 * (difficulty - 1), 0.0, 0.95)
    step_gap = cfg["step"]
    actions: list[dict[str, Any]] = []

    add_action(actions, session_id, detection_at, "declare_deviation", "feed_system", "correct", "declare_deviation")
    add_action(actions, session_id, detection_at + 5, "ack_alarm", "primary_flow_alarm", "correct")
    checks = [
        ("compare_flows", "FRC-404/405/406", "compare_flows"),
        ("check_pressure", "feed_branches", "check_pressure"),
        ("check_pump", "N-1_group", "check_pump"),
        ("check_valve", "target_branch_FRC", "check_valve"),
    ]
    if profile in {"alarm_overload", "chaotic"}:
        checks = [checks[2], checks[0], checks[3], checks[1]]
    for index, (kind, target, expected) in enumerate(checks, start=1):
        expected_index = EXPECTED_STEPS.index(expected)
        previous_expected = [EXPECTED_STEPS.index(item[2]) for item in checks[:index-1]]
        violation = bool(previous_expected and expected_index < max(previous_expected))
        add_action(actions, session_id, detection_at + step_gap * index, kind, target, "out_of_sequence" if violation else "correct", expected, observation=True)

    diagnosis_at = detection_at + step_gap * 5
    true_code = "pump_capacity_loss" if cause == "feed_pump_capacity_loss" else "valve_stiction"
    submitted_code = true_code if diagnosis_correct else rng.choice(["heat_transfer_problem", "sensor_fault", "unknown"])
    add_action(actions, session_id, diagnosis_at, f"submit_diagnosis:{submitted_code}", "feed_branch", "correct" if diagnosis_correct else "incorrect", "submit_diagnosis")

    correct_action_at: int | None = None
    if diagnosis_correct:
        correct_action_at = diagnosis_at + step_gap + 5
        action_kind = "switch_to_standby_pump" if cause == "feed_pump_capacity_loss" else "restore_flow_control"
        add_action(actions, session_id, correct_action_at, action_kind, "feed_branch", "correct", "corrective_action")
    elif profile in {"slow", "chaotic"} and rng.random() < 0.35:
        correct_action_at = diagnosis_at + 180
        add_action(actions, session_id, correct_action_at - 10, f"submit_diagnosis:{true_code}", "feed_branch", "correct", "submit_diagnosis")
        action_kind = "switch_to_standby_pump" if cause == "feed_pump_capacity_loss" else "restore_flow_control"
        add_action(actions, session_id, correct_action_at, action_kind, "feed_branch", "correct", "corrective_action")

    dangerous_action_at: int | None = None
    if dangerous or not diagnosis_correct:
        dangerous_action_at = diagnosis_at + 35
        add_action(actions, session_id, dangerous_action_at, "increase_furnace_heat", "furnaces", "dangerous")

    if profile in {"alarm_overload", "chaotic"}:
        repeat_at = diagnosis_at + 20
        add_action(actions, session_id, repeat_at, "repeat_previous_command", "feed_branch", "repeated")
    if profile in {"chaotic", "wrong_diagnosis"}:
        cancel_at = diagnosis_at + 25
        add_action(actions, session_id, cancel_at, "switch_pump_request", "N-1_group", "cancelled")

    verification_end: int | None = None
    if correct_action_at is not None and verify:
        verify_steps = [
            ("verify_flow", "feed_branch", "verify_flow"), ("verify_t11", "T-1...T-11", "verify_downstream"),
            ("verify_elou", "ELOU", "verify_downstream"), ("verify_e15", "E-15", "verify_downstream"),
            ("verify_k1", "K-1", "verify_downstream"), ("verify_furnaces", "P-1/P-2/P-3", "verify_downstream"),
            ("verify_k2", "K-2", "verify_downstream"), ("verify_products", "product_lines", "verify_downstream"),
        ]
        start = correct_action_at + 60
        for index, (kind, target, expected) in enumerate(verify_steps):
            add_action(actions, session_id, start + 10 * index, kind, target, "correct", expected, result_check=True, observation=True)
        verification_end = start + 10 * (len(verify_steps) - 1)

    actions.sort(key=lambda item: (item["sim_time_s"], item["action_id"]))
    return actions, {
        "detection_at_s": detection_at, "diagnosis_at_s": diagnosis_at, "diagnosis_correct": diagnosis_correct,
        "submitted_diagnosis": submitted_code, "correct_action_at_s": correct_action_at,
        "dangerous_action_at_s": dangerous_action_at, "verification_end_s": verification_end,
    }


def count_actions(actions: list[dict[str, Any]], now: int, key: str | None = None) -> int:
    window = [a for a in actions if now - 30 < a["sim_time_s"] <= now]
    return len(window) if key is None else sum(int(a[key]) for a in window)


def generate_session(session_no: int, difficulty: int, profile: str, seed: int) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)
    level = LEVEL_CONFIG[difficulty]
    session_id = f"EAVT-L{difficulty}-{profile.upper().replace('_', '-')}-{session_no:03d}"
    split = stable_split(session_id)
    cause = "feed_pump_capacity_loss" if (session_no + difficulty) % 2 else "flow_control_valve_stiction"
    target_branch = 1 + (session_no + difficulty) % 3
    disturbance_at = rng.randrange(3060, 3221, 5)
    primary_alarm_at = ceil5(disturbance_at + 0.22 * level["ramp_duration"] + level["sensor_delay"])
    actions, action_meta = build_actions(rng, session_id, profile, difficulty, cause, primary_alarm_at)
    correct_action_at = action_meta["correct_action_at_s"]

    baseline_result = clamp(rng.gauss(72, 14), 30, 98)
    nuisance_windows: list[dict[str, Any]] = []
    nuisance_t = 0.0
    rate_per_s = level["nuisance_rate"] / 60.0
    while rate_per_s > 0:
        nuisance_t += rng.expovariate(rate_per_s)
        if nuisance_t > SESSION_DURATION_S:
            break
        start = ceil5(nuisance_t)
        end = min(SESSION_DURATION_S, start + rng.choice([15, 20, 25, 30]))
        ack = start + (10 if profile == "expert" else 20) if profile not in {"alarm_overload", "chaotic"} else None
        nuisance_windows.append({"start": start, "end": end, "ack": ack})

    def raw_severity(t: int) -> float:
        return clamp((t - disturbance_at) / level["ramp_duration"], 0.0, 1.0)

    def severity_at(t: int) -> float:
        raw = raw_severity(t)
        if correct_action_at is None or t < correct_action_at:
            return raw
        at_action = raw_severity(correct_action_at)
        return clamp(at_action * (1 - (t - correct_action_at) / level["recovery"]), 0.0, 1.0)

    diagnosis_events = [a for a in actions if a["action_type"].startswith("submit_diagnosis:")]
    alarm_records: list[dict[str, Any]] = []
    active_alarm_map: dict[str, dict[str, Any]] = {}
    scenario_alarm_starts: list[int] = []
    alarm_ack_times: list[int] = []
    rows: list[dict[str, Any]] = []
    critical_events: list[dict[str, Any]] = []
    event_seen: set[str] = set()
    history_min_flow: list[float] = []
    history_max_temp: list[float] = []

    for nuisance_index, item in enumerate(nuisance_windows, start=1):
        alarm_records.append({
            "alarm_id": f"{session_id}-N{nuisance_index:03d}", "session_id": session_id, "alarm_code": "nuisance_misc",
            "alarm_level": "L0", "equipment_code": "auxiliary_system", "started_at_s": item["start"],
            "acknowledged_at_s": item["ack"], "cleared_at_s": item["end"], "is_nuisance": 1,
        })
        if item["ack"] is not None:
            alarm_ack_times.append(item["ack"])

    for t in range(0, SESSION_DURATION_S + 1, SNAPSHOT_INTERVAL_S):
        severity = severity_at(t)
        delayed_severity = severity_at(max(0, t - int(level["sensor_delay"])))
        elou_severity = severity_at(max(0, t - 60))
        k1_severity = severity_at(max(0, t - 120))
        k2_severity = severity_at(max(0, t - 240))
        feed_ramp = clamp((t - 240) / 180, 0.0, 1.0)
        base_flow = NOMINAL_BRANCH_FLOW_TPH * feed_ramp
        base_t11_temp = 25.0 + 110.0 * clamp((t - 420) / 360, 0.0, 1.0)
        dangerous_heat_active = action_meta["dangerous_action_at_s"] is not None and t >= action_meta["dangerous_action_at_s"]
        heat_boost = 18.0 if dangerous_heat_active else 0.0

        flows: list[float] = []
        pressures: list[float] = []
        valve_commands: list[float] = []
        valve_actuals: list[float] = []
        t11_temps: list[float] = []
        for branch in (1, 2, 3):
            is_target = branch == target_branch
            loss = 0.38 * delayed_severity if is_target else -0.015 * delayed_severity
            flow = max(0.0, base_flow * (1 - loss) + rng.gauss(0, 0.35 if feed_ramp > 0 else 0.03))
            if cause == "feed_pump_capacity_loss":
                pressure = 5.0 - (1.15 * delayed_severity if is_target else 0.08 * delayed_severity)
                valve_actual = 100.0
            else:
                pressure = 5.0 - (0.75 * delayed_severity if is_target else 0.03 * delayed_severity)
                valve_actual = 100.0 - (42.0 * delayed_severity if is_target else 0.0)
            valve_command = 100.0
            temp = base_t11_temp + (20.0 * delayed_severity if is_target else 1.5 * delayed_severity) + heat_boost * 0.20
            flows.append(flow)
            pressures.append(pressure + rng.gauss(0, 0.015))
            valve_commands.append(valve_command)
            valve_actuals.append(clamp(valve_actual, 0, 100))
            t11_temps.append(temp + rng.gauss(0, 0.12))

        total_flow = sum(flows)
        mean_flow = total_flow / 3 if total_flow > 1 else 1.0
        flow_ratios = [value / NOMINAL_BRANCH_FLOW_TPH for value in flows]
        flow_imbalance = (max(flows) - min(flows)) / mean_flow if feed_ramp > 0.2 else 0.0
        lowest_branch = 1 + flows.index(min(flows))
        pump_pressure = 6.0 - (1.0 * delayed_severity if cause == "feed_pump_capacity_loss" else -0.25 * delayed_severity)
        max_t11_temp = max(t11_temps)
        t11_combined = sum(t11_temps) / 3

        elou_online = t >= 960
        elou_imbalance = flow_imbalance * 0.92 if elou_online else 0.0
        stage1_level = (3820.0 - 560.0 * elou_severity + rng.gauss(0, 6)) if elou_online else 0.0
        stage2_level = (3840.0 - 510.0 * elou_severity + rng.gauss(0, 6)) if t >= 1320 else 0.0
        hv_trip_count = int(stage1_level > 0 and stage1_level < 3500) + int(stage2_level > 0 and stage2_level < 3500)
        wash_water_ratio = 0.075 if elou_online else 0.0
        elou_temp = t11_combined - 2.0 if elou_online else 0.0
        e15_level = (52.0 - 10.0 * elou_severity + rng.gauss(0, 0.25)) if t >= 1500 else 0.0
        n20_state = "DEGRADED" if t >= 1500 and k1_severity > 0.55 else "RUNNING" if t >= 1500 else "OFF"
        k1_feed_ratio = (total_flow / NOMINAL_TOTAL_FLOW_TPH) if t >= 1920 else 0.0
        k1_pressure = (1.6 - 0.22 * k1_severity) if t >= 1920 else 0.0
        k1_top_temp = (138.0 - 6.0 * k1_severity) if t >= 1920 else 0.0
        k1_bottom_temp = (268.0 + 8.0 * k1_severity + heat_boost * 0.12) if t >= 1920 else 0.0
        k1_level = (50.0 - 8.0 * k1_severity) if t >= 1920 else 0.0
        furnace_feed_ratio = k1_feed_ratio if t >= 2160 else 0.0
        furnace_heat_load = (100.0 + heat_boost) if t >= 2160 else 0.0
        heat_to_feed = furnace_heat_load / 100.0 / max(furnace_feed_ratio, 0.05) if t >= 2160 else 0.0
        furnace_outlet_temp = (340.0 + 28.0 * max(0.0, heat_to_feed - 1.0)) if t >= 2160 else 0.0
        k2_pressure = (0.62 + 0.08 * k2_severity) if t >= 2400 else 0.0
        k2_top_temp = (142.0 + 4.0 * k2_severity) if t >= 2400 else 0.0
        k2_bottom_temp = (338.0 + 9.0 * k2_severity + heat_boost * 0.10) if t >= 2400 else 0.0
        k2_stability = clamp(1.0 - 0.55 * k2_severity - 0.25 * max(0.0, heat_to_feed - 1.0), 0.0, 1.0) if t >= 2400 else 0.0
        side_draw_stability = clamp(1.0 - 0.65 * k2_severity, 0.0, 1.0) if t >= 2700 else 0.0
        product_stability = clamp(1.0 - 0.72 * k2_severity, 0.0, 1.0) if t >= 2700 else 0.0

        alarm_conditions = {
            "flow_deviation_branch": (min(flow_ratios) < 0.92 and t >= disturbance_at, "L1", f"feed_branch_{target_branch}"),
            "feed_flow_imbalance": (flow_imbalance > 0.12 and t >= disturbance_at, "L2", "feed_system"),
            "t11_temperature_deviation": (max_t11_temp > 140.0 and t >= disturbance_at, "L3", "T-1...T-11"),
            "elou_load_imbalance": (elou_imbalance > 0.18 and t >= disturbance_at, "L4", "ELOU"),
            "k1_feed_deviation": (k1_feed_ratio > 0 and k1_feed_ratio < 0.91 and t >= disturbance_at, "L5", "K-1"),
        }
        for code, (condition, alarm_level, equipment) in alarm_conditions.items():
            if condition and code not in active_alarm_map:
                ack_delay = 5 if profile == "expert" else 15 if profile not in {"alarm_overload", "chaotic"} else 45
                record = {
                    "alarm_id": f"{session_id}-S{len([a for a in alarm_records if not a['is_nuisance']])+1:02d}", "session_id": session_id,
                    "alarm_code": code, "alarm_level": alarm_level, "equipment_code": equipment, "started_at_s": t,
                    "acknowledged_at_s": max(t + ack_delay, action_meta["detection_at_s"] + 5), "cleared_at_s": None, "is_nuisance": 0,
                }
                active_alarm_map[code] = record
                alarm_records.append(record)
                scenario_alarm_starts.append(t)
                alarm_ack_times.append(record["acknowledged_at_s"])
            if not condition and code in active_alarm_map:
                active_alarm_map.pop(code)["cleared_at_s"] = t

        nuisance_active = [a for a in nuisance_windows if a["start"] <= t < a["end"]]
        active_scenario = list(active_alarm_map.values())
        active_alarm_count = len(active_scenario) + len(nuisance_active)
        unack_count = sum(int(a["acknowledged_at_s"] is None or t < a["acknowledged_at_s"]) for a in active_scenario)
        unack_count += sum(int(a["ack"] is None or t < a["ack"]) for a in nuisance_active)
        level_numbers = [int(a["alarm_level"][1:]) for a in active_scenario]
        max_alarm_level = max(level_numbers, default=0)
        max_alarm_age = max([t - a["started_at_s"] for a in active_scenario] + [t - a["start"] for a in nuisance_active], default=None)
        alarm_rate = 2.0 * sum(t - 30 < start <= t for start in scenario_alarm_starts + [a["start"] for a in nuisance_windows])

        actions_so_far = [a for a in actions if a["sim_time_s"] <= t]
        last_action_time = max((a["sim_time_s"] for a in actions_so_far), default=None)
        diagnosis_value = "none"
        for event in diagnosis_events:
            if event["sim_time_s"] <= t:
                diagnosis_value = event["action_type"].split(":", 1)[1]
        completed_steps = {a["expected_step_code"] for a in actions_so_far if a["is_correct"] and a["expected_step_code"] in EXPECTED_STEPS}
        progress = len(completed_steps) / len(EXPECTED_STEPS)
        next_step = next((step for step in EXPECTED_STEPS if step not in completed_steps), "complete")
        correct_started = int(correct_action_at is not None and t >= correct_action_at)
        reaction_elapsed = None if t < primary_alarm_at else max(0, min(t, correct_action_at if correct_action_at is not None else t) - primary_alarm_at)
        reaction_overdue = max(0.0, (reaction_elapsed or 0.0) - level["deadline"])
        verification_end = action_meta["verification_end_s"]
        verification_required = int(correct_action_at is not None and t >= correct_action_at and (verification_end is None or t < verification_end))
        verification_completed = int(verification_end is not None and t >= verification_end)
        verification_missing = int(verification_required and t - correct_action_at > 90) if correct_action_at is not None else 0
        time_unverified = float(t - correct_action_at) if verification_required and correct_action_at is not None else None
        downstream_checks = sum(1 for a in actions_so_far if a["is_result_check"] and a["action_type"] != "verify_flow")

        history_min_flow.append(min(flow_ratios))
        history_max_temp.append(max_t11_temp)
        prior_index = max(0, len(history_min_flow) - 7)
        min_flow_change = 100.0 * (history_min_flow[-1] - history_min_flow[prior_index])
        temp_change = history_max_temp[-1] - history_max_temp[prior_index]

        deviating_flags = [
            flow_imbalance > 0.10, max_t11_temp > 140.0, elou_imbalance > 0.15,
            k1_feed_ratio > 0 and k1_feed_ratio < 0.92, heat_to_feed > 1.15, k2_stability > 0 and k2_stability < 0.85,
        ]
        critical_flags = [
            flow_imbalance > 0.20, max_t11_temp > 144.0, elou_imbalance > 0.28,
            hv_trip_count > 0, k1_feed_ratio > 0 and k1_feed_ratio < 0.89, heat_to_feed > 1.25,
            k2_stability > 0 and k2_stability < 0.55,
        ]

        critical_conditions = {
            "severe_flow_imbalance": flow_imbalance > 0.20,
            "t11_branch_overtemperature": max_t11_temp > 144.0,
            "elou_critical_load_imbalance": elou_imbalance > 0.28,
            "elou_low_level_interlock": hv_trip_count > 0,
            "k1_critical_feed_deviation": k1_feed_ratio > 0 and k1_feed_ratio < 0.89,
            "unsafe_furnace_heat_to_feed": heat_to_feed > 1.25,
            "k2_critical_instability": k2_stability > 0 and k2_stability < 0.55,
            "missed_critical_reaction_deadline": t >= primary_alarm_at + level["deadline"] and not correct_started,
        }
        for event_type, condition in critical_conditions.items():
            if condition and event_type not in event_seen:
                event_seen.add(event_type)
                critical_events.append({
                    "event_id": f"{session_id}-C{len(critical_events)+1:02d}", "session_id": session_id,
                    "sim_time_s": t, "event_type": event_type, "source": "process_or_rule", "severity": "critical",
                })
        if action_meta["dangerous_action_at_s"] == t and "dangerous_heat_compensation" not in event_seen:
            event_seen.add("dangerous_heat_compensation")
            critical_events.append({
                "event_id": f"{session_id}-C{len(critical_events)+1:02d}", "session_id": session_id,
                "sim_time_s": t, "event_type": "dangerous_heat_compensation", "source": "operator_action", "severity": "critical",
            })

        row: dict[str, Any] = {
            "dataset_version": DATASET_VERSION, "snapshot_id": f"{session_id}-T{t:04d}", "session_id": session_id, "split": split,
            "is_synthetic": 1, "random_seed": seed, "sim_time_s": t, "snapshot_interval_s": SNAPSHOT_INTERVAL_S,
            "scenario_id": SCENARIO_ID, "scenario_version": SCENARIO_VERSION,
            "stage_code": stage_for_time(t, disturbance_at, correct_action_at, severity), "scenario_progress_ratio": t / SESSION_DURATION_S,
            "difficulty_level": difficulty, "operator_profile": profile, "disturbance_cause": cause,
            "disturbance_target_branch": target_branch, "disturbance_onset_s": disturbance_at,
            "disturbance_active_true": int(severity > 0), "disturbance_severity_true": severity,
            "sensor_delay_s": level["sensor_delay"], "nuisance_alarm_rate_min": level["nuisance_rate"],
            "reaction_deadline_s": level["deadline"], "hints_enabled": level["hints"],
            "total_feed_flow_tph": total_flow, "min_branch_flow_ratio": min(flow_ratios), "flow_imbalance_ratio": flow_imbalance,
            "lowest_flow_branch_code": f"branch_{lowest_branch}", "feed_pump_discharge_pressure_bar": pump_pressure,
            "t11_combined_outlet_temp_c": t11_combined, "t11_temperature_margin_norm": (T11_LIMIT_C - max_t11_temp) / 15.0,
            "min_branch_flow_change_30s_pct": min_flow_change, "t11_max_temp_change_30s_c": temp_change,
            "elou_wash_water_ratio": wash_water_ratio, "elou_stage1_min_level_mm": stage1_level,
            "elou_stage2_min_level_mm": stage2_level, "elou_temperature_c": elou_temp,
            "elou_load_imbalance_ratio": elou_imbalance, "elou_hv_trip_count": hv_trip_count,
            "e15_level_pct": e15_level, "n20_state": n20_state, "k1_feed_flow_ratio": k1_feed_ratio,
            "k1_pressure_bar": k1_pressure, "k1_top_temp_c": k1_top_temp, "k1_bottom_temp_c": k1_bottom_temp, "k1_level_pct": k1_level,
            "furnace_feed_flow_ratio": furnace_feed_ratio, "furnace_outlet_temp_c": furnace_outlet_temp,
            "furnace_heat_load_pct": furnace_heat_load, "furnace_heat_to_feed_ratio": heat_to_feed,
            "k2_pressure_bar": k2_pressure, "k2_top_temp_c": k2_top_temp, "k2_bottom_temp_c": k2_bottom_temp,
            "k2_stability_index": k2_stability, "side_draw_stability_index": side_draw_stability,
            "product_flow_stability_index": product_stability, "deviating_parameters_count": sum(deviating_flags),
            "critical_parameters_count": sum(critical_flags), "active_alarms_count": active_alarm_count,
            "critical_alarms_count": sum(int(int(a["alarm_level"][1:]) >= 4) for a in active_scenario),
            "nuisance_alarms_count": len(nuisance_active), "unack_alarms_count": unack_count,
            "alarm_level_max": f"L{max_alarm_level}", "alarm_rate_30s": alarm_rate,
            "time_since_primary_alarm_s": float(t - primary_alarm_at) if t >= primary_alarm_at else None,
            "max_alarm_age_s": float(max_alarm_age) if max_alarm_age is not None else None,
            "alarms_ack_30s": sum(t - 30 < ack <= t for ack in alarm_ack_times),
            "operator_actions_30s": count_actions(actions, t), "correct_actions_30s": count_actions(actions, t, "is_correct"),
            "incorrect_actions_30s": count_actions(actions, t, "is_incorrect"), "dangerous_actions_30s": count_actions(actions, t, "is_dangerous"),
            "repeated_actions_30s": count_actions(actions, t, "is_repeated"), "cancelled_actions_30s": count_actions(actions, t, "is_cancelled"),
            "sequence_violations_30s": count_actions(actions, t, "is_sequence_violation"), "result_checks_30s": count_actions(actions, t, "is_result_check"),
            "observation_checks_30s": count_actions(actions, t, "is_observation"),
            "time_since_last_action_s": float(t - last_action_time) if last_action_time is not None else None,
            "deviation_declared": int(t >= action_meta["detection_at_s"]), "diagnosis_code": diagnosis_value,
            "correct_response_started": correct_started, "reaction_elapsed_s": reaction_elapsed, "reaction_overdue_s": reaction_overdue,
            "sequence_progress_ratio": progress, "expected_step_code": next_step,
            "verification_required": verification_required, "verification_completed": verification_completed,
            "verification_missing": verification_missing, "time_since_unverified_action_s": time_unverified,
            "downstream_checks_completed_count": downstream_checks,
        }
        for index, branch in enumerate((1, 2, 3)):
            row.update({
                f"branch_{branch}_flow_tph": flows[index], f"branch_{branch}_flow_ratio": flow_ratios[index],
                f"branch_{branch}_pressure_bar": pressures[index], f"branch_{branch}_valve_command_pct": valve_commands[index],
                f"branch_{branch}_valve_actual_pct": valve_actuals[index], f"branch_{branch}_t11_outlet_temp_c": t11_temps[index],
            })
        rows.append(row)

    for record in active_alarm_map.values():
        record["cleared_at_s"] = SESSION_DURATION_S

    critical_events.sort(key=lambda event: (event["sim_time_s"], event["event_type"]))
    for row in rows:
        t = row["sim_time_s"]
        row["label_valid"] = int(t + PREDICTION_HORIZON_S <= SESSION_DURATION_S)
        future = [event for event in critical_events if t < event["sim_time_s"] <= t + PREDICTION_HORIZON_S]
        if row["label_valid"]:
            row["risk_next_30s"] = int(bool(future))
            if future:
                nearest = min(future, key=lambda event: event["sim_time_s"])
                row["time_to_critical_event_s"] = nearest["sim_time_s"] - t
                row["target_event_type"] = nearest["event_type"]
            else:
                row["time_to_critical_event_s"] = None
                row["target_event_type"] = None
        else:
            row["risk_next_30s"] = None
            row["time_to_critical_event_s"] = None
            row["target_event_type"] = None
        row.update({key: round_value(value) for key, value in row.items()})

    final_severity = severity_at(SESSION_DURATION_S)
    verification_complete = action_meta["verification_end_s"] is not None
    outcome = "stabilized_verified" if final_severity < 0.05 and verification_complete else "stabilized_unverified" if final_severity < 0.05 else "not_stabilized"
    session_summary = {
        "dataset_version": DATASET_VERSION, "session_id": session_id, "split": split, "random_seed": seed,
        "difficulty_level": difficulty, "operator_profile": profile, "disturbance_cause": cause,
        "disturbance_target_branch": target_branch, "disturbance_onset_s": disturbance_at,
        "primary_alarm_at_s": primary_alarm_at, "detection_at_s": action_meta["detection_at_s"],
        "diagnosis_at_s": action_meta["diagnosis_at_s"], "diagnosis_correct": int(action_meta["diagnosis_correct"]),
        "correct_action_at_s": correct_action_at, "verification_end_s": action_meta["verification_end_s"],
        "session_outcome": outcome, "critical_event_count": len(critical_events), "snapshot_count": len(rows),
        "valid_snapshot_count": sum(r["label_valid"] for r in rows),
        "positive_snapshot_count": sum(int(r["risk_next_30s"] or 0) for r in rows),
        "baseline_resultiveness_0_100": round(baseline_result, 2),
    }
    return rows, session_summary, actions, alarm_records, critical_events


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: "" if row.get(column) is None else row.get(column) for column in columns})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--repetitions", type=int, default=2, help="Sessions per difficulty/profile combination.")
    args = parser.parse_args()
    output = args.output_dir
    sample = output / "sample"
    output.mkdir(parents=True, exist_ok=True)
    sample.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    alarms: list[dict[str, Any]] = []
    critical_events: list[dict[str, Any]] = []
    session_counter = 0
    for difficulty in (1, 2, 3):
        for profile in PROFILE_CONFIG:
            for repetition in range(args.repetitions):
                session_counter += 1
                seed = 20260810 + session_counter * 7919 + difficulty * 101 + repetition
                rows, session, action_rows, alarm_rows, event_rows = generate_session(session_counter, difficulty, profile, seed)
                all_rows.extend(rows)
                sessions.append(session)
                actions.extend(action_rows)
                alarms.extend(alarm_rows)
                critical_events.extend(event_rows)

    fieldnames = [item["field_name"] for item in SCHEMA]
    write_csv(sample / "snapshots.csv", all_rows, fieldnames)
    write_csv(sample / "sessions.csv", sessions, list(sessions[0].keys()))
    write_csv(sample / "actions.csv", actions, list(actions[0].keys()))
    write_csv(sample / "alarms.csv", alarms, list(alarms[0].keys()))
    write_csv(sample / "critical_events.csv", critical_events, list(critical_events[0].keys()))
    write_csv(output / "schema.csv", SCHEMA, ["field_name", "dtype", "unit", "model_role", "nullable", "normalization", "description"])
    (output / "model_columns.json").write_text(json.dumps(MODEL_COLUMNS, ensure_ascii=False, indent=2), encoding="utf-8")

    valid = [row for row in all_rows if row["label_valid"]]
    positives = [row for row in valid if row["risk_next_30s"] == 1]
    split_counts = Counter(row["split"] for row in valid)
    split_positive = Counter(row["split"] for row in positives)
    event_counts = Counter(event["event_type"] for event in critical_events)
    manifest = {
        "dataset_version": DATASET_VERSION, "scenario_id": SCENARIO_ID, "scenario_version": SCENARIO_VERSION,
        "snapshot_interval_s": SNAPSHOT_INTERVAL_S, "prediction_horizon_s": PREDICTION_HORIZON_S,
        "session_duration_s": SESSION_DURATION_S, "session_count": len(sessions), "snapshot_count": len(all_rows),
        "valid_snapshot_count": len(valid), "positive_snapshot_count": len(positives),
        "positive_rate": round(len(positives) / len(valid), 6), "rows_by_split": dict(split_counts),
        "positive_rows_by_split": dict(split_positive), "critical_events_by_type": dict(event_counts),
        "profiles": list(PROFILE_CONFIG), "difficulty_levels": [1, 2, 3],
        "disturbance_causes": ["feed_pump_capacity_loss", "flow_control_valve_stiction"],
        "source_scenario_document": "СЦЕНАРИЙ ТРЕНАЖЁРА (1).md",
        "warning": "Synthetic MVP surrogate. Calibrate equations, thresholds and corrective actions with an ELOU-AVT technologist.",
    }
    (sample / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    rng = random.Random(20260810)
    positive_preview = positives[:1200]
    negative_pool = [row for row in valid if row["risk_next_30s"] == 0]
    negative_preview = rng.sample(negative_pool, min(1800, len(negative_pool)))
    preview = sorted(positive_preview + negative_preview, key=lambda row: (row["session_id"], row["sim_time_s"]))
    write_csv(sample / "snapshots_preview.csv", preview, fieldnames)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
