import hashlib
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.commands import ActionStatus
from app.infrastructure.db.models import (
    CommandRequest,
    OperatorAction,
    OperatorDiagnosis,
    OperatorObservation,
    ProcessSnapshot,
    SessionAlarm,
    SessionEvent,
    SessionStageHistory,
    TrainingSession,
)


def state_hash(values: dict[str, Any]) -> str:
    """Хеш снимка для проверки воспроизводимости replay (§18)."""

    payload = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SessionRepository:
    """Доступ к агрегату прохождения: сессия, её события, снимки и история этапов."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, training_session: TrainingSession) -> None:
        self._session.add(training_session)

    async def get(self, session_id: str) -> TrainingSession | None:
        training_session: TrainingSession | None = await self._session.get(TrainingSession, session_id)
        return training_session

    def append_event(
        self,
        training_session: TrainingSession,
        event_type: str,
        aggregate_type: str,
        payload: dict[str, Any],
        *,
        aggregate_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> SessionEvent:
        """Присваивает событию следующий номер из счётчика сессии."""

        training_session.last_sequence_no += 1
        event = SessionEvent(
            session_id=training_session.id,
            sequence_no=training_session.last_sequence_no,
            sim_time_ms=training_session.sim_time_ms,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id or training_session.id,
            payload_json=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        self._session.add(event)
        return event

    def add_snapshot(
        self,
        training_session: TrainingSession,
        visible_values: dict[str, Any],
        derived_values: dict[str, Any],
        internal_state: dict[str, Any],
    ) -> ProcessSnapshot:
        training_session.last_sequence_no += 1
        snapshot = ProcessSnapshot(
            session_id=training_session.id,
            sequence_no=training_session.last_sequence_no,
            sim_time_ms=training_session.sim_time_ms,
            stage_code=training_session.current_stage_code,
            visible_values_json=visible_values,
            derived_values_json=derived_values,
            internal_state_json=internal_state,
            state_hash=state_hash({"visible": visible_values, "internal": internal_state}),
        )
        self._session.add(snapshot)
        return snapshot

    async def latest_snapshot(self, session_id: str) -> ProcessSnapshot | None:
        query = (
            select(ProcessSnapshot)
            .where(ProcessSnapshot.session_id == session_id)
            .order_by(ProcessSnapshot.sim_time_ms.desc())
            .limit(1)
        )
        snapshot: ProcessSnapshot | None = await self._session.scalar(query)
        return snapshot

    async def snapshots_after(self, session_id: str, after_sequence_no: int) -> Sequence[ProcessSnapshot]:
        query = (
            select(ProcessSnapshot)
            .where(
                ProcessSnapshot.session_id == session_id,
                ProcessSnapshot.sequence_no > after_sequence_no,
            )
            .order_by(ProcessSnapshot.sequence_no)
        )
        return (await self._session.scalars(query)).all()

    async def events_after(self, session_id: str, after_sequence_no: int) -> Sequence[SessionEvent]:
        query = (
            select(SessionEvent)
            .where(SessionEvent.session_id == session_id, SessionEvent.sequence_no > after_sequence_no)
            .order_by(SessionEvent.sequence_no)
        )
        return (await self._session.scalars(query)).all()

    def open_stage(self, training_session: TrainingSession, stage_code: str) -> SessionStageHistory:
        entry = SessionStageHistory(
            session_id=training_session.id,
            stage_code=stage_code,
            entered_sim_time_ms=training_session.sim_time_ms,
        )
        self._session.add(entry)
        return entry

    async def current_stage_entry(self, session_id: str) -> SessionStageHistory | None:
        query = (
            select(SessionStageHistory)
            .where(
                SessionStageHistory.session_id == session_id,
                SessionStageHistory.exited_sim_time_ms.is_(None),
            )
            .order_by(SessionStageHistory.entered_sim_time_ms.desc())
            .limit(1)
        )
        entry: SessionStageHistory | None = await self._session.scalar(query)
        return entry

    def add_action(
        self,
        training_session: TrainingSession,
        *,
        request_id: str,
        action_type: str,
        target_code: str,
        requested_value: dict[str, Any],
        status: str,
        rejection_reason: str | None,
    ) -> OperatorAction:
        action = OperatorAction(
            request_id=request_id,
            session_id=training_session.id,
            sequence_no=training_session.last_sequence_no,
            sim_time_ms=training_session.sim_time_ms,
            action_type=action_type,
            target_code=target_code,
            requested_value_json=requested_value,
            before_state_json={},
            after_state_json={},
            status=status,
            rejection_reason=rejection_reason,
        )
        self._session.add(action)
        return action

    async def find_action(self, request_id: str) -> OperatorAction | None:
        query = select(OperatorAction).where(OperatorAction.request_id == request_id)
        action: OperatorAction | None = await self._session.scalar(query)
        return action

    async def get_action(self, action_id: str) -> OperatorAction | None:
        action: OperatorAction | None = await self._session.get(OperatorAction, action_id)
        return action

    async def accepted_actions(self, session_id: str) -> Sequence[OperatorAction]:
        """Принятые, но ещё не применённые команды в порядке поступления."""

        query = (
            select(OperatorAction)
            .where(
                OperatorAction.session_id == session_id,
                OperatorAction.status == ActionStatus.ACCEPTED,
            )
            .order_by(OperatorAction.sequence_no)
        )
        return (await self._session.scalars(query)).all()

    def add_observation(
        self,
        training_session: TrainingSession,
        *,
        request_id: str,
        observation_type: str,
        target_code: str,
        payload: dict[str, Any],
    ) -> OperatorObservation:
        observation = OperatorObservation(
            request_id=request_id,
            session_id=training_session.id,
            sequence_no=training_session.last_sequence_no,
            sim_time_ms=training_session.sim_time_ms,
            observation_type=observation_type,
            target_code=target_code,
            payload_json=payload,
        )
        self._session.add(observation)
        return observation

    async def find_observation(self, request_id: str) -> OperatorObservation | None:
        query = select(OperatorObservation).where(OperatorObservation.request_id == request_id)
        observation: OperatorObservation | None = await self._session.scalar(query)
        return observation

    async def observations(self, session_id: str) -> Sequence[OperatorObservation]:
        query = (
            select(OperatorObservation)
            .where(OperatorObservation.session_id == session_id)
            .order_by(OperatorObservation.sim_time_ms)
        )
        return (await self._session.scalars(query)).all()

    def add_diagnosis(
        self,
        training_session: TrainingSession,
        *,
        request_id: str,
        affected_area_code: str,
        deviation_code: str,
        suspected_cause_code: str,
        confidence: float | None,
        is_correct: bool,
    ) -> OperatorDiagnosis:
        diagnosis = OperatorDiagnosis(
            request_id=request_id,
            session_id=training_session.id,
            sequence_no=training_session.last_sequence_no,
            sim_time_ms=training_session.sim_time_ms,
            affected_area_code=affected_area_code,
            deviation_code=deviation_code,
            suspected_cause_code=suspected_cause_code,
            confidence=confidence,
            is_correct=is_correct,
        )
        self._session.add(diagnosis)
        return diagnosis

    async def find_diagnosis(self, request_id: str) -> OperatorDiagnosis | None:
        query = select(OperatorDiagnosis).where(OperatorDiagnosis.request_id == request_id)
        diagnosis: OperatorDiagnosis | None = await self._session.scalar(query)
        return diagnosis

    async def diagnoses(self, session_id: str) -> Sequence[OperatorDiagnosis]:
        query = (
            select(OperatorDiagnosis)
            .where(OperatorDiagnosis.session_id == session_id)
            .order_by(OperatorDiagnosis.sim_time_ms)
        )
        return (await self._session.scalars(query)).all()

    async def has_diagnosis(self, session_id: str) -> bool:
        query = select(OperatorDiagnosis.id).where(OperatorDiagnosis.session_id == session_id).limit(1)
        return await self._session.scalar(query) is not None

    async def active_alarms(self, session_id: str) -> Sequence[SessionAlarm]:
        query = (
            select(SessionAlarm)
            .where(SessionAlarm.session_id == session_id, SessionAlarm.cleared_sim_time_ms.is_(None))
            .order_by(SessionAlarm.started_sim_time_ms)
        )
        return (await self._session.scalars(query)).all()

    async def get_alarm(self, alarm_id: str) -> SessionAlarm | None:
        alarm: SessionAlarm | None = await self._session.get(SessionAlarm, alarm_id)
        return alarm

    def raise_alarm(
        self,
        training_session: TrainingSession,
        *,
        alarm_rule_id: str | None,
        alarm_code: str,
        level: str,
        equipment_code: str,
        message: str,
        ack_required: bool,
        is_nuisance: bool = False,
    ) -> SessionAlarm:
        alarm = SessionAlarm(
            session_id=training_session.id,
            alarm_rule_id=alarm_rule_id,
            alarm_code=alarm_code,
            level=level,
            equipment_code=equipment_code,
            message=message,
            ack_required=ack_required,
            is_nuisance=is_nuisance,
            started_sim_time_ms=training_session.sim_time_ms,
        )
        self._session.add(alarm)
        return alarm

    async def find_command_request(self, request_id: str) -> CommandRequest | None:
        request: CommandRequest | None = await self._session.get(CommandRequest, request_id)
        return request

    def add_command_request(
        self, request_id: str, session_id: str, command: str, response: dict[str, Any]
    ) -> None:
        self._session.add(
            CommandRequest(
                request_id=request_id, session_id=session_id, command=command, response_json=response
            )
        )
