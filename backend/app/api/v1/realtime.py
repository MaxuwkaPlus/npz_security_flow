"""WebSocket-канал сессии.

Клиент передаёт последний известный `sequence_no`, получает пропущенные сообщения из
журнала и продолжает слушать поток. Так разрыв связи не приводит к потере событий.
"""

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.application.access import authorize_session_read
from app.application.auth import resolve_principal
from app.application.realtime import messages_after
from app.core.errors import ForbiddenError, NotFoundError, UnauthenticatedError
from app.infrastructure.db.engine import Database
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.realtime.hub import Message, RealtimeHub

router = APIRouter()
logger = logging.getLogger(__name__)

# Коды закрытия из диапазона приложения: 1008 не позволяет клиенту отличить
# «нужен вход» от «нет прав», а поведение фронтенда в этих случаях разное.
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


@router.websocket("/sessions/{session_id}")
async def session_stream(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(description="Токен доступа: заголовки в браузерном WebSocket недоступны"),
    last_sequence_no: int = Query(default=0, ge=0),
) -> None:
    database: Database = websocket.app.state.database
    hub: RealtimeHub = websocket.app.state.realtime_hub

    await websocket.accept()

    # Поток сессии отдаёт обстановку на установке в реальном времени, поэтому доступ к
    # нему проверяется тем же правилом, что и чтение сессии по REST.
    try:
        async with UnitOfWork(database.session_factory) as uow:
            principal = await resolve_principal(uow.session, token)
            await authorize_session_read(uow, principal, session_id)
    except UnauthenticatedError:
        await websocket.close(code=CLOSE_UNAUTHENTICATED, reason="Требуется вход в систему")
        return
    except ForbiddenError:
        logger.warning("realtime_access_denied", extra={"session_id": session_id})
        await websocket.close(code=CLOSE_FORBIDDEN, reason="Недостаточно прав")
        return
    except NotFoundError:
        await websocket.close(code=CLOSE_NOT_FOUND, reason="Сессия не найдена")
        return

    # Подписка оформляется до чтения журнала, иначе сообщения между чтением
    # и подпиской были бы потеряны.
    async with hub.subscribe(session_id) as queue:
        async with UnitOfWork(database.session_factory) as uow:
            history = await messages_after(uow, session_id, last_sequence_no)
        sent_upto = last_sequence_no
        try:
            for message in history:
                await websocket.send_json(message)
                sent_upto = int(message["sequence_no"])
            await _stream(websocket, queue, sent_upto)
        except WebSocketDisconnect:
            logger.info("realtime_client_disconnected")


async def _stream(websocket: WebSocket, queue: asyncio.Queue[Message], sent_upto: int) -> None:
    while True:
        message = await queue.get()
        # Повторы отбрасываются: часть сообщений уже ушла клиенту из журнала.
        if int(message["sequence_no"]) <= sent_upto:
            continue
        await websocket.send_json(message)
        sent_upto = int(message["sequence_no"])
