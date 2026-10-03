"""Simple service API-key auth. No user accounts.

Local default: if ``API_KEY`` is unset or empty, the API is open.
Set ``API_KEY`` to require ``X-API-Key`` or ``Authorization: Bearer``.
Documented demo value: ``sdc-demo``.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import error_body

DEMO_API_KEY = "sdc-demo"

OPEN_EXACT = {
    "/health",
    "/api/v1/health",
    "/ready",
    "/api/v1/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}
OPEN_PREFIXES = ("/docs", "/redoc", "/operator")


def configured_api_key() -> str:
    return (os.environ.get("API_KEY") or "").strip()


def auth_required() -> bool:
    return bool(configured_api_key())


def extract_key(headers: dict[str, str], query_key: str = "") -> str:
    if query_key:
        return query_key.strip()
    raw_key = headers.get("x-api-key") or headers.get("X-API-Key") or ""
    if raw_key:
        return raw_key.strip()
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def key_ok(provided: str) -> bool:
    expected = configured_api_key()
    if not expected:
        return True
    return provided == expected


def path_is_open(path: str) -> bool:
    if path in OPEN_EXACT:
        return True
    return any(path == p or path.startswith(p + "/") for p in OPEN_PREFIXES)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        if request.method == "OPTIONS":
            return await call_next(request)
        if not auth_required() or path_is_open(request.url.path):
            return await call_next(request)
        provided = extract_key({k: v for k, v in request.headers.items()})
        if key_ok(provided):
            return await call_next(request)
        return JSONResponse(
            status_code=401,
            content=error_body("unauthorized", "missing or invalid API key", 401),
            headers={"WWW-Authenticate": "Bearer"},
        )


def install_api_key_auth(app: FastAPI) -> None:
    app.add_middleware(ApiKeyMiddleware)


def authorize_websocket(ws: WebSocket) -> bool:
    if not auth_required():
        return True
    q = ws.query_params.get("api_key") or ws.query_params.get("access_token") or ""
    provided = extract_key({k: v for k, v in ws.headers.items()}, q)
    return key_ok(provided)
