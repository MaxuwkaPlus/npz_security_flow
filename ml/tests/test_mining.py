"""Проверка поиска системных проблем по всем прохождениям."""

from ml import config, mining


def test_corpus_reveals_verification_as_systemic_gap(corpus):
    """В корпусе проверка последствий пропускается массово — это должно всплыть."""

    findings = mining.mine(corpus)

    assert findings
    assert "verification" in {finding.skill for finding in findings}
    # Находки отсортированы от самой массовой проблемы к менее массовой.
    assert findings == sorted(findings, key=lambda finding: finding.share, reverse=True)


def test_no_conclusions_without_enough_sessions(corpus):
    """На нескольких прохождениях выводов о группе не делается."""

    assert mining.mine(corpus[: config.MINING.min_sessions - 1]) == []


def test_proposed_scenario_uses_only_known_knobs(corpus):
    """Черновик сценария состоит из значений, известных тренажёру."""

    for finding in mining.mine(corpus):
        scenario = finding.scenario
        assert scenario["level_no"] in config.LEVELS
        assert set(scenario["disturbance_causes"]) <= set(config.DISTURBANCE_CAUSES)
        assert set(scenario["focus_steps"]) <= set(config.EXPECTED_STEPS)
        assert set(scenario["knobs"]) == {
            "sensor_delay_ms",
            "nuisance_alarm_rate",
            "reaction_deadline_ms",
            "development_speed_factor",
            "hints_enabled",
            "standby_pump_start_delay_ms",
        }


def test_findings_have_distinct_topics(corpus):
    """Разные проблемы не должны слиться в одно предложение эксперту.

    Пропуск проверки расхода и пропуск downstream-проверок относятся к одному
    навыку, но это две разные проблемы: у каждой свой ключ и свой черновик.
    """

    findings = mining.mine(corpus)
    keys = [finding.key for finding in findings]

    assert len(keys) == len(set(keys))


def test_finding_summary_carries_numbers(corpus):
    """Эксперт должен видеть, на каких числах основан вывод."""

    for finding in mining.mine(corpus):
        assert "%" in finding.summary
        assert finding.sessions > 0
