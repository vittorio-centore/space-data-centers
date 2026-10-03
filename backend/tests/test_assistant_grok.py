"""Live xAI client tests — mocked HTTP, no real XAI_API_KEY."""

from __future__ import annotations

import json

import httpx
import pytest

from app.assistant.grok import (
    GrokSettings,
    GrokTurn,
    complete_turn,
    continue_with_results,
    live_enabled,
    parse_with_grok,
    speak,
    transcribe,
)

SETTINGS = GrokSettings(api_key="xai-test-key", base="https://api.x.ai/v1", model="grok-4")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


def test_live_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert live_enabled() is False
    monkeypatch.setenv("XAI_API_KEY", "  xai-abc  ")
    assert live_enabled() is True


@pytest.mark.asyncio
async def test_complete_turn_requires_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    turn = await complete_turn("pause", "links=[]")
    assert turn.calls == []
    assert turn.error == "XAI_API_KEY missing"


@pytest.mark.asyncio
async def test_responses_function_call():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        body = json.loads(request.content)
        seen["body"] = body
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "pause",
                        "arguments": "{}",
                        "call_id": "call_pause",
                    }
                ],
            },
        )

    async with _client(handler) as client:
        turn = await complete_turn("please pause", "jobs=[]", settings=SETTINGS, client=client)
    assert turn.error is None
    assert turn.response_id == "resp_1"
    assert turn.calls == [{"tool": "pause", "args": {}, "call_id": "call_pause"}]
    assert seen["url"].endswith("/responses")
    assert seen["auth"] == "Bearer xai-test-key"
    assert seen["body"]["tools"][0]["name"] == "read_state"
    assert "Never choose a compute node" in seen["body"]["input"][0]["content"]


@pytest.mark.asyncio
async def test_chat_fallback_and_sanitized_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/responses"):
            return httpx.Response(400, text="bad responses Bearer xai-secret-token")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "tc1",
                                    "function": {
                                        "name": "submit_job",
                                        "arguments": '{"preset":"a"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    async with _client(handler) as client:
        turn = await complete_turn("case a", "", settings=SETTINGS, client=client)
    assert turn.transport == "chat"
    assert turn.calls[0]["tool"] == "submit_job"
    assert turn.calls[0]["args"] == {"preset": "a"}


@pytest.mark.asyncio
async def test_both_endpoints_fail_redacts_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="nope Bearer xai-super-secret")

    async with _client(handler) as client:
        turn = await complete_turn("hi", "", settings=SETTINGS, client=client)
    assert turn.error
    assert "xai-super-secret" not in turn.error
    assert "[redacted]" in turn.error


@pytest.mark.asyncio
async def test_continue_with_results_responses():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["previous_response_id"] == "resp_1"
        assert body["input"][0]["type"] == "function_call_output"
        assert json.loads(body["input"][0]["output"])["ok"] is True
        return httpx.Response(
            200,
            json={
                "id": "resp_2",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Paused at t=12s."}],
                    }
                ],
            },
        )

    prior = GrokTurn(response_id="resp_1", transport="responses")
    async with _client(handler) as client:
        turn = await continue_with_results(
            prior,
            [{"call_id": "call_pause", "output": '{"ok": true}'}],
            "",
            settings=SETTINGS,
            client=client,
        )
    assert turn.text == "Paused at t=12s."


@pytest.mark.asyncio
async def test_stt_and_tts():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stt"):
            return httpx.Response(200, json={"text": "pause the sim"})
        if request.url.path.endswith("/tts"):
            return httpx.Response(200, content=b"ID3fake-mp3")
        return httpx.Response(404)

    async with _client(handler) as client:
        text, err = await transcribe(
            b"RIFF", "clip.webm", "audio/webm", settings=SETTINGS, client=client
        )
        audio, aerr = await speak("Paused.", settings=SETTINGS, client=client)
    assert err is None and text == "pause the sim"
    assert aerr is None and audio == b"ID3fake-mp3"


@pytest.mark.asyncio
async def test_parse_with_grok_tuple():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"output": [{"type": "function_call", "name": "play", "arguments": {}}]},
        )

    async with _client(handler) as client:
        calls, text, err = await parse_with_grok("play", "", settings=SETTINGS, client=client)
    assert err is None
    assert calls[0]["tool"] == "play"
    assert text is None
