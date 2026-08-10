import pytest

from app.domain.rules import condition, parse_rule, rule


def test_empty_rule_holds() -> None:
    assert rule().holds({})


def test_all_conditions_must_hold() -> None:
    check = rule(
        condition("min_branch_flow_ratio", ">=", 0.95),
        condition("flow_imbalance_ratio", "<=", 0.05),
    )

    assert check.holds({"min_branch_flow_ratio": 0.97, "flow_imbalance_ratio": 0.02})
    assert not check.holds({"min_branch_flow_ratio": 0.90, "flow_imbalance_ratio": 0.02})


def test_missing_metric_makes_condition_false() -> None:
    assert not rule(condition("k1_feed_flow_ratio", ">=", 0.95)).holds({})


def test_rule_survives_serialization() -> None:
    original = rule(condition("k2_stability_index", ">=", 0.85), hold_ms=20_000)

    assert parse_rule(original.to_json()) == original


def test_unknown_operator_is_rejected() -> None:
    with pytest.raises(ValueError, match="оператор"):
        condition("k1_level_pct", "=>", 40.0)
