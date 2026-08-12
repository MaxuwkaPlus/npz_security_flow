from fastapi import APIRouter, status

from app.api.deps import SessionRunnerDep, UnitOfWorkDep
from app.api.v1.schemas.actions import ActionResponse, SubmitActionRequest
from app.api.v1.schemas.alarms import AcknowledgeAlarmRequest, AlarmResponse
from app.api.v1.schemas.assessment import (
    NasaTlxRequest,
    NasaTlxResponseSchema,
    SagatCheckpointResponse,
    SagatResultResponse,
    SubmitSagatAnswersRequest,
)
from app.api.v1.schemas.observations import (
    DiagnosisResponse,
    ObservationResponse,
    RecordObservationRequest,
    SubmitDiagnosisRequest,
)
from app.api.v1.schemas.sessions import CreateSessionRequest, SessionCommandRequest, SessionResponse
from app.application.actions import cancel_action, submit_action
from app.application.alarms import acknowledge_alarm, list_alarms
from app.application.assessment import current_checkpoint, submit_answers, submit_nasa_tlx
from app.application.observations import record_observation, submit_diagnosis
from app.application.runtime_config import sagat_policy
from app.application.sessions import create_session, get_session_state, transition_session
from app.core.errors import NotFoundError
from app.domain.sessions import SessionCommand, SessionStatus, is_terminal
from app.infrastructure.db.models import ScenarioVersion

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def post_session(payload: CreateSessionRequest, uow: UnitOfWorkDep) -> SessionResponse:
    state = await create_session(
        uow,
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        scenario_version_id=payload.scenario_version_id,
        level_no=payload.level_no,
        instructor_id=payload.instructor_id,
        random_seed=payload.random_seed,
    )
    return SessionResponse.from_state(state)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, uow: UnitOfWorkDep) -> SessionResponse:
    return SessionResponse.from_state(await get_session_state(uow, session_id))


@router.get("/{session_id}/state", response_model=SessionResponse)
async def get_state(session_id: str, uow: UnitOfWorkDep) -> SessionResponse:
    """Текущее состояние сессии; используется клиентом после разрыва WebSocket."""

    return SessionResponse.from_state(await get_session_state(uow, session_id))


@router.post("/{session_id}/actions", response_model=ActionResponse, status_code=status.HTTP_202_ACCEPTED)
async def post_action(
    session_id: str, payload: SubmitActionRequest, runner: SessionRunnerDep
) -> ActionResponse:
    """Принимает команду оператора. Применяет её ближайший tick симуляции."""

    async with runner.exclusive(session_id) as uow:
        receipt = await submit_action(
            uow,
            session_id,
            request_id=payload.request_id,
            action_type=payload.action_type,
            target_code=payload.target_code,
            value=payload.value,
        )
    return ActionResponse.from_receipt(receipt)


