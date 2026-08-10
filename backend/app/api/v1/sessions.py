from fastapi import APIRouter, status

from app.api.deps import UnitOfWorkDep
from app.api.v1.schemas.sessions import CreateSessionRequest, SessionCommandRequest, SessionResponse
from app.application.sessions import create_session, get_session_state, transition_session
from app.domain.sessions import SessionCommand

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


@router.post("/{session_id}/start", response_model=SessionResponse)
async def post_start(session_id: str, payload: SessionCommandRequest, uow: UnitOfWorkDep) -> SessionResponse:
    return await _transition(uow, session_id, SessionCommand.START, payload)


@router.post("/{session_id}/pause", response_model=SessionResponse)
async def post_pause(session_id: str, payload: SessionCommandRequest, uow: UnitOfWorkDep) -> SessionResponse:
    return await _transition(uow, session_id, SessionCommand.PAUSE, payload)


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def post_resume(session_id: str, payload: SessionCommandRequest, uow: UnitOfWorkDep) -> SessionResponse:
    return await _transition(uow, session_id, SessionCommand.RESUME, payload)


@router.post("/{session_id}/abort", response_model=SessionResponse)
async def post_abort(session_id: str, payload: SessionCommandRequest, uow: UnitOfWorkDep) -> SessionResponse:
    return await _transition(uow, session_id, SessionCommand.ABORT, payload)


async def _transition(
    uow: UnitOfWorkDep, session_id: str, command: SessionCommand, payload: SessionCommandRequest
) -> SessionResponse:
    state = await transition_session(
        uow,
        session_id,
        command,
        request_id=payload.request_id,
        expected_version=payload.expected_version,
    )
    return SessionResponse.from_state(state)
