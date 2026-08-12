from dataclasses import replace

from app.domain.scoring import ScoringPolicy, SessionFacts, calculate

POLICY = ScoringPolicy.from_json(
    {"safety": 0.40, "action_correctness": 0.25, "process_stability": 0.20, "reaction_speed": 0.15},
    {
        "dangerous_action": 25.0,
        "missed_alarm": 10.0,
        "unverified_action": 8.0,
        "out_of_sequence_action": 5.0,
        "repeated_action": 2.0,
        "critical_area_per_10s": 2.0,
    },
    {"penalty_per_normalized_deviation_second": 0.5, "stability_confirmation_ms": 20_000},
    {"target_reaction_ms": 60_000, "start_from": "first_operator_visible_alarm"},
)

PERFECT = SessionFacts(
    completed_step_weight=17.0,
    total_step_weight=17.0,
    first_visible_alarm_ms=600_000,
    first_correct_action_ms=630_000,
    recovery_time_ms=210_000,
    sagat_earned=5.0,
    sagat_maximum=5.0,
)


def test_flawless_run_scores_one_hundred() -> None:
    scores = calculate(POLICY, PERFECT)

    assert scores.safety == 100.0
    assert scores.action_correctness == 100.0
    assert scores.process_stability == 100.0
    assert scores.reaction_speed == 100.0
    assert scores.resultiveness == 100.0
    assert scores.situation_awareness == 100.0


def test_resultiveness_uses_configured_weights() -> None:
    scores = calculate(POLICY, replace(PERFECT, dangerous_actions=2))

    # Безопасность 100 − 2×25 = 50, остальные составляющие без изменений.
    assert scores.safety == 50.0
    assert scores.resultiveness == round(0.40 * 50 + 0.25 * 100 + 0.20 * 100 + 0.15 * 100, 2)


def test_every_penalty_is_explained_by_a_rule() -> None:
    facts = SessionFacts(
        dangerous_actions=1,
        unacknowledged_alarms=2,
        out_of_sequence_actions=1,
        completed_step_weight=8.0,
        total_step_weight=17.0,
    )

    scores = calculate(POLICY, facts)

    rules = {event.rule_code for event in scores.events}
    assert {"dangerous_action", "missed_alarm", "out_of_sequence_action"} <= rules
    assert all(event.reason for event in scores.events)


def test_scores_never_leave_the_zero_hundred_range() -> None:
    scores = calculate(POLICY, SessionFacts(dangerous_actions=10, normalized_deviation_seconds=10_000))

    assert scores.safety == 0.0
    assert scores.process_stability == 0.0
    assert 0.0 <= scores.resultiveness <= 100.0


def test_missing_correct_action_zeroes_the_reaction_score() -> None:
    facts = SessionFacts(first_visible_alarm_ms=600_000, first_correct_action_ms=None)

    scores = calculate(POLICY, facts)

    assert scores.reaction_speed == 0.0
    assert any(event.rule_code == "no_correct_action" for event in scores.events)


def test_slow_reaction_scales_with_the_target_time() -> None:
    slow = SessionFacts(first_visible_alarm_ms=0, first_correct_action_ms=240_000)

    scores = calculate(POLICY, slow)

    # Цель 60 с, фактически 240 с: 100 × 60/240.
    assert scores.reaction_speed == 25.0


def test_long_deviation_costs_more_than_short_one() -> None:
    short = calculate(POLICY, SessionFacts(normalized_deviation_seconds=20.0)).process_stability
    long = calculate(POLICY, SessionFacts(normalized_deviation_seconds=120.0)).process_stability

    assert short > long


def test_situation_awareness_is_a_share_of_earned_points() -> None:
    scores = calculate(POLICY, SessionFacts(sagat_earned=2.5, sagat_maximum=5.0))

    assert scores.situation_awareness == 50.0


def test_nasa_tlx_does_not_change_resultiveness() -> None:
    with_tlx = calculate(POLICY, replace(PERFECT, raw_nasa_tlx=9.0))

    assert with_tlx.raw_nasa_tlx == 9.0
    assert with_tlx.resultiveness == calculate(POLICY, PERFECT).resultiveness
