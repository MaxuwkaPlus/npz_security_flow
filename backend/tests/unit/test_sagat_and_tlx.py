from app.domain.nasa_tlx import SCALES, TlxResponse, validate
from app.domain.sagat import SagatPolicy, score_answers, situation_awareness_score

POLICY = SagatPolicy.from_json(
    {
        "trend_window_ms": 30_000,
        "checkpoints": [
            {
                "code": "after_stable_mode",
                "after_stage_code": "stable_mode",
                "answer_deadline_ms": 120_000,
                "questions": [
                    {
                        "code": "lowest_flow_branch",
                        "kind": "what_changed",
                        "prompt": "Какая ветвь имеет наименьший расход?",
                        "options": ["1", "2", "3"],
                        "rule": "value",
                        "metric": "lowest_flow_branch_code",
                    },
                    {
                        "code": "t11_over_limit",
                        "kind": "what_it_means",
                        "prompt": "Температура выше ограничения?",
                        "options": ["yes", "no"],
                        "rule": "threshold",
                        "metric": "t11_max_temp_c",
                        "threshold": 140.0,
                    },
                    {
                        "code": "k1_feed_trend",
                        "kind": "what_happens_next",
                        "prompt": "Как меняется подача на К-1?",
                        "options": ["rising", "falling", "steady"],
                        "rule": "trend",
                        "metric": "k1_feed_flow_ratio",
                        "trend_tolerance": 0.01,
                    },
                ],
            }
        ],
    }
)
QUESTIONS = POLICY.checkpoints[0].questions
NOW = {"lowest_flow_branch_code": 2.0, "t11_max_temp_c": 145.0, "k1_feed_flow_ratio": 0.90}
EARLIER = {"lowest_flow_branch_code": 2.0, "t11_max_temp_c": 138.0, "k1_feed_flow_ratio": 0.98}


def test_checkpoint_is_found_by_its_trigger_stage() -> None:
    assert POLICY.triggered_by("stable_mode") is not None
    assert POLICY.triggered_by("k1") is None


def test_expected_answers_come_from_plant_state() -> None:
    expected = {question.code: question.expected_answer(NOW, EARLIER) for question in QUESTIONS}

    assert expected == {
        "lowest_flow_branch": "2",
        "t11_over_limit": "yes",
        "k1_feed_trend": "falling",
    }


def test_fully_correct_answers_earn_maximum() -> None:
    scores = score_answers(
        QUESTIONS,
        {"lowest_flow_branch": "2", "t11_over_limit": "yes", "k1_feed_trend": "falling"},
        NOW,
        EARLIER,
    )

    assert scores == {"lowest_flow_branch": 1.0, "t11_over_limit": 1.0, "k1_feed_trend": 1.0}
    assert situation_awareness_score(sum(scores.values()), len(scores)) == 100.0


def test_missing_the_trend_direction_earns_a_partial_score() -> None:
    """«Без изменений» вместо падения — частичное понимание, а рост — нет."""

    scores = score_answers(
        QUESTIONS,
        {"lowest_flow_branch": "1", "t11_over_limit": "no", "k1_feed_trend": "steady"},
        NOW,
        EARLIER,
    )

    assert scores == {"lowest_flow_branch": 0.0, "t11_over_limit": 0.0, "k1_feed_trend": 0.5}
    assert situation_awareness_score(sum(scores.values()), len(scores)) == 16.67


def test_opposite_trend_earns_nothing() -> None:
    scores = score_answers(QUESTIONS, {"k1_feed_trend": "rising"}, NOW, EARLIER)

    assert scores["k1_feed_trend"] == 0.0


def test_unanswered_question_earns_nothing() -> None:
    scores = score_answers(QUESTIONS, {}, NOW, EARLIER)

    assert set(scores.values()) == {0.0}


def test_tlx_averages_six_scales_with_inverted_performance() -> None:
    values = {
        "mental_demand": 8.0,
        "physical_demand": 2.0,
        "temporal_demand": 7.0,
        "performance": 3.0,
        "effort": 6.0,
        "frustration": 4.0,
    }

    # Успешность инвертируется: 3 → 7, поэтому сумма 8+2+7+7+6+4 = 34.
    assert TlxResponse(values).raw_score() == round(34 / 6, 2)


def test_tlx_validation_reports_missing_and_out_of_range() -> None:
    complete = dict.fromkeys(SCALES, 5.0)

    assert validate(complete) is None
    assert "Не заполнены шкалы" in str(validate({"mental_demand": 5.0}))
    assert "вне диапазона" in str(validate(complete | {"effort": 11.0}))
