from pydantic import BaseModel, ConfigDict


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected, not ignored.

    Pydantic's default is to drop fields it does not recognise. For an API whose
    callers are other systems rather than people, that turns an integration bug
    into silent data loss — a vendor that sends `descriptoin` gets a 201 and a
    work order with no description, and nobody finds out until someone reads the
    data months later. Rejecting the request instead fails the integration on the
    first call, where it is cheap to fix.

    The trade-off is that adding a field to a request schema is now a breaking
    change for a caller sending fields we do not know about, which is the correct
    direction: it is our job to know what our own API accepts.
    """

    model_config = ConfigDict(extra="forbid")
