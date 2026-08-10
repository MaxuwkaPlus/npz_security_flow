import pytest

from app.domain.clock import SimulationClock

CLOCK = SimulationClock(tick_interval_ms=1_000, snapshot_interval_ms=5_000, duration_ms=3_900_000)


def test_advance_moves_by_one_tick() -> None:
    assert CLOCK.advance(0) == 1_000
    assert CLOCK.advance(1_000) == 2_000


def test_advance_never_passes_scenario_duration() -> None:
    assert CLOCK.advance(3_899_500) == 3_900_000
    assert CLOCK.advance(3_900_000) == 3_900_000
    assert CLOCK.is_finished(3_900_000)


def test_snapshot_is_due_on_configured_interval() -> None:
    due = [time for time in range(0, 11_000, 1_000) if CLOCK.is_snapshot_due(time)]

    assert due == [0, 5_000, 10_000]


def test_snapshot_interval_must_be_multiple_of_tick() -> None:
    with pytest.raises(ValueError, match="кратен"):
        SimulationClock(tick_interval_ms=1_000, snapshot_interval_ms=1_500, duration_ms=10_000)


def test_tick_interval_must_be_positive() -> None:
    with pytest.raises(ValueError, match="положительным"):
        SimulationClock(tick_interval_ms=0, snapshot_interval_ms=0, duration_ms=10_000)
