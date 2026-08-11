"""WebSocket-канал сессии.

Клиент передаёт последний известный `sequence_no`, получает пропущенные сообщения из
журнала и продолжает слушать поток. Так разрыв связи не приводит к потере событий.
"""

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.application.realtime import messages_after
from app.infrastructure.db.engine import Database
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.realtime.hub import Message, RealtimeHub

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/sessions/{session_id}")
async def session_stream(
    websocket: WebSocket,
    session_id: str,
    last_sequence_no: int = Query(default=0, ge=0),
) -> None:
    database: Database = websocket.app.state.database
    hub: RealtimeHub = websocket.app.state.realtime_hub

    await websocket.accept()
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
