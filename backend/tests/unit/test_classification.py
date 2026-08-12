from app.domain.classification import AppliedAction, EffectRule, classify_effect, classify_on_apply
from app.domain.commands import ActionClassification

EFFECT = EffectRule.from_json(
    {"metric": "min_branch_flow_ratio", "op": ">=", "value": 0.95},
    {"required_observations": ["verify_flow"], "window_ms": 120_000},
)
CORRECTIVE = AppliedAction("switch_to_standby_pump", "N-1A", {})
ROUTINE = AppliedAction("set_control_valve", "FRC-404", {"opening_pct": 80.0})


def verdict(action: AppliedAction, **overrides: object):
    kwargs: dict[str, object] = {
        "is_corrective_type": action.action_type == "switch_to_standby_pump",
        "removed_root_cause": True,
        "diagnosis_submitted": True,
        "previous_actions": (),
        "effect": EFFECT,
    }
    kwargs.update(overrides)
    return classify_on_apply(action, **kwargs)  # type: ignore[arg-type]


def test_routine_control_is_not_classified() -> None:
    result = verdict(ROUTINE)

    assert result.classification is None
    assert result.evaluation_window_ms is None


def test_repeated_command_is_marked_immediately() -> None:
    result = verdict(ROUTINE, previous_actions=(ROUTINE,))

    assert result.classification is ActionClassification.REPEATED


def test_corrective_action_before_diagnosis_violates_sequence() -> None:
    result = verdict(CORRECTIVE, diagnosis_submitted=False)

    assert result.classification is ActionClassification.OUT_OF_SEQUENCE


def test_corrective_action_that_missed_the_cause_is_ineffective() -> None:
    result = verdict(CORRECTIVE, removed_root_cause=False)

    assert result.classification is ActionClassification.INEFFECTIVE


def test_correct_action_waits_for_the_effect_window() -> None:
    """Синтаксически верная команда не считается правильной до подтверждения эффекта."""

    result = verdict(CORRECTIVE)

    assert result.classification is None
    assert result.evaluation_window_ms == 120_000
    assert result.requires_verification is True


def test_effect_decides_the_final_class() -> None:
    assert classify_effect(EFFECT, {"min_branch_flow_ratio": 0.99}) is ActionClassification.CORRECT
    assert classify_effect(EFFECT, {"min_branch_flow_ratio": 0.70}) is ActionClassification.INEFFECTIVE


def test_action_without_effect_rule_counts_as_correct() -> None:
    assert classify_effect(None, {}) is ActionClassification.CORRECT