@router.post(
    "/{session_id}/observations",
    response_model=ObservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_observation(
    session_id: str, payload: RecordObservationRequest, runner: SessionRunnerDep
) -> ObservationResponse:
    """Фиксирует явную проверку участка оператором."""

    async with runner.exclusive(session_id) as uow:
        receipt = await record_observation(
            uow,
            session_id,
            request_id=payload.request_id,
            observation_type=payload.observation_type,
            target_code=payload.target_code,
            payload=payload.payload,
        )
    return ObservationResponse.from_receipt(receipt)


@router.post("/{session_id}/diagnoses", response_model=DiagnosisResponse, status_code=status.HTTP_201_CREATED)
async def post_diagnosis(
    session_id: str, payload: SubmitDiagnosisRequest, runner: SessionRunnerDep
) -> DiagnosisResponse:
    async with runner.exclusive(session_id) as uow:
        receipt = await submit_diagnosis(
            uow,
            session_id,
            request_id=payload.request_id,
            affected_area_code=payload.affected_area_code,
            deviation_code=payload.deviation_code,
            suspected_cause_code=payload.suspected_cause_code,
            confidence=payload.confidence,
        )
    return DiagnosisResponse.from_receipt(receipt)


@router.get("/{session_id}/sagat/current", response_model=SagatCheckpointResponse | None)
async def get_current_sagat(session_id: str, uow: UnitOfWorkDep) -> SagatCheckpointResponse | None:
    """Открытая контрольная точка ситуационной осведомлённости или ничего."""

    scenario = await _scenario_of(uow, session_id)
    view = await current_checkpoint(uow, session_id, sagat_policy(scenario))
    return None if view is None else SagatCheckpointResponse.from_view(view)


@router.post("/{session_id}/sagat/{checkpoint_id}/answers", response_model=SagatResultResponse)
async def post_sagat_answers(
    session_id: str,
    checkpoint_id: str,
    payload: SubmitSagatAnswersRequest,
    runner: SessionRunnerDep,
) -> SagatResultResponse:
    async with runner.exclusive(session_id) as uow:
        scenario = await _scenario_of(uow, session_id)
        result = await submit_answers(uow, session_id, checkpoint_id, payload.answers, sagat_policy(scenario))
    return SagatResultResponse.from_result(result)


@router.post(
    "/{session_id}/nasa-tlx", response_model=NasaTlxResponseSchema, status_code=status.HTTP_201_CREATED
)
async def post_nasa_tlx(
    session_id: str, payload: NasaTlxRequest, runner: SessionRunnerDep
) -> NasaTlxResponseSchema:
    """Анкета субъективной нагрузки. На квалификационную оценку не влияет."""

    async with runner.exclusive(session_id) as uow:
        response = await submit_nasa_tlx(uow, session_id, payload.model_dump())
    return NasaTlxResponseSchema.from_model(response)


@router.post("/{session_id}/actions/{action_id}/cancel", response_model=ActionResponse)
async def post_action_cancel(session_id: str, action_id: str, runner: SessionRunnerDep) -> ActionResponse:
    """Отзывает команду, которую ещё не применил очередной шаг симуляции."""

    async with runner.exclusive(session_id) as uow:
        receipt = await cancel_action(uow, session_id, action_id)
    return ActionResponse.from_receipt(receipt)


@router.get("/{session_id}/alarms", response_model=list[AlarmResponse])
async def get_alarms(session_id: str, uow: UnitOfWorkDep) -> list[AlarmResponse]:
    """Активные тревоги сессии; используется клиентом при переподключении."""

    return [AlarmResponse.from_view(view) for view in await list_alarms(uow, session_id)]


@router.post("/{session_id}/alarms/{alarm_id}/acknowledge", response_model=AlarmResponse)
async def post_alarm_acknowledge(
    session_id: str,
    alarm_id: str,
    payload: AcknowledgeAlarmRequest,
    runner: SessionRunnerDep,
) -> AlarmResponse:
    async with runner.exclusive(session_id) as uow:
        training_session = await uow.sessions.get(session_id)
        operator_id = training_session.operator_id if training_session else ""
        view = await acknowledge_alarm(uow, session_id, alarm_id, operator_id=operator_id)
    return AlarmResponse.from_view(view)


@router.post("/{session_id}/start", response_model=SessionResponse)
async def post_start(
    session_id: str, payload: SessionCommandRequest, runner: SessionRunnerDep
) -> SessionResponse:
    return await _transition(runner, session_id, SessionCommand.START, payload)


@router.post("/{session_id}/pause", response_model=SessionResponse)
async def post_pause(
    session_id: str, payload: SessionCommandRequest, runner: SessionRunnerDep
) -> SessionResponse:
    return await _transition(runner, session_id, SessionCommand.PAUSE, payload)


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def post_resume(
    session_id: str, payload: SessionCommandRequest, runner: SessionRunnerDep
) -> SessionResponse:
    return await _transition(runner, session_id, SessionCommand.RESUME, payload)


@router.post("/{session_id}/abort", response_model=SessionResponse)
async def post_abort(
    session_id: str, payload: SessionCommandRequest, runner: SessionRunnerDep
) -> SessionResponse:
    return await _transition(runner, session_id, SessionCommand.ABORT, payload)


async def _transition(
    runner: SessionRunnerDep,
    session_id: str,
    command: SessionCommand,
    payload: SessionCommandRequest,
) -> SessionResponse:
    # Транзакция команды выполняется внутри блокировки сессии и завершается до выхода
    # из блока: тик и команда никогда не пишут состояние одной сессии одновременно.
    async with runner.exclusive(session_id) as uow:
        state = await transition_session(
            uow,
            session_id,
            command,
            request_id=payload.request_id,
            expected_version=payload.expected_version,
        )

    # Симуляцию ведёт фоновая задача. На паузе она остаётся живой, чтобы продолжение
    # не требовало перезапуска, а в терминальном состоянии освобождается сразу.
    if state.status is SessionStatus.RUNNING:
        runner.start(session_id)
    elif is_terminal(state.status):
        await runner.stop(session_id)
    return SessionResponse.from_state(state)


async def _scenario_of(uow: UnitOfWorkDep, session_id: str) -> ScenarioVersion:
    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария сессии не найдена")
    return scenario
