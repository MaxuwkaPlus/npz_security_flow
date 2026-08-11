from app.domain.alarms import AlarmRule, evaluate
from app.domain.rules import condition, rule

FLOW_DEVIATION = AlarmRule(
    code="flow_deviation_branch",
    level="L1",
    equipment_code="FEED-SYSTEM",
    trigger=rule(condition("min_branch_flow_ratio", "<", 0.92)),
    clear=rule(condition("min_branch_flow_ratio", ">=", 0.95)),
    activation_delay_ms=5_000,
    ack_required=True,
    message="Отклонение расхода сырьевой ветви",
)
RULES = [FLOW_DEVIATION]


def test_short_violation_does_not_raise_alarm() -> None:
    decision = evaluate(
        RULES, {"min_branch_flow_ratio": 0.90}, active_codes=set(), pending_since={}, sim_time_ms=1_000
    )

    assert decision.raised == ()
    assert decision.pending_since == {"flow_deviation_branch": 1_000}


def test_alarm_raises_after_activation_delay() -> None:
    pending = {"flow_deviation_branch": 1_000}

    decision = evaluate(
        RULES, {"min_branch_flow_ratio": 0.90}, active_codes=set(), pending_since=pending, sim_time_ms=6_000
    )

    assert decision.raised == ("flow_deviation_branch",)
    assert decision.pending_since == {}


def test_violation_that_disappears_resets_the_timer() -> None:
    pending = {"flow_deviation_branch": 1_000}

    decision = evaluate(
        RULES, {"min_branch_flow_ratio": 0.99}, active_codes=set(), pending_since=pending, sim_time_ms=3_000
    )

    assert decision.raised == ()
    assert decision.pending_since == {}


def test_hysteresis_keeps_alarm_active_between_thresholds() -> None:
    """Расход вернулся выше порога включения, но ниже порога снятия — тревога остаётся."""

    active = {"flow_deviation_branch"}

    decision = evaluate(
        RULES, {"min_branch_flow_ratio": 0.93}, active_codes=active, pending_since={}, sim_time_ms=20_000
    )

    assert decision.raised == ()
    assert decision.cleared == ()


def test_alarm_clears_when_clear_condition_holds() -> None:
    active = {"flow_deviation_branch"}

    decision = evaluate(
        RULES, {"min_branch_flow_ratio": 0.97}, active_codes=active, pending_since={}, sim_time_ms=30_000
    )

    assert decision.cleared == ("flow_deviation_branch",)


def test_rule_without_its_metric_never_fires() -> None:
    """Правила ЭЛОУ и К-1 молчат, пока эти участки ещё не моделируются."""

    elou = AlarmRule(
        code="elou_load_imbalance",
        level="L4",
        equipment_code="ELOU",
        trigger=rule(condition("elou_load_imbalance_ratio", ">", 0.18)),
        clear=rule(condition("elou_load_imbalance_ratio", "<=", 0.12)),
        activation_delay_ms=0,
        ack_required=True,
        message="Изменение нагрузки ЭЛОУ",
    )

    decision = evaluate([elou], {}, active_codes=set(), pending_since={}, sim_time_ms=1_000)

    assert decision.raised == ()
