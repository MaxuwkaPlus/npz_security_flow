from app.domain.rules import condition, rule
from app.domain.stages import Stage, StageOutcome, evaluate_stage, next_stage_code

FEED_STARTUP = Stage(
    code="feed_startup",
    order_no=1,
    success=rule(condition("min_branch_flow_ratio", ">=", 0.5), hold_ms=10_000),
    failure=rule(),
    timeout_ms=360_000,
)
T1_T3 = Stage(
    code="t1_t3",
    order_no=2,
    success=rule(condition("min_branch_flow_ratio", ">=", 0.9), hold_ms=15_000),
    failure=rule(),
    timeout_ms=360_000,
)
STAGES = [FEED_STARTUP, T1_T3]


def evaluate(
    metrics: dict[str, float], *, sim_time_ms: int, holding: int | None, checks: set[str] | None = None
):
    return evaluate_stage(
        FEED_STARTUP,
        STAGES,
        metrics,
        entered_sim_time_ms=0,
        sim_time_ms=sim_time_ms,
        holding_since_ms=holding,
        completed_checks=checks or set(),
    )


def test_condition_must_hold_continuously() -> None:
    started = evaluate({"min_branch_flow_ratio": 0.6}, sim_time_ms=1_000, holding=None)

    assert started.outcome is None
    assert started.holding_since_ms == 1_000

    too_early = evaluate({"min_branch_flow_ratio": 0.6}, sim_time_ms=5_000, holding=1_000)
    assert too_early.outcome is None

    done = evaluate({"min_branch_flow_ratio": 0.6}, sim_time_ms=11_000, holding=1_000)
    assert done.outcome is StageOutcome.SUCCESS
    assert done.next_stage_code == "t1_t3"


def test_broken_condition_resets_the_hold_timer() -> None:
    decision = evaluate({"min_branch_flow_ratio": 0.2}, sim_time_ms=5_000, holding=1_000)

    assert decision.outcome is None
    assert decision.holding_since_ms is None


def test_stage_closes_by_timeout_when_condition_never_holds() -> None:
    decision = evaluate({"min_branch_flow_ratio": 0.1}, sim_time_ms=360_000, holding=None)

    assert decision.outcome is StageOutcome.TIMEOUT
    assert decision.next_stage_code == "t1_t3"


def test_failure_condition_wins_over_success() -> None:
    stage = Stage(
        code="k1",
        order_no=1,
        success=rule(condition("k1_level_pct", ">=", 40.0)),
        failure=rule(condition("k1_bottom_temp_c", ">", 280.0)),
        timeout_ms=360_000,
    )

    decision = evaluate_stage(
        stage,
        [stage],
        {"k1_level_pct": 50.0, "k1_bottom_temp_c": 290.0},
        entered_sim_time_ms=0,
        sim_time_ms=1_000,
        holding_since_ms=None,
        completed_checks=set(),
    )

    assert decision.outcome is StageOutcome.FAILED


def test_required_checks_block_success_but_not_timeout() -> None:
    stage = Stage(
        code="precheck",
        order_no=1,
        success=rule(),
        failure=rule(),
        timeout_ms=120_000,
        required_checks=("feed_system_ready",),
    )

    blocked = evaluate_stage(
        stage,
        [stage],
        {},
        entered_sim_time_ms=0,
        sim_time_ms=1_000,
        holding_since_ms=None,
        completed_checks=set(),
    )
    passed = evaluate_stage(
        stage,
        [stage],
        {},
        entered_sim_time_ms=0,
        sim_time_ms=1_000,
        holding_since_ms=None,
        completed_checks={"feed_system_ready"},
    )
    timed_out = evaluate_stage(
        stage,
        [stage],
        {},
        entered_sim_time_ms=0,
        sim_time_ms=120_000,
        holding_since_ms=None,
        completed_checks=set(),
    )

    assert blocked.outcome is None
    assert passed.outcome is StageOutcome.SUCCESS
    assert timed_out.outcome is StageOutcome.TIMEOUT


def test_last_stage_has_no_next() -> None:
    assert next_stage_code(T1_T3, STAGES) is None
