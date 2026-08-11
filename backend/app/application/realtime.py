"""Проекции состояния сессии для WebSocket.

Сообщения собираются из уже зафиксированных фактов: событий журнала и снимков.
`internal_state_json` снимка сюда не попадает — оператор не должен видеть скрытую
интенсивность возмущения и целевую ветвь.
"""

from typing import Any

from app.infrastructure.db.models import ProcessSnapshot, SessionEvent
from app.infrastructure.db.unit_of_work import UnitOfWork

SCHEMA_VERSION = 1

SESSION_STATE_EVENTS = frozenset(
    {
        "session_created",
        "session_ready",
        "session_started",
        "session_paused",
        "session_resumed",
        "session_failed",
        "session_aborted",
    }
)
MESSAGE_TYPES = {
    "session_completed": "session_completed",
    "stage_changed": "stage_changed",
    "alarm_raised": "alarm_raised",
    "alarm_cleared": "alarm_updated",
    "alarm_acknowledged": "alarm_updated",
    "action_accepted": "action_status_changed",
    "action_rejected": "action_status_changed",
    "action_applied": "action_status_changed",
}


def event_message(event: SessionEvent) -> dict[str, Any]:
    message_type = MESSAGE_TYPES.get(event.event_type)
    if message_type is None:
        message_type = "session_state" if event.event_type in SESSION_STATE_EVENTS else "session_event"
    return _envelope(
        message_type,
        session_id=event.session_id,
        sequence_no=event.sequence_no,
        sim_time_ms=event.sim_time_ms,
        payload={"event_type": event.event_type, **event.payload_json},
    )


def snapshot_message(snapshot: ProcessSnapshot) -> dict[str, Any]:
    return _envelope(
        "process_snapshot",
        session_id=snapshot.session_id,
        sequence_no=snapshot.sequence_no,
        sim_time_ms=snapshot.sim_time_ms,
        payload={
            "stage_code": snapshot.stage_code,
            "values": snapshot.visible_values_json,
            "derived": snapshot.derived_values_json,
        },
    )


async def messages_after(uow: UnitOfWork, session_id: str, after_sequence_no: int) -> list[dict[str, Any]]:
    """События и снимки строго после указанного номера, в порядке возрастания."""

    events = await uow.sessions.events_after(session_id, after_sequence_no)
    snapshots = await uow.sessions.snapshots_after(session_id, after_sequence_no)
    messages = [event_message(event) for event in events]
    messages.extend(snapshot_message(snapshot) for snapshot in snapshots)
    return sorted(messages, key=lambda message: int(message["sequence_no"]))


def _envelope(
    message_type: str, *, session_id: str, sequence_no: int, sim_time_ms: int, payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": message_type,
        "session_id": session_id,
        "sequence_no": sequence_no,
        "sim_time_ms": sim_time_ms,
        "payload": payload,
    }
