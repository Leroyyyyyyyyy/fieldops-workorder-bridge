"""The work order state machine.

Deliberately free of FastAPI, SQLAlchemy and the database: the rules are a pure
function of (command, current status), so the full transition matrix can be
tested without a request or a connection. Everything that talks to the outside
world imports from here rather than restating the rules.
"""

from enum import StrEnum
from typing import NamedTuple


class WorkOrderStatus(StrEnum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Priority(StrEnum):
    """How urgent the work is. Set by the caller at creation and not changed after."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Command(StrEnum):
    """The four things that can be done to a work order.

    There is no generic "set status" command on purpose: each command names a
    real event, carries its own required data, and has its own preconditions.
    """

    ASSIGN = "ASSIGN"
    START = "START"
    COMPLETE = "COMPLETE"
    CANCEL = "CANCEL"


class Transition(NamedTuple):
    allowed_from: frozenset[WorkOrderStatus]
    to: WorkOrderStatus


#: The whole state machine. `NEW -> ASSIGNED -> IN_PROGRESS -> COMPLETED`, with
#: cancellation available from any non-terminal status.
#:
#: Reassignment (ASSIGN from ASSIGNED) is not allowed: the contract lists exactly
#: one transition into ASSIGNED, and quietly widening it here would make the
#: diagram and the code disagree. If reassignment is needed it should be its own
#: command, with its own audit event.
TRANSITIONS: dict[Command, Transition] = {
    Command.ASSIGN: Transition(frozenset({WorkOrderStatus.NEW}), WorkOrderStatus.ASSIGNED),
    Command.START: Transition(frozenset({WorkOrderStatus.ASSIGNED}), WorkOrderStatus.IN_PROGRESS),
    Command.COMPLETE: Transition(
        frozenset({WorkOrderStatus.IN_PROGRESS}), WorkOrderStatus.COMPLETED
    ),
    Command.CANCEL: Transition(
        frozenset({WorkOrderStatus.NEW, WorkOrderStatus.ASSIGNED, WorkOrderStatus.IN_PROGRESS}),
        WorkOrderStatus.CANCELLED,
    ),
}

TERMINAL_STATUSES = frozenset({WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED})


class InvalidTransition(Exception):
    """Raised when a command is not legal from the work order's current status."""

    def __init__(self, command: Command, current: WorkOrderStatus) -> None:
        super().__init__(f"Cannot {command} a work order in status {current}.")
        self.command = command
        self.current = current


def is_allowed(command: Command, current: WorkOrderStatus) -> bool:
    return current in TRANSITIONS[command].allowed_from


def next_status(command: Command, current: WorkOrderStatus) -> WorkOrderStatus:
    """The status after `command`, or raise `InvalidTransition` if it is illegal."""
    if not is_allowed(command, current):
        raise InvalidTransition(command, current)
    return TRANSITIONS[command].to
