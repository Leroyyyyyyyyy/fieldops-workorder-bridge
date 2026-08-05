"""The full transition matrix: every command against every status.

No database and no HTTP — these are the rules themselves. The table below is
written out by hand rather than derived from TRANSITIONS, so that a change to
the state machine has to be made twice, deliberately, instead of silently
agreeing with itself.
"""

import pytest

from app.domain.work_order_status import (
    Command,
    InvalidTransition,
    WorkOrderStatus,
    is_allowed,
    next_status,
)

NEW = WorkOrderStatus.NEW
ASSIGNED = WorkOrderStatus.ASSIGNED
IN_PROGRESS = WorkOrderStatus.IN_PROGRESS
COMPLETED = WorkOrderStatus.COMPLETED
CANCELLED = WorkOrderStatus.CANCELLED

#: (command, status) -> resulting status, or None if the command is illegal there.
MATRIX: dict[tuple[Command, WorkOrderStatus], WorkOrderStatus | None] = {
    (Command.ASSIGN, NEW): ASSIGNED,
    (Command.ASSIGN, ASSIGNED): None,
    (Command.ASSIGN, IN_PROGRESS): None,
    (Command.ASSIGN, COMPLETED): None,
    (Command.ASSIGN, CANCELLED): None,
    # Reassignment returns the work order to ASSIGNED: the new assignee has not
    # started it, whatever the previous one had done.
    (Command.REASSIGN, NEW): None,
    (Command.REASSIGN, ASSIGNED): ASSIGNED,
    (Command.REASSIGN, IN_PROGRESS): ASSIGNED,
    (Command.REASSIGN, COMPLETED): None,
    (Command.REASSIGN, CANCELLED): None,
    (Command.START, NEW): None,
    (Command.START, ASSIGNED): IN_PROGRESS,
    (Command.START, IN_PROGRESS): None,
    (Command.START, COMPLETED): None,
    (Command.START, CANCELLED): None,
    (Command.COMPLETE, NEW): None,
    (Command.COMPLETE, ASSIGNED): None,
    (Command.COMPLETE, IN_PROGRESS): COMPLETED,
    (Command.COMPLETE, COMPLETED): None,
    (Command.COMPLETE, CANCELLED): None,
    (Command.CANCEL, NEW): CANCELLED,
    (Command.CANCEL, ASSIGNED): CANCELLED,
    (Command.CANCEL, IN_PROGRESS): CANCELLED,
    (Command.CANCEL, COMPLETED): None,
    (Command.CANCEL, CANCELLED): None,
}


def test_matrix_covers_every_command_and_status() -> None:
    """A new command or status must not slip through untested."""
    assert set(MATRIX) == {(command, status) for command in Command for status in WorkOrderStatus}


@pytest.mark.parametrize(("command", "current", "expected"), [(*k, v) for k, v in MATRIX.items()])
def test_transition(
    command: Command, current: WorkOrderStatus, expected: WorkOrderStatus | None
) -> None:
    if expected is None:
        assert not is_allowed(command, current)
        with pytest.raises(InvalidTransition):
            next_status(command, current)
    else:
        assert is_allowed(command, current)
        assert next_status(command, current) == expected


def test_terminal_statuses_accept_no_command() -> None:
    """No reopen: once COMPLETED or CANCELLED, nothing moves the work order."""
    for status in (COMPLETED, CANCELLED):
        for command in Command:
            assert not is_allowed(command, status)


def test_invalid_transition_names_the_command_and_status() -> None:
    error = InvalidTransition(Command.START, COMPLETED)

    assert error.command is Command.START
    assert error.current is COMPLETED
    assert "START" in str(error)
    assert "COMPLETED" in str(error)


def test_every_command_has_a_matching_event_type() -> None:
    """A new command must not be able to exist without a way to record it."""
    from app.domain.work_order_status import WorkOrderEventType

    assert {command.value for command in Command} <= {
        event_type.value for event_type in WorkOrderEventType
    }
