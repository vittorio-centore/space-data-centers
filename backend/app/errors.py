"""Uniform API error envelope."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_body(code: str, detail: str, status: int, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": True, "code": code, "detail": detail, "status": status}
    if extra:
        body.update(extra)
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body("http_error", str(exc.detail), exc.status_code),
        )

    @app.exception_handler(RequestValidationError)
    async def valid_exc(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "request failed validation", 422, {"errors": exc.errors()}),
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "internal server error", 500),
        )
