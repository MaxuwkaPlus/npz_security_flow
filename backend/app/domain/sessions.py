"""Жизненный цикл тренировочной сессии (§8.1 технического задания)."""

from dataclasses import dataclass
from enum import StrEnum


class SessionStatus(StrEnum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class SessionCommand(StrEnum):
    CONFIRM_CONFIGURATION = "confirm_configuration"
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    COMPLETE = "complete"
    FAIL = "fail"
    ABORT = "abort"


class SessionOutcome(StrEnum):
    STABILIZED = "stabilized"
    NOT_STABILIZED = "not_stabilized"
    ABORTED = "aborted"


TERMINAL_STATUSES = frozenset({SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.ABORTED})

TRANSITIONS: dict[tuple[SessionStatus, SessionCommand], SessionStatus] = {
    (SessionStatus.CREATED, SessionCommand.CONFIRM_CONFIGURATION): SessionStatus.READY,
    (SessionStatus.READY, SessionCommand.START): SessionStatus.RUNNING,
    (SessionStatus.RUNNING, SessionCommand.PAUSE): SessionStatus.PAUSED,
    (SessionStatus.PAUSED, SessionCommand.RESUME): SessionStatus.RUNNING,
    (SessionStatus.RUNNING, SessionCommand.COMPLETE): SessionStatus.COMPLETED,
    (SessionStatus.RUNNING, SessionCommand.FAIL): SessionStatus.FAILED,
    (SessionStatus.RUNNING, SessionCommand.ABORT): SessionStatus.ABORTED,
    (SessionStatus.PAUSED, SessionCommand.ABORT): SessionStatus.ABORTED,
    (SessionStatus.READY, SessionCommand.ABORT): SessionStatus.ABORTED,
    (SessionStatus.CREATED, SessionCommand.ABORT): SessionStatus.ABORTED,
}

# Состояние, в котором команда уже выполнена: повторный запрос не создаёт второй переход.
ALREADY_APPLIED: dict[SessionCommand, SessionStatus] = {
    SessionCommand.CONFIRM_CONFIGURATION: SessionStatus.READY,
    SessionCommand.START: SessionStatus.RUNNING,
    SessionCommand.PAUSE: SessionStatus.PAUSED,
    SessionCommand.RESUME: SessionStatus.RUNNING,
    SessionCommand.COMPLETE: SessionStatus.COMPLETED,
    SessionCommand.FAIL: SessionStatus.FAILED,
    SessionCommand.ABORT: SessionStatus.ABORTED,
}


class InvalidSessionTransition(Exception):
    def __init__(self, current: SessionStatus, command: SessionCommand) -> None:
        super().__init__(f"Команда {command} недопустима в состоянии {current}")
        self.current = current
        self.command = command


@dataclass(frozen=True, slots=True)
class Transition:
    status: SessionStatus
    changed: bool


def apply_command(current: SessionStatus, command: SessionCommand) -> Transition:
    """Возвращает новое состояние. Повторение уже выполненной команды не меняет состояние."""

    target = TRANSITIONS.get((current, command))
    if target is not None:
        return Transition(status=target, changed=True)
    if ALREADY_APPLIED[command] == current:
        return Transition(status=current, changed=False)
    raise InvalidSessionTransition(current, command)


def is_terminal(status: SessionStatus) -> bool:
    return status in TERMINAL_STATUSES


def accepts_operator_input(status: SessionStatus) -> bool:
    """Команды и наблюдения оператора принимаются только на идущей сессии."""

    return status is SessionStatus.RUNNING
