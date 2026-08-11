from app.domain.metrics import derived_values, rule_metrics, visible_values
from app.domain.twin import (
    RESTORE_FLOW_CONTROL,
    START_FEED_PUMP,
    SWITCH_TO_STANDBY_PUMP,
    Command,
    Disturbance,
    PlantState,
    TwinConfig,
    initial_state,
    step,
)

CONFIG = TwinConfig()
TICK_MS = 1_000

PUMP_FAILURE = Disturbance(
    target_branch=2,
    onset_sim_time_ms=900_000,
    correct_action_type=SWITCH_TO_STANDBY_PUMP,
    ramp_duration_ms=360_000,
    recovery_duration_ms=180_000,
    target_branch_flow_loss=0.38,
    other_branch_flow_gain=0.015,
    target_branch_pressure_drop_bar=1.15,
    pump_discharge_pressure_drop_bar=1.0,
)
VALVE_STICTION = Disturbance(
    target_branch=2,
    onset_sim_time_ms=900_000,
    correct_action_type=RESTORE_FLOW_CONTROL,
    ramp_duration_ms=360_000,
    recovery_duration_ms=180_000,
    target_branch_pressure_drop_bar=0.75,
    pump_discharge_pressure_drop_bar=-0.25,
    valve_actual_offset_pct=42.0,
)


def run(
    state: PlantState,
    disturbance: Disturbance,
    *,
    from_ms: int,
    seconds: int,
    commands: dict[int, list[Command]] | None = None,
) -> tuple[PlantState, int]:
    commands = commands or {}
    sim_time_ms = from_ms
    for _ in range(seconds):
        sim_time_ms += TICK_MS
        state = step(
            state,
            CONFIG,
            disturbance,
            sim_time_ms=sim_time_ms,
            dt_ms=TICK_MS,
            commands=commands.get(sim_time_ms, []),
        )
    return state, sim_time_ms


def started_plant(disturbance: Disturbance, seconds: int = 899) -> tuple[PlantState, int]:
    """Насос запущен, установка вышла на номинал и прогрелась до момента возмущения."""

    state = step(
        initial_state(CONFIG),
        CONFIG,
        disturbance,
        sim_time_ms=TICK_MS,
        dt_ms=TICK_MS,
        commands=[Command(START_FEED_PUMP, "N-1")],
    )
    return run(state, disturbance, from_ms=TICK_MS, seconds=seconds)


def test_plant_without_running_pump_has_no_flow() -> None:
    state, _ = run(initial_state(CONFIG), PUMP_FAILURE, from_ms=0, seconds=120)

    assert all(branch.flow_tph == 0.0 for branch in state.branches)
    assert state.pump_discharge_pressure_bar == 0.0


def test_flow_appears_gradually_after_pump_start() -> None:
    """Команда не меняет установку мгновенно: расход нарастает во времени."""

    state = step(
        initial_state(CONFIG),
        CONFIG,
        PUMP_FAILURE,
        sim_time_ms=TICK_MS,
        dt_ms=TICK_MS,
        commands=[Command(START_FEED_PUMP, "N-1")],
    )

    assert state.branches[0].flow_tph < 5.0

    after_minute, _ = run(state, PUMP_FAILURE, from_ms=TICK_MS, seconds=60)
    after_ten_minutes, _ = run(state, PUMP_FAILURE, from_ms=TICK_MS, seconds=600)

    assert 50.0 < after_minute.branches[0].flow_tph < 90.0
    assert after_ten_minutes.branches[0].flow_tph > 99.0


def test_stable_mode_keeps_all_parameters_in_normal_range() -> None:
    state, _ = started_plant(PUMP_FAILURE)
    metrics = rule_metrics(state, CONFIG)

    assert metrics["min_branch_flow_ratio"] > 0.95
    assert metrics["flow_imbalance_ratio"] < 0.05
    assert 120.0 < metrics["t11_max_temp_c"] <= 140.0


