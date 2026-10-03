"""Assistant orchestration: live tools are validated; offline is labelled."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.assistant.grok import GrokSettings
from app.assistant.service import OFFLINE_NOTE, AssistantService


class FakeWorld:
    def __init__(self) -> None:
        self.link_by_id = {"link-gs-ashburn-orbital-iss-cheap": object()}
        self.jobs = {}
        self.station_by_id = {"gs-ashburn": object(), "gs-madrid": object()}
        self.node_by_id = {"earth-us-east": object()}
        self.links = []
        self.plans = {}
        self.settings = SimpleNamespace(t=12.0, playing=False, speed=1, disrupted_links={})
        self.submitted = []
        self.played = False
        self.paused = False

    async def play(self):
        self.played = True
        self.settings.playing = True

    async def pause(self):
        self.paused = True
        self.settings.playing = False

    async def submit_job(self, body):
        self.submitted.append(body)
        return {
            "job": {"id": "job-00000001", "state": "planned", "assigned_node_id": "earth-us-east"},
            "plan": {"estimated_cost": 1.5, "estimated_completion": 40},
        }

    async def submit_thesis(self, preset):
        return await self.submit_job({"preset": preset})

    def clear_disruption(self, lid):
        self.settings.disrupted_links.pop(lid, None)

    def disrupt_link(self, lid, down=True, bandwidth_factor=None, until=None):
        self.settings.disrupted_links[lid] = {"down": down}
        return {"link_id": lid, "disruption": {"down": down}}

    async def emit(self, *_a, **_k):
        return None


SETTINGS = GrokSettings(api_key="xai-test", base="https://api.x.ai/v1")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


@pytest.mark.asyncio
async def test_offline_status_and_note(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    svc = AssistantService()
    st = svc.status()
    assert st["mode"] == "offline"
    assert st["note"] == OFFLINE_NOTE
    assert st["planner"] == "deterministic"
    out = await svc.ask(FakeWorld(), "pause")
    assert out["mode"] == "offline"
    assert out["parser"] == "offline"
    assert out["reply"].startswith(OFFLINE_NOTE)
    assert out["actions"][0]["tool"] == "pause"


@pytest.mark.asyncio
async def test_live_pause_validates_and_followup():
    world = FakeWorld()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("previous_response_id") == "resp_1":
            return httpx.Response(
                200,
                json={
                    "output": [
                        {"type": "message", "content": [{"text": "Clock paused."}]}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "pause",
                        "arguments": "{}",
                        "call_id": "c1",
                    }
                ],
            },
        )

    async with _client(handler) as client:
        svc = AssistantService(client=client, settings=SETTINGS)
        out = await svc.ask(world, "pause now")
    assert out["mode"] == "live"
    assert out["parser"] == "grok"
    assert world.paused is True
    assert out["actions"][0]["tool"] == "pause"
    assert "Clock paused." in out["reply"]
    assert OFFLINE_NOTE not in out["reply"]


@pytest.mark.asyncio
async def test_live_rejects_planner_override_no_submit():
    world = FakeWorld()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_x",
                "output": [
                    {
                        "type": "function_call",
                        "name": "submit_job",
                        "arguments": json.dumps(
                            {"input_bytes": 1000, "assigned_node_id": "orbital-iss-cheap"}
                        ),
                        "call_id": "c2",
                    }
                ],
            },
        )

    async with _client(handler) as client:
        svc = AssistantService(client=client, settings=SETTINGS)
        out = await svc.ask(world, "run this on the ISS")
    assert world.submitted == []
    assert out["actions"] == []
    assert out["rejected"]
    assert "planner override" in out["rejected"][0]["error"]


@pytest.mark.asyncio
async def test_live_unknown_tool_rejected():
    world = FakeWorld()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "function_call",
                        "name": "replan",
                        "arguments": "{}",
                        "call_id": "c3",
                    }
                ]
            },
        )

    async with _client(handler) as client:
        out = await AssistantService(client=client, settings=SETTINGS).ask(world, "replan")
    assert out["rejected"][0]["tool"] == "replan"
    assert "unknown" in out["rejected"][0]["error"]


@pytest.mark.asyncio
async def test_live_error_falls_back_to_offline_parser():
    world = FakeWorld()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    async with _client(handler) as client:
        out = await AssistantService(client=client, settings=SETTINGS).ask(world, "play")
    assert out["parser"] == "offline_fallback"
    assert world.played is True
    assert out["grok_error"]


@pytest.mark.asyncio
async def test_voice_offline_message(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    out = await AssistantService().voice(FakeWorld(), b"xx", "c.webm", "audio/webm")
    assert out["ok"] is False
    assert out["mode"] == "offline"
    assert OFFLINE_NOTE in out["error"]


@pytest.mark.asyncio
async def test_voice_live_transcribe_then_ask():
    world = FakeWorld()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stt"):
            return httpx.Response(200, json={"text": "pause"})
        if request.url.path.endswith("/tts"):
            return httpx.Response(200, content=b"ID3")
        body = json.loads(request.content)
        if body.get("previous_response_id"):
            return httpx.Response(
                200, json={"output": [{"type": "message", "content": [{"text": "Done."}]}]}
            )
        return httpx.Response(
            200,
            json={
                "id": "r1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "pause",
                        "arguments": "{}",
                        "call_id": "v1",
                    }
                ],
            },
        )

    async with _client(handler) as client:
        out = await AssistantService(client=client, settings=SETTINGS).voice(
            world, b"RIFF", "clip.webm", "audio/webm", speak=True
        )
    assert out["ok"] is True
    assert out["transcript"] == "pause"
    assert world.paused is True
    assert out["audio_b64"]
