import pytest

from app.domain.sessions import (
    InvalidSessionTransition,
    SessionCommand,
    SessionStatus,
    accepts_operator_input,
    apply_command,
    is_terminal,
)


def test_full_happy_path() -> None:
    status = SessionStatus.CREATED
    for command in (
        SessionCommand.CONFIRM_CONFIGURATION,
        SessionCommand.START,
        SessionCommand.PAUSE,
        SessionCommand.RESUME,
        SessionCommand.COMPLETE,
    ):
        status = apply_command(status, command).status

    assert status is SessionStatus.COMPLETED
    assert is_terminal(status)


@pytest.mark.parametrize(
    ("status", "command"),
    [
        (SessionStatus.RUNNING, SessionCommand.START),
        (SessionStatus.RUNNING, SessionCommand.RESUME),
        (SessionStatus.PAUSED, SessionCommand.PAUSE),
        (SessionStatus.ABORTED, SessionCommand.ABORT),
    ],
)
def test_repeated_command_does_not_create_second_transition(
    status: SessionStatus, command: SessionCommand
) -> None:
    transition = apply_command(status, command)

    assert transition.status is status
    assert transition.changed is False


@pytest.mark.parametrize(
    ("status", "command"),
    [
        (SessionStatus.CREATED, SessionCommand.START),
        (SessionStatus.READY, SessionCommand.PAUSE),
        (SessionStatus.COMPLETED, SessionCommand.ABORT),
        (SessionStatus.ABORTED, SessionCommand.RESUME),
    ],
)
def test_forbidden_transitions_are_rejected(status: SessionStatus, command: SessionCommand) -> None:
    with pytest.raises(InvalidSessionTransition):
        apply_command(status, command)


def test_terminal_session_accepts_no_operator_input() -> None:
    assert accepts_operator_input(SessionStatus.RUNNING)
    assert not accepts_operator_input(SessionStatus.PAUSED)
    assert not accepts_operator_input(SessionStatus.COMPLETED)
