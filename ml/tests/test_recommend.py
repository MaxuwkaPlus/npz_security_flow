"""Проверка правила «слабое место → профильный сценарий»."""

from dataclasses import replace

from ml import config, data, recommend


def _facts(**overrides) -> data.SessionFacts:
    """Прохождение с закрытым отклонением: дальше тест меняет одну деталь."""

    base = data.SessionFacts(
        session_id="s1",
        operator_id="o1",
        source="backend",
        level_no=1,
        status="completed",
        outcome="stabilized",
        sim_time_ms=3_900_000,
        reaction_deadline_ms=120_000,
        first_alarm_ms=3_200_000,
        declared_deviation_ms=3_230_000,
        diagnosis_ms=3_250_000,
        diagnosis_submitted=True,
        diagnosis_correct=True,
        correct_action_ms=3_260_000,
        verify_flow_done=True,
        downstream_checks_done=7,
        alarms_total=5,
        alarm_ack_delay_avg_ms=10_000,
        known_cause="feed_pump_capacity_loss",
    )
    return replace(base, **overrides)


def test_recommendation_is_deterministic():
    """Одинаковый вход даёт одинаковую рекомендацию, включая целевую ветвь."""

    first = recommend.recommend(_facts())
    second = recommend.recommend(_facts())
    assert first.to_json() == second.to_json()


def test_every_corpus_session_produces_valid_scenario(corpus):
    """На всех 36 прохождениях выход остаётся в allowlist тренажёра."""

    for facts in corpus:
        result = recommend.recommend(facts)
        assert result.level_no in config.LEVELS
        assert result.disturbance_cause in config.DISTURBANCE_CAUSES
        assert result.target_branch in config.TARGET_BRANCHES
        assert set(result.focus_steps) <= set(config.EXPECTED_STEPS)
        assert result.evidence


def test_weak_diagnosis_switches_the_root_cause():
    """Диагностику тренируют второй первопричиной, а не повтором той же."""

    facts = _facts(diagnosis_correct=False, correct_action_ms=None, known_cause="feed_pump_capacity_loss")
    result = recommend.recommend(facts)

    assert result.weak_skill == "diagnosis"
    assert result.disturbance_cause == "flow_control_valve_stiction"


def test_dangerous_action_lowers_the_level():
    """Опасное действие — единственный случай снижения сложности."""

    facts = _facts(level_no=2, dangerous_actions=1)
    result = recommend.recommend(facts)

    assert result.weak_skill == "safety"
    assert result.level_no == 1
    assert result.knobs["hints_enabled"] is True


def test_session_without_weak_spots_raises_the_level():
    """Слабых мест нет — навык проверяется в более трудных условиях."""

    result = recommend.recommend(_facts())

    assert result.weak_skill is None
    assert result.level_no == 2
    assert result.disturbance_cause == "flow_control_valve_stiction"


def test_level_stays_within_allowed_range():
    """Сдвиг уровня не выходит за 1..3."""

    assert recommend.recommend(_facts(level_no=3)).level_no == 3
    assert recommend.recommend(_facts(level_no=1, dangerous_actions=1)).level_no == 1
