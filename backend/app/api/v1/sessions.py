from fastapi import APIRouter, status

from app.api.deps import SessionRunnerDep, UnitOfWorkDep
from app.api.v1.schemas.actions import ActionResponse, SubmitActionRequest
from app.api.v1.schemas.alarms import AcknowledgeAlarmRequest, AlarmResponse
from app.api.v1.schemas.sessions import CreateSessionRequest, SessionCommandRequest, SessionResponse
from app.application.actions import submit_action
from app.application.alarms import acknowledge_alarm, list_alarms
from app.application.sessions import create_session, get_session_state, transition_session
from app.domain.sessions import SessionCommand, SessionStatus, is_terminal

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
