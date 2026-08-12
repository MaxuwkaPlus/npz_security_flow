"""Расчёт оценки прохождения.

Факты собираются только из журнала сессии, поэтому оценку можно пересчитать заново
и получить тот же результат (§18). Пересчёт заменяет прежние score_events.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy import delete, select

from app.application.runtime_config import scoring_config
from app.core.errors import NotFoundError
from app.domain.commands import ActionClassification, ActionStatus
from app.domain.rules import Condition, parse_rule
from app.domain.scoring import SessionFacts, SessionScores, calculate
from app.infrastructure.db.models import (
    ExpectedActionRule,
    NasaTlxResponse,
    OperatorAction,
    ProcessSnapshot,
    SagatAnswer,
    SagatCheckpoint,
    ScenarioStage,
    ScenarioVersion,
    ScoreEventRecord,
    SessionAlarm,
    SessionScore,
    TrainingSession,
)
from app.infrastructure.db.types import utcnow
from app.infrastructure.db.unit_of_work import UnitOfWork

STABLE_MODE_STAGE = "stable_mode"
VERIFY_FLOW_CHECK = "verify_flow"


async def calculate_scores(uow: UnitOfWork, session_id: str) -> SessionScores:
    """Считает и сохраняет оценку. Повторный вызов даёт тот же результат."""

    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария сессии не найдена")

    policy = await scoring_config(uow, training_session.scoring_policy_version_id)
    facts = await collect_facts(uow, training_session, scenario)
    scores = calculate(policy, facts)
    await _store(uow, training_session, scores)
    return scores


async def collect_facts(
    uow: UnitOfWork, training_session: TrainingSession, scenario: ScenarioVersion
) -> SessionFacts:
    actions = await _applied_actions(uow, training_session.id)
    alarms = await _process_alarms(uow, training_session.id)
    snapshots = await _snapshots(uow, training_session.id)
    stability_conditions = await _stable_mode_conditions(uow, scenario.id)
    completed = await _completed_step_weights(uow, training_session, scenario)

    deviation_seconds, critical_ms = _deviation_load(snapshots, stability_conditions, scenario)
    first_alarm = min((alarm.started_sim_time_ms for alarm in alarms), default=None)
    first_correct = min(
        (action.sim_time_ms for action in actions if action.classification == ActionClassification.CORRECT),
        default=None,
    )
    earned, maximum = await _sagat_totals(uow, training_session.id)

    return SessionFacts(
        dangerous_actions=_count(actions, ActionClassification.DANGEROUS),
        out_of_sequence_actions=_count(actions, ActionClassification.OUT_OF_SEQUENCE),
        repeated_actions=_count(actions, ActionClassification.REPEATED),
        unverified_actions=await _unverified_actions(uow, training_session.id, actions),
        unacknowledged_alarms=sum(
            1 for alarm in alarms if alarm.ack_required and alarm.acknowledged_sim_time_ms is None
        ),
        critical_area_ms=critical_ms,
        completed_step_weight=completed[0],
        total_step_weight=completed[1],
        normalized_deviation_seconds=deviation_seconds,
        first_visible_alarm_ms=first_alarm,
        first_correct_action_ms=first_correct,
        recovery_time_ms=_recovery_time(training_session, snapshots, stability_conditions),
        sagat_earned=earned,
        sagat_maximum=maximum,
        raw_nasa_tlx=await _raw_tlx(uow, training_session.id),
    )


async def _store(uow: UnitOfWork, training_session: TrainingSession, scores: SessionScores) -> None:
    await uow.session.execute(
        delete(ScoreEventRecord).where(ScoreEventRecord.session_id == training_session.id)
    )
    for event in scores.events:
        uow.session.add(
            ScoreEventRecord(
                session_id=training_session.id,
                sim_time_ms=training_session.sim_time_ms,
                dimension=event.dimension,
                delta=event.delta,
                rule_code=event.rule_code,
                reason=event.reason,
            )
        )
    existing = await uow.session.get(SessionScore, training_session.id)
    if existing is not None:
        await uow.session.delete(existing)
        await uow.flush()
    uow.session.add(
        SessionScore(
            session_id=training_session.id,
            scoring_policy_version_id=training_session.scoring_policy_version_id,
            safety_score=scores.safety,
            action_correctness_score=scores.action_correctness,
            process_stability_score=scores.process_stability,
            reaction_score=scores.reaction_speed,
            resultiveness_score=scores.resultiveness,
            situation_awareness_score=scores.situation_awareness,
            recovery_time_ms=scores.recovery_time_ms,
            raw_nasa_tlx=scores.raw_nasa_tlx,
            calculated_at=utcnow(),
        )
    )


async def _applied_actions(uow: UnitOfWork, session_id: str) -> Sequence[OperatorAction]:
    query = (
        select(OperatorAction)
        .where(OperatorAction.session_id == session_id, OperatorAction.status == ActionStatus.APPLIED)
        .order_by(OperatorAction.sim_time_ms)
    )
    return (await uow.session.scalars(query)).all()


async def _process_alarms(uow: UnitOfWork, session_id: str) -> Sequence[SessionAlarm]:
    """Второстепенные тревоги — методический шум, в оценку они не входят."""

    query = select(SessionAlarm).where(
        SessionAlarm.session_id == session_id, SessionAlarm.is_nuisance.is_(False)
    )
    return (await uow.session.scalars(query)).all()


async def _snapshots(uow: UnitOfWork, session_id: str) -> Sequence[ProcessSnapshot]:
    query = (
        select(ProcessSnapshot)
        .where(ProcessSnapshot.session_id == session_id)
        .order_by(ProcessSnapshot.sim_time_ms)
    )
    return (await uow.session.scalars(query)).all()


async def _stable_mode_conditions(uow: UnitOfWork, scenario_version_id: str) -> tuple[Condition, ...]:
    """Норма процесса — те же условия, по которым подтверждается устойчивый режим."""

    query = select(ScenarioStage).where(
        ScenarioStage.scenario_version_id == scenario_version_id,
        ScenarioStage.code == STABLE_MODE_STAGE,
    )
    stage = await uow.session.scalar(query)
    return () if stage is None else parse_rule(stage.success_rule_json).conditions


async def _completed_step_weights(
    uow: UnitOfWork, training_session: TrainingSession, scenario: ScenarioVersion
) -> tuple[float, float]:
    from app.application.observations import completed_checks
    from app.application.runtime_config import checks_policy

    query = select(ExpectedActionRule).where(ExpectedActionRule.scenario_version_id == scenario.id)
    steps = (await uow.session.scalars(query)).all()
    closed = await completed_checks(uow, training_session.id, checks_policy(scenario))
    total = sum(step.weight for step in steps)
    earned = sum(step.weight for step in steps if step.action_type in closed)
    return earned, total


async def _unverified_actions(uow: UnitOfWork, session_id: str, actions: Sequence[OperatorAction]) -> int:
    """Действия, требующие проверки результата, для которых её не было."""

    required = [action for action in actions if action.requires_verification]
    if not required:
        return 0
    observations = await uow.sessions.observations(session_id)
    verified_at = [
        observation.sim_time_ms
        for observation in observations
        if observation.observation_type == "verify_result"
    ]
    return sum(1 for action in required if not any(moment >= action.sim_time_ms for moment in verified_at))


async def _sagat_totals(uow: UnitOfWork, session_id: str) -> tuple[float, float]:
    query = (
        select(SagatAnswer)
        .join(SagatCheckpoint, SagatAnswer.checkpoint_id == SagatCheckpoint.id)
        .where(SagatCheckpoint.session_id == session_id)
    )
    answers = (await uow.session.scalars(query)).all()
    return sum(answer.score for answer in answers), float(len(answers))


async def _raw_tlx(uow: UnitOfWork, session_id: str) -> float | None:
    query = select(NasaTlxResponse).where(NasaTlxResponse.session_id == session_id)
    response = await uow.session.scalar(query)
    return None if response is None else response.raw_tlx_score


def _count(actions: Sequence[OperatorAction], classification: str) -> int:
    return sum(1 for action in actions if action.classification == classification)


def _deviation_load(
    snapshots: Sequence[ProcessSnapshot],
    conditions: Sequence[Condition],
    scenario: ScenarioVersion,
) -> tuple[float, int]:
    """Интеграл нормированного отклонения и время в критической области."""

    if not snapshots or not conditions:
        return 0.0, 0
    interval_ms = int(scenario.config_json.get("snapshot_interval_ms", 5_000))
    interval_s = interval_ms / 1000
    deviation_seconds = 0.0
    critical_ms = 0
    for snapshot in snapshots:
        metrics = {**snapshot.visible_values_json, **snapshot.derived_values_json}
        violation = sum(_normalized_violation(condition, metrics) for condition in conditions)
        if violation > 0:
            deviation_seconds += violation * interval_s
            critical_ms += interval_ms
    return round(deviation_seconds, 3), critical_ms


def _normalized_violation(condition: Condition, metrics: Mapping[str, float]) -> float:
    current = metrics.get(condition.metric)
    if current is None or condition.holds(metrics):
        return 0.0
    scale = abs(condition.value) or 1.0
    return abs(current - condition.value) / scale


def _recovery_time(
    training_session: TrainingSession,
    snapshots: Sequence[ProcessSnapshot],
    conditions: Sequence[Condition],
) -> int | None:
    """От начала возмущения до устойчивого возврата обязательных параметров (§16.6)."""

    armed_at: int | None = training_session.runtime_state_json.get("stage", {}).get("disturbance_armed_at_ms")
    if armed_at is None or not conditions:
        return None
    onset = int(armed_at) + int(training_session.hidden_runtime_config_json["disturbance"]["onset_delay_ms"])
    disturbed = False
    for snapshot in snapshots:
        if snapshot.sim_time_ms < onset:
            continue
        metrics = {**snapshot.visible_values_json, **snapshot.derived_values_json}
        in_range = all(condition.holds(metrics) for condition in conditions)
        if not in_range:
            disturbed = True
        elif disturbed:
            return snapshot.sim_time_ms - onset
    return None
