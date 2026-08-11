"""Шина сообщений реального времени в пределах одного экземпляра приложения."""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

Message = dict[str, Any]


class RealtimeHub:
    """Публикация сообщений сессии подписанным WebSocket-клиентам."""

    def __init__(self, queue_size: int = 200) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, set[asyncio.Queue[Message]]] = {}

    @asynccontextmanager
    async def subscribe(self, session_id: str) -> AsyncIterator[asyncio.Queue[Message]]:
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(session_id, set()).add(queue)
        try:
            yield queue
        finally:
            listeners = self._subscribers.get(session_id, set())
            listeners.discard(queue)
            if not listeners:
                self._subscribers.pop(session_id, None)

    def publish(self, session_id: str, messages: Sequence[Message]) -> None:
        for queue in self._subscribers.get(session_id, set()):
            for message in messages:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    # Медленный клиент обнаружит пропуск по sequence_no и запросит состояние REST-ом.
                    logger.warning("realtime_queue_overflow", extra={"context": {"session_id": session_id}})

    def has_subscribers(self, session_id: str) -> bool:
        return bool(self._subscribers.get(session_id))
