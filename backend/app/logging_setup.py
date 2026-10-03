"""Structured JSON logs with request id."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
        }
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(json_logs: bool = True) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root.handlers = [handler]


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        rid = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:12]}"
        request.state.request_id = rid
        t0 = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        logging.getLogger("sdc.http").info(
            "%s %s -> %s %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            time.perf_counter() - t0,
            extra={"request_id": rid},
        )
        return response


def install_request_logging(app: FastAPI) -> None:
    app.add_middleware(RequestIdMiddleware)
