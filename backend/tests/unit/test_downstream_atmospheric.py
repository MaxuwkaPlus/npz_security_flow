from app.domain.commands import Command
from app.domain.downstream import (
    SET_WASH_WATER,
    START_TRANSFER_PUMP,
    DownstreamConfig,
    DownstreamState,
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


def started_chain(seconds: int = 1_200) -> DownstreamState:
    """Вода подана, насосы Н-20 запущены, цепочка вышла на номинал."""

    return run(
        initial_downstream_state(),
        feed_ratio=1.0,
        seconds=seconds,
        commands=[
            Command(SET_WASH_WATER, "ELOU", {"ratio": 0.075}),
            Command(START_TRANSFER_PUMP, "N-20"),
        ],
    )


def test_k1_stays_empty_until_transfer_pump_is_started() -> None:
    """Без Н-20 сырьё не доходит до К-1, как бы долго ни шёл поток."""

    state = run(
        initial_downstream_state(),
        feed_ratio=1.0,
        seconds=900,
        commands=[Command(SET_WASH_WATER, "ELOU", {"ratio": 0.075})],
    )

    assert state.vessel.level_pct > 40.0
    assert state.k1.feed_ratio < CONFIG.section_min_load_ratio
    assert state.k1.bottom_temp_c == 0.0


def test_started_chain_reaches_normal_regime() -> None:
    state = started_chain()

    assert 40.0 < state.vessel.level_pct < 60.0
    assert state.k1.feed_ratio > 0.95
    assert 1.4 < state.k1.pressure_bar < 1.8
    assert 130.0 < state.k1.top_temp_c < 145.0
    assert state.k1.bottom_temp_c < 280.0
    assert 40.0 < state.k1.level_pct < 60.0


def test_feed_loss_reaches_k1_later_than_elou() -> None:
    """Запаздывание нарастает вниз по цепочке: К-1 реагирует позже ЭЛОУ."""

    state = started_chain()
    elou_before = state.elou.load_ratio
    k1_before = state.k1.feed_ratio

    after = run(state, feed_ratio=0.878, seconds=60)

    elou_drop = elou_before - after.elou.load_ratio
    k1_drop = k1_before - after.k1.feed_ratio
    assert elou_drop > k1_drop > 0.0


def test_sustained_feed_loss_pushes_k1_out_of_range() -> None:
    state = run(started_chain(), feed_ratio=0.878, seconds=900)

    assert state.k1.feed_ratio < 0.91
    assert state.k1.bottom_temp_c > 270.0
    assert state.k1.level_pct < 45.0
    assert state.vessel.level_pct < 45.0


def test_restored_feed_returns_k1_to_normal() -> None:
    starved = run(started_chain(), feed_ratio=0.878, seconds=900)

    restored = run(starved, feed_ratio=1.0, seconds=900)

    assert restored.k1.feed_ratio > 0.95
    assert restored.k1.bottom_temp_c < 275.0
    assert is_online(restored.k1.feed_ratio, CONFIG)


def test_state_survives_serialization() -> None:
    state = started_chain(seconds=600)

    assert DownstreamState.from_json(state.to_json()) == state
