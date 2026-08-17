"""Общие фикстуры тестов.

Корпус читается один раз на весь прогон: 36 прохождений с известным поведением —
это эталон, на котором проверяются правила.
"""

import pytest

from ml import data, skills


@pytest.fixture(scope="session")
def corpus() -> list[data.SessionFacts]:
    return data.load_corpus()


@pytest.fixture(scope="session")
def profiles_by_behaviour(corpus: list[data.SessionFacts]) -> dict[str, list[skills.SkillProfile]]:
    """Профили навыков, сгруппированные по синтетическому профилю поведения."""

    grouped: dict[str, list[skills.SkillProfile]] = {}
    for facts in corpus:
        grouped.setdefault(str(facts.audit["operator_profile"]), []).append(skills.evaluate(facts))
    return grouped
