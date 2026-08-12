from app.domain.nuisance import NuisancePolicy

CONFIG = {
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
TICK_MS = 1_000


def count_over_hour(rate: float, seed: int = 42) -> int:
    policy = NuisancePolicy.from_json(CONFIG, rate)
    return sum(
        1
        for sim_time_ms in range(TICK_MS, 3_600_000, TICK_MS)
        if policy.due(seed, sim_time_ms, TICK_MS, active_codes=()) is not None
    )


def test_zero_rate_never_raises_nuisance() -> None:
    assert count_over_hour(0.0) == 0


def test_rate_sets_the_expected_order_of_magnitude() -> None:
    """Уровень задаёт интенсивность помех: минимум, средне, много (§9 ТЗ)."""

    low = count_over_hour(0.4)
    medium = count_over_hour(2.0)
    high = count_over_hour(4.5)

    assert low < medium < high
    # За час при 0.4 в минуту ожидается около 24 помех, при 4.5 — около 270.
    assert 12 <= low <= 40
    assert 200 <= high <= 340


def test_same_seed_gives_the_same_stream_of_nuisance() -> None:
    assert count_over_hour(2.0, seed=7) == count_over_hour(2.0, seed=7)


def test_different_seeds_give_different_streams() -> None:
    assert count_over_hour(2.0, seed=7) != count_over_hour(2.0, seed=8)


def test_already_active_code_is_not_repeated() -> None:
    policy = NuisancePolicy.from_json(CONFIG, 60.0)
    busy = [alarm.code for alarm in policy.alarms]

    raised = [
        policy.due(42, sim_time_ms, TICK_MS, active_codes=busy)
        for sim_time_ms in range(TICK_MS, 60_000, TICK_MS)
    ]

    assert set(raised) == {None}


def test_policy_without_alarms_is_silent() -> None:
    policy = NuisancePolicy.from_json({"alarms": []}, 10.0)

    assert policy.due(42, 1_000, TICK_MS, active_codes=()) is None
