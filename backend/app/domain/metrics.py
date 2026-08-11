"""Проекция состояния двойника в значения снимка.

Ключи совпадают с кодами тегов каталога установки, поэтому снимок самоописателен, а
правила этапов и тревог ссылаются на те же имена. Скрытое состояние (интенсивность
возмущения, целевая ветвь) сюда не попадает — для него есть `internal_state_json`.
"""

from typing import Any

from app.domain.twin import BRANCH_COUNT, PlantState, TwinConfig

PUMP_STATE_RUNNING = "RUNNING"
PUMP_STATE_STOPPED = "STOPPED"
PUMP_STATE_STANDBY = "STANDBY"


def visible_values(state: PlantState, config: TwinConfig) -> dict[str, Any]:
    """Измерения, доступные оператору на мнемосхеме."""

    values: dict[str, Any] = {}
    for index, branch in enumerate(state.branches, start=1):
        values[f"branch_{index}_flow_tph"] = round(branch.flow_tph, 3)
        values[f"branch_{index}_pressure_bar"] = round(branch.pressure_bar, 3)
        values[f"branch_{index}_valve_command_pct"] = round(branch.valve_command_pct, 2)
        values[f"branch_{index}_valve_actual_pct"] = round(branch.valve_actual_pct, 2)
        values[f"branch_{index}_t11_outlet_temp_c"] = round(branch.outlet_temp_c, 2)
    values["feed_pump_discharge_pressure_bar"] = round(state.pump_discharge_pressure_bar, 3)
    values["feed_pump_state"] = PUMP_STATE_RUNNING if state.pump_running else PUMP_STATE_STOPPED
    values["standby_pump_state"] = (
        PUMP_STATE_RUNNING if state.pump_running and state.active_pump_code != "N-1" else PUMP_STATE_STANDBY
    )
    return values


def derived_values(state: PlantState, config: TwinConfig) -> dict[str, float]:
    """Показатели, которые оператор иначе считал бы в уме."""

    flows = [branch.flow_tph for branch in state.branches]
    temperatures = [branch.outlet_temp_c for branch in state.branches]
    total_flow = sum(flows)
    mean_flow = total_flow / BRANCH_COUNT
    max_temp = max(temperatures)
    margin = (config.t11_temperature_limit_c - max_temp) / config.t11_temperature_margin_span_c

    return {
        "total_feed_flow_tph": round(total_flow, 3),
        "min_branch_flow_ratio": round(min(flows) / config.nominal_branch_flow_tph, 4),
        # Размах расходов относительно среднего: 0 до появления потока.
        "flow_imbalance_ratio": round((max(flows) - min(flows)) / mean_flow, 4) if mean_flow > 1.0 else 0.0,
        "lowest_flow_branch_code": float(flows.index(min(flows)) + 1),
        "t11_combined_outlet_temp_c": round(sum(temperatures) / BRANCH_COUNT, 2),
        "t11_max_temp_c": round(max_temp, 2),
        "t11_min_temp_c": round(min(temperatures), 2),
        "t11_temperature_margin_norm": round(margin, 4),
    }


def rule_metrics(state: PlantState, config: TwinConfig) -> dict[str, float]:
    """Числовые значения для правил этапов, тревог и блокировок."""

    numeric = {
        code: float(value)
        for code, value in visible_values(state, config).items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    return numeric | derived_values(state, config)