def test_pump_failure_lowers_flow_and_pressure_of_one_branch_only() -> None:
    state, sim_time_ms = started_plant(PUMP_FAILURE)

    state, _ = run(state, PUMP_FAILURE, from_ms=sim_time_ms, seconds=400)
    values = visible_values(state, CONFIG)

    assert values["branch_2_flow_tph"] < 70.0
    assert values["branch_1_flow_tph"] > 95.0
    assert values["branch_3_flow_tph"] > 95.0
    assert values["branch_2_pressure_bar"] < values["branch_1_pressure_bar"]
    assert values["feed_pump_discharge_pressure_bar"] < 5.2
    # Регулятор исправен: команда и факт совпадают.
    assert values["branch_2_valve_actual_pct"] == values["branch_2_valve_command_pct"]


def test_valve_stiction_splits_command_and_actual_position() -> None:
    state, sim_time_ms = started_plant(VALVE_STICTION)

    state, _ = run(state, VALVE_STICTION, from_ms=sim_time_ms, seconds=400)
    values = visible_values(state, CONFIG)

    assert values["branch_2_valve_command_pct"] == 100.0
    assert values["branch_2_valve_actual_pct"] < 70.0
    assert values["branch_2_flow_tph"] < 70.0
    # Давление на выкиде при закрывающемся регуляторе не падает.
    assert values["feed_pump_discharge_pressure_bar"] > 6.0


def test_lower_flow_raises_temperature_after_heat_exchangers() -> None:
    """Главная причинная связь этапа: расход упал — температура ушла вверх."""

    state, sim_time_ms = started_plant(PUMP_FAILURE)
    before = derived_values(state, CONFIG)["t11_max_temp_c"]

    state, _ = run(state, PUMP_FAILURE, from_ms=sim_time_ms, seconds=500)
    after = derived_values(state, CONFIG)

    assert after["t11_max_temp_c"] > before
    assert after["t11_max_temp_c"] > 140.0
    assert after["t11_temperature_margin_norm"] < 0.0
    assert after["lowest_flow_branch_code"] == 2.0


def test_correct_action_restores_flow_but_not_instantly() -> None:
    state, sim_time_ms = started_plant(PUMP_FAILURE)
    state, sim_time_ms = run(state, PUMP_FAILURE, from_ms=sim_time_ms, seconds=400)
    degraded = state.branches[1].flow_tph

    corrective = {sim_time_ms + TICK_MS: [Command(SWITCH_TO_STANDBY_PUMP, "N-1A")]}
    after_ten_seconds, _ = run(state, PUMP_FAILURE, from_ms=sim_time_ms, seconds=10, commands=corrective)
    recovered, _ = run(state, PUMP_FAILURE, from_ms=sim_time_ms, seconds=400, commands=corrective)

    assert after_ten_seconds.branches[1].flow_tph < degraded + 5.0
    assert recovered.branches[1].flow_tph > 95.0
    assert recovered.severity == 0.0


def test_action_on_the_wrong_branch_does_not_fix_the_cause() -> None:
    state, sim_time_ms = started_plant(VALVE_STICTION)
    state, sim_time_ms = run(state, VALVE_STICTION, from_ms=sim_time_ms, seconds=400)

    wrong = {sim_time_ms + TICK_MS: [Command(RESTORE_FLOW_CONTROL, "FRC-404")]}
    after, _ = run(state, VALVE_STICTION, from_ms=sim_time_ms, seconds=300, commands=wrong)

    assert after.corrected is False
    assert after.branches[1].flow_tph < 70.0


def test_same_inputs_give_the_same_state() -> None:
    first, _ = started_plant(PUMP_FAILURE, seconds=1_200)
    second, _ = started_plant(PUMP_FAILURE, seconds=1_200)

    assert first == second


def test_state_survives_serialization() -> None:
    state, _ = started_plant(PUMP_FAILURE, seconds=300)

    assert PlantState.from_json(state.to_json()) == state
