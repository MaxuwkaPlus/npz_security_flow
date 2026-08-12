from app.domain.report import (
    ConclusionFacts,
    Outcome,
    absolute_drop,
    conclusions,
    efficiency_retention,
    longest_deviating_parameters,
    outcome_of,
)

GOOD_RUN = ConclusionFacts(
    deviation_declared=True,
    diagnosis_correct=True,
    correct_action_done=True,
    dangerous_actions=0,
    downstream_checks_done=7,
    downstream_checks_total=7,
    detection_time_ms=40_000,
    reaction_deadline_ms=120_000,
    unacknowledged_alarms=0,
)


def test_outcome_requires_both_normal_parameters_and_checked_consequences() -> None:
    """§22: завершение требует downstream-проверок, а не только параметров в норме."""

    assert (
        outcome_of("completed", parameters_in_range=True, downstream_checks_done=True) is Outcome.STABILIZED
    )
    assert (
        outcome_of("completed", parameters_in_range=True, downstream_checks_done=False)
        is Outcome.NOT_STABILIZED
    )
    assert (
        outcome_of("completed", parameters_in_range=False, downstream_checks_done=True)
        is Outcome.NOT_STABILIZED
    )
    assert outcome_of("aborted", parameters_in_range=True, downstream_checks_done=True) is Outcome.ABORTED


def test_flawless_run_gets_positive_conclusions() -> None:
    lines = conclusions(GOOD_RUN)

    assert "Быстро обнаруживает отклонение." in lines
    assert "Правильно определяет первопричину и устраняет её." in lines
    assert "Прослеживает последствия по всей цепочке установки." in lines


def test_fixed_cause_without_downstream_checks_is_called_out() -> None:
    """Главный учебный принцип §41: исправил, но не проверил последствия."""

    facts = ConclusionFacts(**{**_as_dict(GOOD_RUN), "downstream_checks_done": 0})

    lines = conclusions(facts)

    assert "Не проверяет downstream-последствия после воздействия." in lines


def test_dangerous_compensation_is_named_in_conclusions() -> None:
    facts = ConclusionFacts(**{**_as_dict(GOOD_RUN), "dangerous_actions": 1})

    lines = conclusions(facts)

    assert any("тепловой нагрузкой" in line for line in lines)


def test_late_detection_and_missing_diagnosis_are_named() -> None:
    facts = ConclusionFacts(
        **{
            **_as_dict(GOOD_RUN),
            "detection_time_ms": 300_000,
            "diagnosis_correct": False,
            "correct_action_done": False,
        }
    )

    lines = conclusions(facts)

    assert "Обнаруживает отклонение позже допустимого времени реакции." in lines
    assert "Первопричина не установлена и не устранена." in lines


def test_efficiency_retention_compares_levels() -> None:
    assert efficiency_retention(80.0, 60.0) == 75.0
    assert absolute_drop(80.0, 60.0) == 20.0
    assert efficiency_retention(0.0, 60.0) is None


def test_worst_parameters_are_sorted_by_time_out_of_range() -> None:
    worst = longest_deviating_parameters(
        [("k2_stability_index", 30_000), ("min_branch_flow_ratio", 90_000), ("k1_level_pct", 0)]
    )

    assert [item["metric"] for item in worst] == ["min_branch_flow_ratio", "k2_stability_index"]


def _as_dict(facts: ConclusionFacts) -> dict[str, object]:
    return {
        "deviation_declared": facts.deviation_declared,
        "diagnosis_correct": facts.diagnosis_correct,
        "correct_action_done": facts.correct_action_done,
        "dangerous_actions": facts.dangerous_actions,
        "downstream_checks_done": facts.downstream_checks_done,
        "downstream_checks_total": facts.downstream_checks_total,
        "detection_time_ms": facts.detection_time_ms,
        "reaction_deadline_ms": facts.reaction_deadline_ms,
        "unacknowledged_alarms": facts.unacknowledged_alarms,
    }
