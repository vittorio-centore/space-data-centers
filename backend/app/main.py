"""Space Data Centers — FastAPI backend (v1 + legacy aliases)."""

from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.routes import build_router
from app.assistant.service import AssistantService
from app.config import load_config
from app.errors import install_error_handlers
from app.logging_setup import install_request_logging, setup_logging
from app.sim.world import SimWorld

config = load_config()
setup_logging(config.log_json)
world = SimWorld(config)
assistant = AssistantService()


def get_world() -> SimWorld:
    return world


app = FastAPI(
    title="Space Data Centers",
    version="1.0.0",
    description="Job-placement planner for Earth and orbital data centers. "
    "Canonical API is /api/v1. Planner is deterministic.",
    openapi_tags=[
        {"name": "v1", "description": "Versioned product API"},
    ],
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_request_logging(app)
install_error_handlers(app)

v1 = build_router(get_world, include_in_schema=True)
v1.tags = ["v1"]
app.include_router(v1, prefix="/api/v1")
# Hidden aliases so the existing dashboard proxy (`/api` → strip → root) keeps working.
app.include_router(build_router(get_world, include_in_schema=False), prefix="")

static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/operator", StaticFiles(directory=static_dir, html=True), name="operator")


class AskBody(BaseModel):
    text: str
    source: str = "text"
    speak: bool = False


@app.get("/assistant/status")
def assistant_status():
    return assistant.status()


@app.post("/assistant/ask")
async def assistant_ask(body: AskBody):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    source = body.source if body.source in ("text", "voice") else "text"
    return await assistant.ask(world, text, source=source, speak=body.speak)


@app.post("/assistant/voice")
async def assistant_voice(file: UploadFile = File(...), speak: bool = True):
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty audio")
    return await assistant.voice(
        world,
        data,
        file.filename or "clip.webm",
        file.content_type or "application/octet-stream",
        speak=speak,
    )


def create_app() -> FastAPI:
    return app
