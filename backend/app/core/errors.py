from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """所有可预期错误的基类。错误码按 <域>_<对象>_<情形> 命名。"""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 400,
        data: dict[str, Any] | None = None,
        retriable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data or {}
        self.retriable = retriable


class NotFound(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 404)


class Conflict(AppError):
    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, 409, data)


class Forbidden(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 403)


class Unauthorized(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 401)


def envelope(
    code: str,
    message: str,
    data: Any = None,
    trace_id: str | None = None,
    retriable: bool = False,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": trace_id,
        "retriable": retriable,
    }


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    return JSONResponse(
        status_code=exc.http_status,
        content=envelope(exc.code, exc.message, exc.data, trace_id, exc.retriable),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    return JSONResponse(
        status_code=500,
        content=envelope("SYS_INTERNAL_ERROR", "服务内部错误", None, trace_id, True),
    )
