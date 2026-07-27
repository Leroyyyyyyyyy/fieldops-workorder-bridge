from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """The one shape every handled error returns.

    `correlation_id` is in the contract from the start even though nothing fills
    it in yet: adding a field later is easy, but clients that already parse these
    responses would have to be told the shape changed.
    """

    code: str
    message: str
    correlation_id: str | None = None


class ApiError(Exception):
    """An error that carries the status code and machine-readable code to return.

    `code` is what a client branches on and is part of the API contract;
    `message` is for a human reading a log or a response body.
    """

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(code=exc.code, message=exc.message).model_dump(mode="json"),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)
