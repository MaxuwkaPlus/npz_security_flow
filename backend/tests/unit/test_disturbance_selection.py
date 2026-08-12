import pytest

from app.domain.disturbance import DisturbanceOption, select_disturbance

OPTIONS = (
    DisturbanceOption(
        code="feed_pump_capacity_loss",
        cause_code="pump_capacity_loss",
        eligible_branches=(1, 2, 3),
        after_stage_code="stable_mode",
        earliest_delay_ms=0,
        latest_delay_ms=120_000,
        development={"ramp_duration_ms": 360_000, "target_branch_flow_loss": 0.38},
        recovery={"correct_action_type": "switch_to_standby_pump"},
    ),
    DisturbanceOption(
        code="flow_control_valve_stiction",
        cause_code="valve_stiction",
        eligible_branches=(1, 2, 3),
        after_stage_code="stable_mode",
        earliest_delay_ms=0,
        latest_delay_ms=120_000,
        development={"ramp_duration_ms": 360_000, "target_branch_flow_loss": 0.38},
        recovery={"correct_action_type": "restore_flow_control"},
    ),
)


def test_same_seed_gives_same_disturbance() -> None:
    first = select_disturbance(OPTIONS, random_seed=12345, development_speed_factor=1.0)
    second = select_disturbance(OPTIONS, random_seed=12345, development_speed_factor=1.0)

    assert first == second


def test_selection_stays_inside_configured_bounds() -> None:
    for seed in range(50):
        selected = select_disturbance(OPTIONS, random_seed=seed, development_speed_factor=1.0)

        assert selected.target_branch in (1, 2, 3)
        assert 0 <= selected.onset_delay_ms <= 120_000
        assert selected.after_stage_code == "stable_mode"
        assert selected.cause_code in ("pump_capacity_loss", "valve_stiction")


def test_different_seeds_reach_every_branch_and_cause() -> None:
    selected = [select_disturbance(OPTIONS, seed, 1.0) for seed in range(50)]

    assert {item.target_branch for item in selected} == {1, 2, 3}
    assert {item.cause_code for item in selected} == {"pump_capacity_loss", "valve_stiction"}


def test_higher_level_speeds_up_development_but_keeps_cause() -> None:
    slow = select_disturbance(OPTIONS, random_seed=7, development_speed_factor=0.8)
    fast = select_disturbance(OPTIONS, random_seed=7, development_speed_factor=1.6)

    assert slow.cause_code == fast.cause_code
    assert slow.target_branch == fast.target_branch
    assert fast.development["ramp_duration_ms"] < slow.development["ramp_duration_ms"]


def test_empty_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="шаблона возмущения"):
        select_disturbance((), random_seed=1, development_speed_factor=1.0)
