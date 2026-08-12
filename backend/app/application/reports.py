"""Итоговый отчёт и сравнение уровней.

Отчёт целиком выводится из журнала и версий конфигурации, поэтому его можно
пересобрать заново и получить тот же документ (§18).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select

from app.application.observations import completed_checks
from app.application.runtime_config import checks_policy
from app.application.scoring import calculate_scores
from app.core.errors import NotFoundError
from app.domain.commands import ActionClassification
from app.domain.report import (
    ConclusionFacts,
    absolute_drop,
    conclusions,
    efficiency_retention,
    longest_deviating_parameters,
    outcome_of,
)
from app.domain.rules import Condition, parse_rule
from app.infrastructure.db.models import (
    OperatorAction,
    OperatorDiagnosis,
    ProcessSnapshot,
    ScenarioLevel,
    ScenarioStage,
    ScenarioVersion,
    SessionAlarm,
    SessionReport,
    SessionScore,
    SessionStageHistory,
    TrainingSession,
)
from app.infrastructure.db.types import utcnow
from app.infrastructure.db.unit_of_work import UnitOfWork

REPORT_VERSION = 1
DOWNSTREAM_CHECKS = (
    "verify_t11",
    "verify_elou",
    "verify_e15",
    "verify_k1",
    "verify_furnaces",
    "verify_k2",
    "verify_products",
)


async def build_report(uow: UnitOfWork, session_id: str) -> dict[str, Any]:
    """Собирает и сохраняет отчёт. Повторный вызов пересобирает его заново."""

    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
    level = await uow.session.get(ScenarioLevel, training_session.scenario_level_id)
    if scenario is None or level is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария сессии не найдена")

    scores = await calculate_scores(uow, session_id)
    actions = list((await uow.session.scalars(_actions_query(session_id))).all())
    alarms = list((await uow.session.scalars(_alarms_query(session_id))).all())
    stages = list((await uow.session.scalars(_stages_query(session_id))).all())
    snapshots = list((await uow.session.scalars(_snapshots_query(session_id))).all())
    diagnoses = list((await uow.session.scalars(_diagnoses_query(session_id))).all())
    closed = await completed_checks(uow, session_id, checks_policy(scenario))
    conditions = await _stable_mode_conditions(uow, scenario.id)

    parameters_in_range = _in_range(snapshots[-1], conditions) if snapshots else False
    detection_ms = _detection_time(alarms, stages, closed, snapshots)
    facts = ConclusionFacts(
        deviation_declared="declare_deviation" in closed,
        diagnosis_correct=any(diagnosis.is_correct for diagnosis in diagnoses),
        correct_action_done=any(action.classification == ActionClassification.CORRECT for action in actions),
        dangerous_actions=_count(actions, ActionClassification.DANGEROUS),
        downstream_checks_done=len(set(DOWNSTREAM_CHECKS) & closed),
        downstream_checks_total=len(DOWNSTREAM_CHECKS),
        detection_time_ms=detection_ms,
        reaction_deadline_ms=level.reaction_deadline_ms,
        unacknowledged_alarms=sum(
            1 for alarm in alarms if alarm.ack_required and alarm.acknowledged_sim_time_ms is None
        ),
    )

    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "session": {
            "id": training_session.id,
            "operator_id": training_session.operator_id,
            "instructor_id": training_session.instructor_id,
            "status": training_session.status,
            "sim_time_ms": training_session.sim_time_ms,
        },
        "versions": {
            "scenario_code": scenario.scenario_code,
            "scenario_version": scenario.version,
            "scenario_version_id": scenario.id,
            "installation_version_id": scenario.installation_version_id,
            "level_no": level.level_no,
            "scoring_policy_version_id": training_session.scoring_policy_version_id,
        },
        "outcome": outcome_of(training_session.status, parameters_in_range).value,
        "timings": {
            "total_sim_time_ms": training_session.sim_time_ms,
            "detection_time_ms": detection_ms,
            "reaction_time_ms": _reaction_time(alarms, actions),
            "recovery_time_ms": scores.recovery_time_ms,
        },
        "scores": {
            "safety": scores.safety,
            "action_correctness": scores.action_correctness,
            "process_stability": scores.process_stability,
            "reaction_speed": scores.reaction_speed,
            "resultiveness": scores.resultiveness,
            "situation_awareness": scores.situation_awareness,
            "raw_nasa_tlx": scores.raw_nasa_tlx,
        },
        "score_events": [
            {
                "dimension": event.dimension,
                "delta": event.delta,
                "rule_code": event.rule_code,
                "reason": event.reason,
            }
            for event in scores.events
        ],
        "actions": _action_breakdown(actions),
        "alarms": _alarm_breakdown(alarms),
        "downstream_checks": {
            "completed": sorted(set(DOWNSTREAM_CHECKS) & closed),
            "missing": sorted(set(DOWNSTREAM_CHECKS) - closed),
        },
        "stages": [
            {
                "stage_code": entry.stage_code,
                "entered_sim_time_ms": entry.entered_sim_time_ms,
                "exited_sim_time_ms": entry.exited_sim_time_ms,
                "outcome": entry.outcome,
            }
            for entry in stages
        ],
        "worst_parameters": longest_deviating_parameters(_deviation_by_metric(snapshots, conditions)),
        "conclusions": conclusions(facts),
    }
    await _store(uow, session_id, report)
    return report


async def level_comparison(uow: UnitOfWork, operator_id: str) -> dict[str, Any]:
    """Сравнение уровней одного оператора (§16.9)."""

    query = (
        select(TrainingSession, SessionScore, ScenarioLevel)
        .join(SessionScore, SessionScore.session_id == TrainingSession.id)
        .join(ScenarioLevel, ScenarioLevel.id == TrainingSession.scenario_level_id)
        .where(TrainingSession.operator_id == operator_id)
        .order_by(TrainingSession.created_at)
    )
    by_level: dict[int, dict[str, Any]] = {}
    for _, score, level in (await uow.session.execute(query)).all():
        # Более поздняя сессия того же уровня замещает предыдущую.
        by_level[level.level_no] = {
            "level_no": level.level_no,
            "session_id": score.session_id,
            "resultiveness": score.resultiveness_score,
            "safety": score.safety_score,
            "action_correctness": score.action_correctness_score,
            "process_stability": score.process_stability_score,
            "reaction_speed": score.reaction_score,
            "situation_awareness": score.situation_awareness_score,
            "raw_nasa_tlx": score.raw_nasa_tlx,
        }

    first = by_level.get(1, {}).get("resultiveness")
    third = by_level.get(3, {}).get("resultiveness")
    return {
        "operator_id": operator_id,
        "levels": [by_level[key] for key in sorted(by_level)],
        "efficiency_retention": (
            None if first is None or third is None else efficiency_retention(first, third)
        ),
        "absolute_drop": None if first is None or third is None else absolute_drop(first, third),
    }


async def _store(uow: UnitOfWork, session_id: str, report: dict[str, Any]) -> None:
    existing = await uow.session.get(SessionReport, session_id)
    if existing is not None:
        await uow.session.delete(existing)
        await uow.flush()
    uow.session.add(
        SessionReport(
            session_id=session_id,
            report_version=REPORT_VERSION,
            report_json=report,
            generated_at=utcnow(),
        )
    )


def _actions_query(session_id: str) -> Any:
    return (
        select(OperatorAction)
        .where(OperatorAction.session_id == session_id)
        .order_by(OperatorAction.sim_time_ms)
    )


def _alarms_query(session_id: str) -> Any:
    return (
        select(SessionAlarm)
        .where(SessionAlarm.session_id == session_id, SessionAlarm.is_nuisance.is_(False))
        .order_by(SessionAlarm.started_sim_time_ms)
    )


def _stages_query(session_id: str) -> Any:
    return (
        select(SessionStageHistory)
        .where(SessionStageHistory.session_id == session_id)
        .order_by(SessionStageHistory.entered_sim_time_ms)
    )


def _snapshots_query(session_id: str) -> Any:
    return (
        select(ProcessSnapshot)
        .where(ProcessSnapshot.session_id == session_id)
        .order_by(ProcessSnapshot.sim_time_ms)
    )


def _diagnoses_query(session_id: str) -> Any:
    return select(OperatorDiagnosis).where(OperatorDiagnosis.session_id == session_id)


async def _stable_mode_conditions(uow: UnitOfWork, scenario_version_id: str) -> tuple[Condition, ...]:
    query = select(ScenarioStage).where(
        ScenarioStage.scenario_version_id == scenario_version_id,
        ScenarioStage.code == "stable_mode",
    )
    stage = await uow.session.scalar(query)
    return () if stage is None else parse_rule(stage.success_rule_json).conditions


def _action_breakdown(actions: Sequence[OperatorAction]) -> dict[str, Any]:
    return {
        "total": len(actions),
        "by_classification": {
            classification.value: _count(actions, classification)
            for classification in ActionClassification
            if _count(actions, classification)
        },
        "rejected": [
            {
                "action_type": action.action_type,
                "target_code": action.target_code,
                "sim_time_ms": action.sim_time_ms,
                "reason": action.rejection_reason,
            }
            for action in actions
            if action.rejection_reason
        ],
        "unverified": [
            {"action_type": action.action_type, "sim_time_ms": action.sim_time_ms}
            for action in actions
            if action.requires_verification
        ],
    }


def _alarm_breakdown(alarms: Sequence[SessionAlarm]) -> dict[str, Any]:
    return {
        "total": len(alarms),
        "timeline": [
            {
                "alarm_code": alarm.alarm_code,
                "level": alarm.level,
                "equipment_code": alarm.equipment_code,
                "started_sim_time_ms": alarm.started_sim_time_ms,
                "acknowledged_sim_time_ms": alarm.acknowledged_sim_time_ms,
                "cleared_sim_time_ms": alarm.cleared_sim_time_ms,
            }
            for alarm in alarms
        ],
        "unacknowledged": [
            alarm.alarm_code
            for alarm in alarms
            if alarm.ack_required and alarm.acknowledged_sim_time_ms is None
        ],
    }


def _count(actions: Sequence[OperatorAction], classification: str) -> int:
    return sum(1 for action in actions if action.classification == classification)


def _in_range(snapshot: ProcessSnapshot, conditions: Sequence[Condition]) -> bool:
    if not conditions:
        return False
    metrics = _metrics(snapshot)
    return all(condition.holds(metrics) for condition in conditions)


def _metrics(snapshot: ProcessSnapshot) -> Mapping[str, float]:
    return {**snapshot.visible_values_json, **snapshot.derived_values_json}


def _deviation_by_metric(
    snapshots: Sequence[ProcessSnapshot], conditions: Sequence[Condition]
) -> list[tuple[str, int]]:
    if len(snapshots) < 2 or not conditions:
        return []
    interval = snapshots[1].sim_time_ms - snapshots[0].sim_time_ms
    totals: dict[str, int] = {}
    for snapshot in snapshots:
        metrics = _metrics(snapshot)
        for condition in conditions:
            if condition.metric in metrics and not condition.holds(metrics):
                totals[condition.metric] = totals.get(condition.metric, 0) + interval
    return list(totals.items())


def _detection_time(
    alarms: Sequence[SessionAlarm],
    stages: Sequence[SessionStageHistory],
    closed: frozenset[str],
    snapshots: Sequence[ProcessSnapshot],
) -> int | None:
    """От первой видимой тревоги до момента, когда оператор зафиксировал отклонение."""

    if not alarms or "declare_deviation" not in closed:
        return None
    first_alarm = alarms[0].started_sim_time_ms
    declared = next(
        (entry.exited_sim_time_ms for entry in stages if entry.stage_code == "disturbance_monitoring"),
        None,
    )
    if declared is None:
        return None
    return max(0, declared - first_alarm)


def _reaction_time(alarms: Sequence[SessionAlarm], actions: Sequence[OperatorAction]) -> int | None:
    if not alarms:
        return None
    correct = next(
        (action for action in actions if action.classification == ActionClassification.CORRECT), None
    )
    return None if correct is None else max(0, correct.sim_time_ms - alarms[0].started_sim_time_ms)
