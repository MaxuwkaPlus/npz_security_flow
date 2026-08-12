from app.domain.commands import Command
from app.domain.downstream import (
    SET_WASH_WATER,
    DownstreamConfig,
    DownstreamState,
    hv_trip_count,
    initial_downstream_state,
    is_online,
    step_downstream,
)

CONFIG = DownstreamConfig()
TICK_MS = 1_000


def run(
    state: DownstreamState,
    *,
    feed_ratio: float,
    seconds: int,
    imbalance: float = 0.0,
    temperature_c: float = 130.0,
    commands: list[Command] | None = None,
) -> DownstreamState:
    for index in range(seconds):
        state = step_downstream(
            state,
            CONFIG,
            feed_ratio=feed_ratio,
            flow_imbalance_ratio=imbalance,
            feed_temperature_c=temperature_c,
            dt_ms=TICK_MS,
            commands=commands if index == 0 and commands else [],
        )
    return state


def loaded_elou(seconds: int = 900) -> DownstreamState:
    """Полная подача, вода подана: обе ступени выведены в работу."""

    return run(
        initial_downstream_state(),
        feed_ratio=1.0,
        seconds=seconds,
        commands=[Command(SET_WASH_WATER, "ELOU", {"ratio": 0.075})],
    )


def test_idle_elou_has_no_level_and_is_offline() -> None:
    state = run(initial_downstream_state(), feed_ratio=0.0, seconds=120)

    assert not is_online(state.elou.load_ratio, CONFIG)
    assert state.elou.stage1_level_mm == 0.0
    assert state.elou.temperature_c == 0.0


def test_load_reaches_elou_with_delay() -> None:
    """Между сырьевой частью и ЭЛОУ есть транспортное запаздывание."""

    after_ten_seconds = run(initial_downstream_state(), feed_ratio=1.0, seconds=10)
    after_five_minutes = run(initial_downstream_state(), feed_ratio=1.0, seconds=300)

    assert after_ten_seconds.elou.load_ratio < 0.25
    assert after_five_minutes.elou.load_ratio > 0.95
    assert after_five_minutes.elou.stage2_load_ratio < after_five_minutes.elou.load_ratio


def test_full_load_keeps_levels_in_normal_range() -> None:
    state = loaded_elou()

    assert 3700.0 < state.elou.stage1_level_mm <= 3820.0
    assert 3700.0 < state.elou.stage2_level_mm <= 3840.0
    assert hv_trip_count(state, CONFIG) == 0
    assert state.elou.temperature_c == 128.0


def test_filling_does_not_trip_the_low_level_interlock() -> None:
    """При наполнении уровень законно ниже 3500 мм: защита ещё не взведена."""

    filling = run(initial_downstream_state(), feed_ratio=1.0, seconds=40)

    assert filling.elou.stage1_level_mm < 3500.0
    assert hv_trip_count(filling, CONFIG) == 0


def test_feed_loss_drops_level_below_interlock() -> None:
    state = loaded_elou()

    starved = run(state, feed_ratio=0.878, seconds=600)

    assert starved.elou.stage1_level_mm < 3500.0
    assert hv_trip_count(starved, CONFIG) >= 1


def test_restored_feed_returns_level_above_interlock() -> None:
    starved = run(loaded_elou(), feed_ratio=0.878, seconds=600)

    restored = run(starved, feed_ratio=1.0, seconds=600)

    assert restored.elou.stage1_level_mm > 3700.0
    assert hv_trip_count(restored, CONFIG) == 0


def test_feed_imbalance_reaches_elou_load() -> None:
    state = run(loaded_elou(), feed_ratio=0.878, seconds=600, imbalance=0.45)

    assert state.elou.imbalance_ratio > 0.18


def test_wash_water_is_set_by_command_and_limited() -> None:
    state = run(
        initial_downstream_state(),
        feed_ratio=1.0,
        seconds=5,
        commands=[Command(SET_WASH_WATER, "ELOU", {"ratio": 0.5})],
    )

    assert state.elou.wash_water_ratio == CONFIG.wash_water_max_ratio


def test_state_survives_serialization() -> None:
    state = loaded_elou(seconds=300)

    assert DownstreamState.from_json(state.to_json()) == state
