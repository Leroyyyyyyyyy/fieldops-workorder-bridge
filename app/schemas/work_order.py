from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.domain.work_order_status import Priority
from app.schemas.base import RequestModel

#: Free text from a caller. Stripped first, so a field of spaces is rejected as
#: the empty value it is rather than stored as meaningless whitespace.
FreeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class WorkOrderCreate(RequestModel):
    """The client-supplied half of a work order.

    `status` and `version` are absent on purpose: a work order always starts at
    NEW, and status only ever changes through the explicit command endpoints. If
    a caller could set it here, the state machine would have a way around itself.
    Supplying them is rejected rather than ignored — see `RequestModel`.
    """

    asset_id: UUID
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: FreeText | None = None
    priority: Priority


class AssignRequest(RequestModel):
    """`assignee_id` is not validated against a users table because there is not
    one yet; authentication introduces it, along with the foreign key."""

    assignee_id: UUID


class ReassignRequest(RequestModel):
    """Hand the work to someone else.

    No reason field yet: a reason belongs on the audit event, not on the row,
    because a work order can be reassigned repeatedly and a column would only
    ever hold the latest one. It arrives with the audit trail.
    """

    assignee_id: UUID


class StartRequest(RequestModel):
    """Deliberately empty.

    Starting work adds no facts, so there is nothing to send — but the endpoint
    still takes a body, for two reasons. Without one FastAPI never looks at the
    request body at all, so `extra="forbid"` would not apply and `start` would be
    the one command that silently ignores a misspelled or unknown field. And when
    the commands grow a field they all need, adding it here is then a new field on
    an existing body rather than a body appearing where there was none.
    """


class CompleteRequest(RequestModel):
    """A resolution is required: a completed work order that does not say what was
    done is not an audit trail, it is a status flag."""

    resolution: FreeText


class CancelRequest(RequestModel):
    """Same reasoning as `CompleteRequest` — cancelling without a reason loses the
    only information anyone will want later."""

    reason: FreeText


class WorkOrderRead(BaseModel):
    """What the API returns. Built from the ORM object via `from_attributes`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    title: str
    description: str | None
    # `str`, not the enum: the CHECK constraint keeps new rows inside the value
    # domain, but a read should still surface a row rather than fail on it if one
    # ever gets in another way.
    priority: str
    status: str
    version: int
    assignee_id: UUID | None
    resolution: str | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime
