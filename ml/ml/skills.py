"""Шесть навыков оператора и поиск слабого места.

Каждый навык — прозрачная формула от фактов прохождения, а не «чёрный ящик».
Это осознанное решение: методист должен уметь оспорить оценку, а для этого он
должен видеть, из какого числа она получилась. Поэтому рядом с баллом всегда
лежит `evidence` — тот самый факт словами.

Навык может быть не оценён (`score is None`). Так бывает, когда проявить его было
негде: например, проверять результат нечего, если корректирующее действие вообще
не выполнялось. Не оценённый навык не может стать слабым местом — иначе
рекомендация уводила бы в сторону от настоящей проблемы.
"""

from dataclasses import dataclass

from ml import config
from ml.data import SessionFacts


@dataclass(frozen=True, slots=True)
class Skill:
    code: str
    name: str
    score: float | None
    evidence: str
    # Правило технолога сильнее арифметики: некоторые факты делают навык слабым
    # независимо от итогового балла.
    forced_weak: bool = False

    @property
    def is_weak(self) -> bool:
        if self.score is None:
            return False
        return self.forced_weak or self.score < config.WEAK_SKILL_THRESHOLD


@dataclass(frozen=True, slots=True)
class SkillProfile:
    """Профиль навыков одного прохождения."""

    session_id: str
    operator_id: str
    level_no: int
    skills: dict[str, Skill]

    @property
    def weak_skills(self) -> list[Skill]:
        """Слабые навыки по убыванию важности.

        Сначала то, что нарушает безопасность (`forced_weak`), затем самый низкий
        балл, при равенстве — более критичный навык из `SKILL_ORDER`.
        """

        weak = [skill for skill in self.skills.values() if skill.is_weak]
        return sorted(
            weak,
            key=lambda skill: (not skill.forced_weak, skill.score, config.SKILL_ORDER.index(skill.code)),
        )

    @property
    def weak_skill(self) -> Skill | None:
        weak = self.weak_skills
        return weak[0] if weak else None

    def to_json(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "operator_id": self.operator_id,
            "level_no": self.level_no,
            "skills": [
                {"code": skill.code, "name": skill.name, "score": skill.score, "evidence": skill.evidence}
                for skill in self.skills.values()
            ],
            "weak_skill": self.weak_skill.code if self.weak_skill else None,
        }


def evaluate(facts: SessionFacts) -> SkillProfile:
    """Считает все шесть навыков по фактам прохождения."""

    computed = [
        _detection(facts),
        _diagnosis(facts),
        _correction(facts),
        _verification(facts),
        _alarm_handling(facts),
        _safety(facts),
    ]
    by_code = {skill.code: skill for skill in computed}
    return SkillProfile(
        session_id=facts.session_id,
        operator_id=facts.operator_id,
        level_no=facts.level_no,
        # Порядок словаря — порядок критичности из конфигурации, так его читает эксперт.
        skills={code: by_code[code] for code in config.SKILL_ORDER},
    )


def average_scores(profiles: list[SkillProfile]) -> dict[str, float]:
    """Средний балл по каждому навыку. Не оценённые прохождения пропускаются."""

    averages: dict[str, float] = {}
    for code in config.SKILL_ORDER:
        scores: list[float] = []
        for profile in profiles:
            score = profile.skills[code].score
            if score is not None:
                scores.append(score)
        if scores:
            averages[code] = round(sum(scores) / len(scores), 1)
    return averages


def weak_share(profiles: list[SkillProfile]) -> dict[str, float]:
    """Доля прохождений, где навык оказался слабым. Основа для поиска общих проблем."""

    shares: dict[str, float] = {}
    for code in config.SKILL_ORDER:
        evaluated = [profile for profile in profiles if profile.skills[code].score is not None]
        if evaluated:
            weak = sum(1 for profile in evaluated if profile.skills[code].is_weak)
            shares[code] = round(weak / len(evaluated), 2)
    return shares


# --- Навыки ---------------------------------------------------------------


def _detection(facts: SessionFacts) -> Skill:
    """Насколько быстро оператор заметил отклонение после первой видимой тревоги."""

    if not facts.disturbance_happened:
        return _skipped("detection", "возмущение ещё не проявилось")
    if facts.detection_time_ms is None:
        return _skill("detection", 0.0, "отклонение не зафиксировано оператором")

    deadline = facts.reaction_deadline_ms
    score = _decay(
        facts.detection_time_ms,
        good=deadline * config.DETECTION_GOOD_RATIO,
        bad=deadline * config.DETECTION_BAD_RATIO,
    )
    return _skill(
        "detection",
        score,
        f"отклонение зафиксировано за {facts.detection_time_ms // 1000} с "
        f"при дедлайне уровня {deadline // 1000} с",
    )


