"""Политика оценки, версия 1.

Веса результативности взяты из §16.1 технического задания. Штрафы и нормативные
времена в §23 отнесены к несогласованным значениям, поэтому политика помечена
`provisional` и используется только для демонстрации.
"""

from typing import Any

SCORING_POLICY_CODE = "ELOU-AVT-MVP"
SCORING_POLICY_VERSION = 1

WEIGHTS: dict[str, Any] = {
    "provisional": False,
    "safety": 0.40,
    "action_correctness": 0.25,
    "process_stability": 0.20,
    "reaction_speed": 0.15,
}

PENALTIES: dict[str, Any] = {
    "provisional": True,
    "dangerous_action": 25.0,
    "interlock_bypass_attempt": 30.0,
    "missed_alarm": 10.0,
    "unverified_action": 8.0,
    "out_of_sequence_action": 5.0,
    "unnecessary_action": 3.0,
    "repeated_action": 2.0,
    # 0.5 за 10 секунд: сотня баллов уходит примерно за полчаса непрерывной критики.
    # При 2.0 шкала обнулялась за восемь минут и переставала различать прохождения.
    "critical_area_per_10s": 0.5,
}

STABILITY_RULE: dict[str, Any] = {
    "provisional": True,
    # Интегральный штраф: длительное критическое отклонение весит больше короткого.
    "sample_interval_ms": 5_000,
    "penalty_per_normalized_deviation_second": 0.5,
    "stability_confirmation_ms": 20_000,
}

REACTION_RULE: dict[str, Any] = {
    "provisional": True,
    # Отсчёт с первого доступного оператору признака, а не со скрытого начала возмущения (§16.5).
    "start_from": "first_operator_visible_alarm",
    "target_reaction_ms": 60_000,
}
