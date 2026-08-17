"""Проверка правил на корпусе.

Смысл этих тестов: у каждого синтетического профиля поведения известен свой изъян.
Если правила расчёта навыков верны, слабое место должно совпасть с изъяном профиля.
Так проверяется методика, а не отдельная формула.
"""

from ml import config, data, skills


def _weak_codes(profile: skills.SkillProfile) -> list[str]:
    return [skill.code for skill in profile.weak_skills]


def test_no_verification_profile_is_weak_in_verification(profiles_by_behaviour):
    """Оператор, который не проверяет результат, слаб именно в проверке.

    Первым слабым местом проверка становится, если оператор не совершил опасного
    действия: безопасность всегда разбирают раньше.
    """

    for profile in profiles_by_behaviour["no_verification"]:
        assert "verification" in _weak_codes(profile)
        if not profile.skills["safety"].is_weak:
            assert profile.weak_skill.code == "verification"


def test_wrong_diagnosis_profile_is_weak_in_diagnosis(profiles_by_behaviour):
    """Неверный диагноз выводит в слабые места диагностику, а не действие.

    Действие не могло быть верным, если причина не найдена, поэтому навык
    `correction` в таких прохождениях не оценивается.
    """

    for profile in profiles_by_behaviour["wrong_diagnosis"]:
        assert "diagnosis" in _weak_codes(profile)
        assert profile.skills["correction"].score is None
        if not profile.skills["safety"].is_weak:
            assert profile.weak_skill.code == "diagnosis"


def test_dangerous_action_outranks_other_weak_spots(profiles_by_behaviour):
    """Опасное действие разбирают раньше любого другого слабого места."""

    with_danger = [
        profile
        for profiles in profiles_by_behaviour.values()
        for profile in profiles
        if profile.skills["safety"].forced_weak
    ]
    assert with_danger, "в корпусе должны быть прохождения с опасным действием"
    for profile in with_danger:
        assert profile.weak_skill.code == "safety"


def test_expert_profile_has_few_weak_spots(profiles_by_behaviour):
    """У эталонного поведения слабых мест почти нет."""

    profiles = profiles_by_behaviour["expert"]
    without_weak = sum(1 for profile in profiles if profile.weak_skill is None)
    assert without_weak >= len(profiles) / 2

    averages = skills.average_scores(profiles)
    assert averages["detection"] >= config.WEAK_SKILL_THRESHOLD
    assert averages["verification"] >= config.WEAK_SKILL_THRESHOLD


def test_deficiency_of_profile_shows_up_as_highest_weak_share(profiles_by_behaviour):
    """Изъян профиля чаще прочих попадает в слабые места."""

    expected = {
        "slow": "detection",
        "alarm_overload": "alarm_handling",
        "chaotic": "alarm_handling",
    }
    for behaviour, skill_code in expected.items():
        shares = skills.weak_share(profiles_by_behaviour[behaviour])
        assert shares[skill_code] == max(shares.values()), (behaviour, shares)


def test_skill_is_not_evaluated_when_it_could_not_show_up():
    """Навык без повода проявиться не оценивается и не становится слабым местом."""

    facts = data.SessionFacts(
        session_id="s1",
        operator_id="o1",
        source="backend",
        level_no=1,
        status="running",
        outcome=None,
        sim_time_ms=60_000,
        reaction_deadline_ms=120_000,
    )
    profile = skills.evaluate(facts)

    assert profile.skills["detection"].score is None
    assert profile.skills["verification"].score is None
    assert profile.skills["alarm_handling"].score is None
    # Дисциплина команд оценивается всегда: опасное действие возможно на любом этапе.
    assert profile.skills["safety"].score == 100.0
    assert profile.weak_skill is None


def test_scores_stay_in_range(corpus):
    """Балл навыка всегда в диапазоне 0..100."""

    for facts in corpus:
        for skill in skills.evaluate(facts).skills.values():
            assert skill.score is None or 0.0 <= skill.score <= 100.0