def _diagnosis(facts: SessionFacts) -> Skill:
    """Названа ли первопричина. Две причины различаются только по признакам."""

    if not facts.disturbance_happened:
        return _skipped("diagnosis", "возмущение ещё не проявилось")
    if not facts.diagnosis_submitted:
        return _skill("diagnosis", 0.0, "диагноз не заявлен")
    if not facts.diagnosis_correct:
        return _skill("diagnosis", config.DIAGNOSIS_WRONG_SCORE, "заявлена неверная первопричина")
    return _skill("diagnosis", 100.0, "первопричина определена верно")


def _correction(facts: SessionFacts) -> Skill:
    """Выполнено ли действие, устраняющее причину, и как быстро."""

    if not facts.disturbance_happened:
        return _skipped("correction", "возмущение ещё не проявилось")
    if facts.reaction_time_ms is None and not facts.diagnosis_correct:
        # Причина не найдена — устранять было нечего. Тренировать здесь надо диагностику,
        # поэтому навык не оценивается и не может увести рекомендацию в сторону.
        return _skipped("correction", "первопричина не установлена — оценивать действие не по чему")
    if facts.reaction_time_ms is None:
        return _skill("correction", 0.0, "первопричина названа верно, но действие не выполнено")

    deadline = facts.reaction_deadline_ms
    score = _decay(
        facts.reaction_time_ms,
        good=deadline * config.CORRECTION_GOOD_RATIO,
        bad=deadline * config.CORRECTION_BAD_RATIO,
    )
    return _skill(
        "correction",
        score,
        f"корректирующее действие через {facts.reaction_time_ms // 1000} с "
        f"при дедлайне уровня {deadline // 1000} с",
    )


def _verification(facts: SessionFacts) -> Skill:
    """Проверил ли оператор результат своего действия и последствия ниже по цепочке."""

    if facts.correct_action_ms is None:
        return _skipped("verification", "корректирующего действия не было — проверять нечего")

    total = len(config.DOWNSTREAM_CHECKS)
    score = config.VERIFY_FLOW_WEIGHT * float(facts.verify_flow_done)
    score += config.DOWNSTREAM_WEIGHT * facts.downstream_checks_done / total
    verified = "проверен" if facts.verify_flow_done else "не проверен"
    return _skill(
        "verification",
        score,
        f"расход после воздействия {verified}, "
        f"downstream-проверок закрыто {facts.downstream_checks_done} из {total}",
    )


def _alarm_handling(facts: SessionFacts) -> Skill:
    """Подтверждение тревог и устойчивость к потоку второстепенных сообщений."""

    if facts.alarms_total == 0:
        return _skipped("alarm_handling", "значимых тревог не было")
    if facts.alarm_ack_delay_avg_ms is None:
        return _skill("alarm_handling", 0.0, f"ни одна из {facts.alarms_total} тревог не подтверждена")

    score = _decay(facts.alarm_ack_delay_avg_ms, config.ALARM_ACK_GOOD_MS, config.ALARM_ACK_BAD_MS)
    score -= config.SAFETY_PENALTIES["missed_alarm"] * facts.alarms_unacknowledged
    return _skill(
        "alarm_handling",
        score,
        f"среднее подтверждение {facts.alarm_ack_delay_avg_ms // 1000} с, "
        f"без подтверждения {facts.alarms_unacknowledged} из {facts.alarms_total} "
        f"на фоне {facts.nuisance_alarms_total} второстепенных",
    )


def _safety(facts: SessionFacts) -> Skill:
    """Дисциплина команд.

    Считается только то, что сделал оператор. Критические события установки сюда не
    входят: они бывают следствием медленной реакции и уже учтены в других навыках,
    а двойной штраф за один и тот же промах исказил бы картину.
    """

    penalties = config.SAFETY_PENALTIES
    score = 100.0
    score -= penalties["dangerous_action"] * facts.dangerous_actions
    score -= penalties["out_of_sequence_action"] * facts.out_of_sequence_actions
    score -= penalties["repeated_action"] * facts.repeated_actions
    return _skill(
        "safety",
        score,
        f"опасных действий {facts.dangerous_actions}, "
        f"нарушений последовательности {facts.out_of_sequence_actions}, "
        f"повторных команд {facts.repeated_actions}",
        # Даже одно опасное действие требует разбора: по арифметике штрафов балл
        # остался бы выше порога, а по смыслу это первое, что надо отработать.
        forced_weak=facts.dangerous_actions > 0,
    )


# --- Вспомогательное ------------------------------------------------------


def _skill(code: str, score: float, evidence: str, forced_weak: bool = False) -> Skill:
    return Skill(
        code=code,
        name=config.SKILL_NAMES[code],
        score=_bounded(score),
        evidence=evidence,
        forced_weak=forced_weak,
    )


def _skipped(code: str, reason: str) -> Skill:
    return Skill(code=code, name=config.SKILL_NAMES[code], score=None, evidence=reason)


def _decay(value: float, good: float, bad: float) -> float:
    """100 баллов при `value <= good`, 0 при `value >= bad`, линейно между ними."""

    if value <= good:
        return 100.0
    if value >= bad:
        return 0.0
    return 100.0 * (bad - value) / (bad - good)


def _bounded(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)
