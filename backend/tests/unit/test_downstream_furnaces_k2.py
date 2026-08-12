from app.domain.commands import Command
from app.domain.downstream import (
    SET_FURNACE_HEAT_LOAD,
    SET_WASH_WATER,
    START_TRANSFER_PUMP,
    DownstreamConfig,
    DownstreamState,
    heat_to_feed_ratio,
    initial_downstream_state,
    step_downstream,
)

CONFIG = DownstreamConfig()
TICK_MS = 1_000


def run(
    state: DownstreamState,
    *,
    feed_ratio: float,
    seconds: int,
    commands: list[Command] | None = None,
) -> DownstreamState:
    for index in range(seconds):
        state = step_downstream(
            state,
            CONFIG,
            feed_ratio=feed_ratio,
            flow_imbalance_ratio=0.0,
            feed_temperature_c=130.0,
            dt_ms=TICK_MS,
            commands=commands if index == 0 and commands else [],
        )
    return state


def running_plant(seconds: int = 2_400) -> DownstreamState:
    return run(
        initial_downstream_state(),
        feed_ratio=1.0,
        seconds=seconds,
        commands=[
            Command(SET_WASH_WATER, "ELOU", {"ratio": 0.075}),
            Command(START_TRANSFER_PUMP, "N-20"),
            Command(SET_FURNACE_HEAT_LOAD, "FURNACES", {"heat_load_pct": 100.0}),
        ],
    )


def test_full_chain_reaches_stable_regime() -> None:
    state = running_plant()

    assert state.furnaces.feed_ratio > 0.95
    assert 330.0 < state.furnaces.outlet_temp_c < 350.0
    assert heat_to_feed_ratio(state, CONFIG) < 1.05
    assert 0.2 < state.k2.pressure_bar < 1.0
    assert state.k2.top_temp_c < 148.0
    assert state.k2.bottom_temp_c < 350.0
    assert state.k2.stability_index > 0.85
    assert state.k2.side_draw_stability_index > 0.85
    assert state.k2.product_stability_index > 0.85


def test_feed_loss_degrades_k2_and_products() -> None:
    state = run(running_plant(), feed_ratio=0.878, seconds=1_200)

    assert state.k2.stability_index < 0.85
    assert state.k2.side_draw_stability_index < 0.85
    assert state.k2.product_stability_index < 0.85
    assert state.k2.bottom_temp_c > 340.0


def test_keeping_heat_load_after_feed_loss_raises_heat_to_feed() -> None:
    """Расход упал, нагрузку не тронули — отношение тепла к сырью уже выросло."""

    stable = running_plant()
    before = heat_to_feed_ratio(stable, CONFIG)

    starved = run(stable, feed_ratio=0.878, seconds=1_200)

    assert before < 1.05
    assert heat_to_feed_ratio(starved, CONFIG) > 1.05


def test_dangerous_heat_compensation_pushes_ratio_into_critical_area() -> None:
    """Оператор компенсирует симптом нагрузкой печей вместо восстановления расхода."""

    starved = run(running_plant(), feed_ratio=0.878, seconds=900)

    compensated = run(
        starved,
        feed_ratio=0.878,
        seconds=600,
        commands=[Command(SET_FURNACE_HEAT_LOAD, "FURNACES", {"heat_load_pct": 125.0})],
    )

    assert heat_to_feed_ratio(compensated, CONFIG) > 1.25
    assert compensated.furnaces.outlet_temp_c > 360.0
    # Компенсация не помогает: устойчивость К-2 падает ещё сильнее.
    assert compensated.k2.stability_index < run(starved, feed_ratio=0.878, seconds=600).k2.stability_index


def test_lowering_heat_load_with_feed_keeps_ratio_safe() -> None:
    """Правильная реакция на снижение расхода — снизить и тепловую нагрузку."""

    starved = run(running_plant(), feed_ratio=0.878, seconds=900)

    balanced = run(
        starved,
        feed_ratio=0.878,
        seconds=600,
        commands=[Command(SET_FURNACE_HEAT_LOAD, "FURNACES", {"heat_load_pct": 88.0})],
    )

    assert heat_to_feed_ratio(balanced, CONFIG) < 1.05


def test_unfired_furnaces_do_not_heat_the_product() -> None:
    """Печи стартуют погашенными: продукт проходит с температурой низа К-1."""

    state = run(
        initial_downstream_state(),
        feed_ratio=1.0,
        seconds=2_400,
        commands=[
            Command(SET_WASH_WATER, "ELOU", {"ratio": 0.075}),
            Command(START_TRANSFER_PUMP, "N-20"),
        ],
    )

    assert state.furnaces.heat_load_pct == 0.0
    assert heat_to_feed_ratio(state, CONFIG) == 0.0
    assert state.furnaces.outlet_temp_c < 280.0


def test_heat_load_is_limited_by_configuration() -> None:
    state = run(
        running_plant(seconds=1_200),
        feed_ratio=1.0,
        seconds=10,
        commands=[Command(SET_FURNACE_HEAT_LOAD, "FURNACES", {"heat_load_pct": 500.0})],
    )

    assert state.furnaces.heat_load_pct == CONFIG.furnace_max_heat_load_pct


def test_state_survives_serialization() -> None:
    state = running_plant(seconds=1_200)

    assert DownstreamState.from_json(state.to_json()) == state
