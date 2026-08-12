"""Наблюдения оператора и диагноз.

Наблюдение — это заявление оператора о том, что он проверил участок. Диагноз —
заявление о первопричине. Оба факта неизменяемы и питают обязательные проверки этапов.
Правильность диагноза вычисляется сразу, но во время прохождения не раскрывается.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.application.runtime_config import checks_policy
from app.core.errors import ConflictError, NotFoundError, PreconditionFailedError
from app.domain.commands import ActionStatus
from app.domain.observations import ChecksPolicy, ObservationFact, ObservationType
from app.domain.sessions import SessionStatus, accepts_operator_input
from app.infrastructure.db.models import (
    OperatorAction,
    OperatorDiagnosis,
    OperatorObservation,
    ScenarioVersion,
    TrainingSession,
)
from app.infrastructure.db.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ObservationReceipt:
    id: str
    request_id: str
    session_id: str
    sequence_no: int
    sim_time_ms: int
    observation_type: str
    target_code: str


@dataclass(frozen=True, slots=True)
class DiagnosisReceipt:
    """Приём диагноза. Правильность оператору не сообщается — она попадёт в отчёт."""

    id: str
    request_id: str
    session_id: str
    sequence_no: int
    sim_time_ms: int
    affected_area_code: str
    deviation_code: str
    suspected_cause_code: str


async def record_observation(
    uow: UnitOfWork,
    session_id: str,
    *,
    request_id: str,
    observation_type: str,
    target_code: str,
    payload: Mapping[str, Any] | None = None,
) -> ObservationReceipt:
    existing = await uow.sessions.find_observation(request_id)
    if existing is not None:
        _require_same_session(existing.session_id, session_id, request_id)
        return _observation_receipt(existing)

    training_session = await _running_session(uow, session_id)
    scenario = await _load_scenario(uow, training_session)
    _validate_observation(checks_policy(scenario), observation_type, target_code)

    observation = uow.sessions.add_observation(
        training_session,
        request_id=request_id,
        observation_type=observation_type,
        target_code=target_code,
        payload=dict(payload or {}),
    )
    await uow.flush()
    uow.sessions.append_event(
        training_session,
        "observation_recorded",
        "observation",
        {"observation_type": observation_type, "target_code": target_code},
        aggregate_id=observation.id,
        correlation_id=request_id,
    )
    observation.sequence_no = training_session.last_sequence_no
    return _observation_receipt(observation)


async def submit_diagnosis(
    uow: UnitOfWork,
    session_id: str,
    *,
    request_id: str,
    affected_area_code: str,
    deviation_code: str,
    suspected_cause_code: str,
    confidence: float | None = None,
) -> DiagnosisReceipt:
    existing = await uow.sessions.find_diagnosis(request_id)
    if existing is not None:
        _require_same_session(existing.session_id, session_id, request_id)
        return _diagnosis_receipt(existing)

    training_session = await _running_session(uow, session_id)
    hidden_cause = training_session.hidden_runtime_config_json["disturbance"]["cause_code"]

    diagnosis = uow.sessions.add_diagnosis(
        training_session,
        request_id=request_id,
        affected_area_code=affected_area_code,
        deviation_code=deviation_code,
        suspected_cause_code=suspected_cause_code,
        confidence=confidence,
        is_correct=suspected_cause_code == hidden_cause,
    )
    await uow.flush()
    uow.sessions.append_event(
        training_session,
        "diagnosis_submitted",
        "diagnosis",
        # Правильность в событие не пишется: журнал читает и оператор через WebSocket.
        {"affected_area_code": affected_area_code, "deviation_code": deviation_code},
        aggregate_id=diagnosis.id,
        correlation_id=request_id,
    )
    diagnosis.sequence_no = training_session.last_sequence_no
    return _diagnosis_receipt(diagnosis)


async def completed_checks(uow: UnitOfWork, session_id: str, policy: ChecksPolicy) -> frozenset[str]:
    """Какие обязательные проверки оператор уже закрыл."""

    observations = await uow.sessions.observations(session_id)
    facts = [
        ObservationFact(observation.observation_type, observation.target_code) for observation in observations
    ]
    applied = await _applied_action_types(uow, session_id)
    has_diagnosis = await uow.sessions.has_diagnosis(session_id)
    return policy.completed(facts, applied, has_diagnosis)


async def _applied_action_types(uow: UnitOfWork, session_id: str) -> Sequence[str]:
    query = select(OperatorAction.action_type).where(
        OperatorAction.session_id == session_id,
        OperatorAction.status == ActionStatus.APPLIED,
    )
    return list((await uow.session.scalars(query)).all())


def _validate_observation(policy: ChecksPolicy, observation_type: str, target_code: str) -> None:
    if observation_type not in set(ObservationType):
        raise PreconditionFailedError(
            "UNKNOWN_OBSERVATION_TYPE",
            "Неизвестный тип наблюдения",
            {"observation_type": observation_type},
        )
    allowed = policy.observation_targets(observation_type)
    if allowed and target_code not in allowed:
        raise PreconditionFailedError(
            "OBSERVATION_TARGET_NOT_ALLOWED",
            "Для этого типа наблюдения указан недопустимый участок",
            {"target_code": target_code, "allowed": sorted(allowed)},
        )


async def _running_session(uow: UnitOfWork, session_id: str) -> TrainingSession:
    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    status = SessionStatus(training_session.status)
    if not accepts_operator_input(status):
        raise ConflictError(
            "SESSION_NOT_RUNNING",
            "Наблюдения принимаются только на идущей сессии",
            {"status": status.value},
        )
    return training_session


async def _load_scenario(uow: UnitOfWork, training_session: TrainingSession) -> ScenarioVersion:
    scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария сессии не найдена")
    return scenario


def _require_same_session(stored_session_id: str, session_id: str, request_id: str) -> None:
    if stored_session_id != session_id:
        raise ConflictError(
            "REQUEST_ID_ALREADY_USED",
            "Этот request_id уже использован в другой сессии",
            {"request_id": request_id},
        )


def _observation_receipt(observation: OperatorObservation) -> ObservationReceipt:
    return ObservationReceipt(
        id=observation.id,
        request_id=observation.request_id,
        session_id=observation.session_id,
        sequence_no=observation.sequence_no,
        sim_time_ms=observation.sim_time_ms,
        observation_type=observation.observation_type,
        target_code=observation.target_code,
    )


def _diagnosis_receipt(diagnosis: OperatorDiagnosis) -> DiagnosisReceipt:
    return DiagnosisReceipt(
        id=diagnosis.id,
        request_id=diagnosis.request_id,
        session_id=diagnosis.session_id,
        sequence_no=diagnosis.sequence_no,
        sim_time_ms=diagnosis.sim_time_ms,
        affected_area_code=diagnosis.affected_area_code,
        deviation_code=diagnosis.deviation_code,
        suspected_cause_code=diagnosis.suspected_cause_code,
    )
