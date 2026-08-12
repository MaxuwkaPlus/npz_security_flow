from app.domain.observations import ChecksPolicy, ObservationFact

POLICY = ChecksPolicy.from_json(
    {
        "feed_system_ready": {"observation_type": "inspect_equipment", "target_code": "FEED-SYSTEM"},
        "elou_ready": {"observation_type": "inspect_equipment", "target_code": "ELOU"},
        "declare_deviation": {"observation_type": "declare_deviation", "target_code": "FEED-SYSTEM"},
        "submit_diagnosis": {"by_diagnosis": True},
        "corrective_action": {"action_types": ["switch_to_standby_pump", "restore_flow_control"]},
    }
)


def test_nothing_is_closed_without_operator_activity() -> None:
    assert POLICY.completed([], [], has_diagnosis=False) == frozenset()


def test_observation_closes_only_its_own_check() -> None:
    closed = POLICY.completed([ObservationFact("inspect_equipment", "FEED-SYSTEM")], [], has_diagnosis=False)

    assert closed == {"feed_system_ready"}


def test_same_observation_on_another_target_closes_another_check() -> None:
    closed = POLICY.completed(
        [
            ObservationFact("inspect_equipment", "FEED-SYSTEM"),
            ObservationFact("inspect_equipment", "ELOU"),
        ],
        [],
        has_diagnosis=False,
    )

    assert closed == {"feed_system_ready", "elou_ready"}


def test_unknown_target_closes_nothing() -> None:
    assert (
        POLICY.completed([ObservationFact("inspect_equipment", "K-9")], [], has_diagnosis=False)
        == frozenset()
    )


def test_diagnosis_and_corrective_action_close_their_checks() -> None:
    closed = POLICY.completed([], ["switch_to_standby_pump"], has_diagnosis=True)

    assert closed == {"submit_diagnosis", "corrective_action"}


def test_allowed_targets_are_derived_from_the_policy() -> None:
    assert POLICY.observation_targets("inspect_equipment") == {"FEED-SYSTEM", "ELOU"}
    assert POLICY.observation_targets("verify_result") == frozenset()
