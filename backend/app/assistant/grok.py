"""xAI Grok + Voice HTTP client.

Live when ``XAI_API_KEY`` is set. Settings are read at call time so tests can
inject a key and a mock transport without importing the module after env setup.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

DEFAULT_BASE = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4"
DEFAULT_STT_MODEL = "grok-voice-transcribe-2.0"
DEFAULT_TTS_VOICE = "eve"
MAX_USER_CHARS = 4_000
MAX_TTS_CHARS = 800
MAX_ERROR_CHARS = 240

GROK_TOOLS = [
    {
        "type": "function",
        "name": "read_state",
        "description": "Read simulation state: jobs, links, clock, play/pause.",
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "enum": ["jobs", "links", "settings", "all"]},
            },
        },
    },
    {
        "type": "function",
        "name": "explain_plan",
        "description": "Explain why the planner chose a node versus the cheapest-node baseline.",
        "parameters": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
        },
    },
    {
        "type": "function",
        "name": "submit_job",
        "description": (
            "Submit a job or thesis preset. Do not pick a compute node — "
            "the deterministic planner assigns placement."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input_bytes": {"type": "integer"},
                "output_bytes": {"type": "integer"},
                "work": {"type": "number"},
                "deadline_offset_s": {"type": "number"},
                "deadline_at": {"type": "number"},
                "source_id": {"type": "string"},
                "destination_id": {"type": "string"},
                "preset": {"type": "string", "enum": ["a", "b"]},
            },
        },
    },
    {
        "type": "function",
        "name": "play",
        "description": "Start or resume the simulation clock.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "pause",
        "description": "Pause the simulation clock.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "disrupt_link",
        "description": "Force a configured link down or clear a disruption. Requires a real link_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "link_id": {"type": "string"},
                "action": {"type": "string", "enum": ["down", "clear"]},
                "bandwidth_factor": {"type": "number"},
                "until": {"type": "number"},
            },
            "required": ["link_id"],
        },
    },
]

CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
        },
    }
    for t in GROK_TOOLS
]

SYSTEM = (
    "You are the Space Data Centers operator assistant. "
    "Call tools to inspect or control the sim. "
    "Never choose a compute node or invent link/job ids. "
    "Placement is a deterministic planner; you may only submit jobs. "
    "If the user asks why a placement won or lost, call explain_plan. "
    "If they want status, call read_state. "
    "For play/pause/disrupt/submit, call the matching tool. "
    "After tools run, reply briefly. Do not invent tool results."
)


@dataclass(frozen=True)
class GrokSettings:
    api_key: Optional[str]
    base: str = DEFAULT_BASE
    model: str = DEFAULT_MODEL
    stt_model: str = DEFAULT_STT_MODEL
    tts_voice: str = DEFAULT_TTS_VOICE

    @classmethod
    def from_env(cls) -> "GrokSettings":
        key = (os.environ.get("XAI_API_KEY") or "").strip() or None
        return cls(
            api_key=key,
            base=(os.environ.get("XAI_API_BASE") or DEFAULT_BASE).rstrip("/"),
            model=os.environ.get("XAI_MODEL") or DEFAULT_MODEL,
            stt_model=os.environ.get("XAI_STT_MODEL") or DEFAULT_STT_MODEL,
            tts_voice=os.environ.get("XAI_TTS_VOICE") or DEFAULT_TTS_VOICE,
        )


@dataclass
class GrokTurn:
    calls: list[dict[str, Any]] = field(default_factory=list)
    text: Optional[str] = None
    error: Optional[str] = None
    response_id: Optional[str] = None
    transport: str = "responses"
    chat_messages: list[dict[str, Any]] = field(default_factory=list)


# Back-compat names used by status() and older imports.
def api_key() -> Optional[str]:
    return GrokSettings.from_env().api_key


def live_enabled() -> bool:
    return api_key() is not None


def _settings_model() -> str:
    return GrokSettings.from_env().model


XAI_MODEL = DEFAULT_MODEL  # overwritten at status time via settings


def _sanitize_error(msg: str) -> str:
    cleaned = re.sub(r"(Bearer\s+)[^\s]+", r"\1[redacted]", msg, flags=re.I)
    cleaned = re.sub(r"xai-[A-Za-z0-9_-]+", "xai-[redacted]", cleaned)
    return cleaned[:MAX_ERROR_CHARS]


def _parse_args(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _from_responses(data: dict[str, Any]) -> GrokTurn:
    calls: list[dict[str, Any]] = []
    texts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        typ = item.get("type")
        if typ in ("function_call", "tool_call"):
            name = item.get("name") or (item.get("function") or {}).get("name")
            if not name:
                continue
            calls.append(
                {
                    "tool": str(name),
                    "args": _parse_args(item.get("arguments") or item.get("args")),
                    "call_id": item.get("call_id") or item.get("id"),
                }
            )
        elif typ == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
                elif isinstance(part, str):
                    texts.append(part)
    if not calls and not texts:
        ot = data.get("output_text")
        if ot:
            texts.append(str(ot))
    return GrokTurn(
        calls=calls,
        text="\n".join(texts) or None,
        response_id=data.get("id"),
        transport="responses",
    )


def _from_chat(data: dict[str, Any], prior: Optional[list[dict[str, Any]]] = None) -> GrokTurn:
    calls: list[dict[str, Any]] = []
    texts: list[str] = []
    messages = list(prior or [])
    for choice in data.get("choices") or []:
        msg = choice.get("message") or {}
        messages.append(msg)
        if msg.get("content"):
            texts.append(str(msg["content"]))
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            calls.append(
                {
                    "tool": str(name),
                    "args": _parse_args(fn.get("arguments")),
                    "call_id": tc.get("id"),
                }
            )
    return GrokTurn(
        calls=calls,
        text="\n".join(texts) or None,
        transport="chat",
        chat_messages=messages,
    )


def _auth_headers(key: str, json_body: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {key}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


async def _request(
    method: str,
    url: str,
    *,
    key: str,
    client: Optional[httpx.AsyncClient] = None,
    json_body: Any = None,
    files: Any = None,
    data: Any = None,
    timeout: float = 40.0,
) -> httpx.Response:
    headers = _auth_headers(key, json_body=files is None)
    if client is not None:
        return await client.request(
            method, url, headers=headers, json=json_body, files=files, data=data
        )
    async with httpx.AsyncClient(timeout=timeout) as owned:
        return await owned.request(
            method, url, headers=headers, json=json_body, files=files, data=data
        )


def _system(catalog_hint: str) -> str:
    return SYSTEM + "\nKnown ids:\n" + catalog_hint


async def complete_turn(
    text: str,
    catalog_hint: str,
    *,
    settings: Optional[GrokSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> GrokTurn:
    """First Grok turn: Responses API, then chat/completions fallback."""
    settings = settings or GrokSettings.from_env()
    if not settings.api_key:
        return GrokTurn(error="XAI_API_KEY missing")
    user_text = (text or "").strip()[:MAX_USER_CHARS]
    if not user_text:
        return GrokTurn(error="empty text")

    payload = {
        "model": settings.model,
        "input": [
            {"role": "system", "content": _system(catalog_hint)},
            {"role": "user", "content": user_text},
        ],
        "tools": GROK_TOOLS,
        "store": False,
        "tool_choice": "auto",
    }
    try:
        res = await _request(
            "POST",
            f"{settings.base}/responses",
            key=settings.api_key,
            client=client,
            json_body=payload,
        )
        if res.status_code < 400:
            return _from_responses(res.json())

        chat_messages = [
            {"role": "system", "content": _system(catalog_hint)},
            {"role": "user", "content": user_text},
        ]
        chat = await _request(
            "POST",
            f"{settings.base}/chat/completions",
            key=settings.api_key,
            client=client,
            json_body={
                "model": settings.model,
                "messages": chat_messages,
                "tools": CHAT_TOOLS,
                "tool_choice": "auto",
            },
        )
        if chat.status_code >= 400:
            return GrokTurn(
                error=_sanitize_error(f"xAI error {res.status_code}: {res.text}")
            )
        return _from_chat(chat.json(), chat_messages)
    except httpx.HTTPError as exc:
        return GrokTurn(error=_sanitize_error(f"xAI unreachable: {exc}"))
    except (ValueError, json.JSONDecodeError) as exc:
        return GrokTurn(error=_sanitize_error(f"xAI bad payload: {exc}"))


async def continue_with_results(
    turn: GrokTurn,
    outputs: list[dict[str, Any]],
    catalog_hint: str,
    *,
    settings: Optional[GrokSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> GrokTurn:
    """Send validated tool results back so Grok can write a brief reply."""
    settings = settings or GrokSettings.from_env()
    if not settings.api_key:
        return GrokTurn(error="XAI_API_KEY missing")
    if not outputs:
        return GrokTurn(text=turn.text, transport=turn.transport, response_id=turn.response_id)

    try:
        if turn.transport == "chat":
            messages = list(turn.chat_messages)
            for item in outputs:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.get("call_id") or "",
                        "content": item.get("output") or "{}",
                    }
                )
            chat = await _request(
                "POST",
                f"{settings.base}/chat/completions",
                key=settings.api_key,
                client=client,
                json_body={
                    "model": settings.model,
                    "messages": messages,
                    "tools": CHAT_TOOLS,
                },
            )
            if chat.status_code >= 400:
                return GrokTurn(
                    error=_sanitize_error(f"xAI error {chat.status_code}: {chat.text}"),
                    transport="chat",
                )
            return _from_chat(chat.json(), messages)

        payload_input = [
            {
                "type": "function_call_output",
                "call_id": item.get("call_id") or "",
                "output": item.get("output") or "{}",
            }
            for item in outputs
        ]
        body: dict[str, Any] = {
            "model": settings.model,
            "input": payload_input,
            "tools": GROK_TOOLS,
            "store": False,
        }
        if turn.response_id:
            body["previous_response_id"] = turn.response_id
        else:
            body["input"] = [
                {"role": "system", "content": _system(catalog_hint)},
                *payload_input,
            ]
        res = await _request(
            "POST",
            f"{settings.base}/responses",
            key=settings.api_key,
            client=client,
            json_body=body,
        )
        if res.status_code >= 400:
            return GrokTurn(
                error=_sanitize_error(f"xAI error {res.status_code}: {res.text}")
            )
        return _from_responses(res.json())
    except httpx.HTTPError as exc:
        return GrokTurn(error=_sanitize_error(f"xAI unreachable: {exc}"))
    except (ValueError, json.JSONDecodeError) as exc:
        return GrokTurn(error=_sanitize_error(f"xAI bad payload: {exc}"))


async def parse_with_grok(
    text: str,
    catalog_hint: str,
    *,
    settings: Optional[GrokSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[list[dict[str, Any]], Optional[str], Optional[str]]:
    """Return (tool_calls, assistant_text, error)."""
    turn = await complete_turn(text, catalog_hint, settings=settings, client=client)
    return turn.calls, turn.text, turn.error


async def transcribe(
    audio: bytes,
    filename: str,
    content_type: str,
    *,
    settings: Optional[GrokSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[Optional[str], Optional[str]]:
    settings = settings or GrokSettings.from_env()
    if not settings.api_key:
        return None, "XAI_API_KEY missing"
    if not audio:
        return None, "empty audio"
    try:
        res = await _request(
            "POST",
            f"{settings.base}/stt",
            key=settings.api_key,
            client=client,
            files={"file": (filename or "clip.webm", audio, content_type or "application/octet-stream")},
            data={"model": settings.stt_model},
            timeout=60.0,
        )
        if res.status_code >= 400:
            return None, _sanitize_error(f"xAI STT error {res.status_code}: {res.text}")
        data = res.json()
        text = data.get("text") or data.get("transcript")
        if not text:
            return None, "empty transcript"
        return str(text).strip(), None
    except httpx.HTTPError as exc:
        return None, _sanitize_error(f"xAI STT unreachable: {exc}")
    except (ValueError, json.JSONDecodeError) as exc:
        return None, _sanitize_error(f"xAI STT bad payload: {exc}")


async def speak(
    text: str,
    *,
    settings: Optional[GrokSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[Optional[bytes], Optional[str]]:
    settings = settings or GrokSettings.from_env()
    if not settings.api_key:
        return None, "XAI_API_KEY missing"
    snippet = (text or "").strip()
    if not snippet:
        return None, "empty text"
    try:
        res = await _request(
            "POST",
            f"{settings.base}/tts",
            key=settings.api_key,
            client=client,
            json_body={
                "text": snippet[:MAX_TTS_CHARS],
                "voice_id": settings.tts_voice,
                "language": "en",
            },
        )
        if res.status_code >= 400:
            return None, _sanitize_error(f"xAI TTS error {res.status_code}: {res.text}")
        audio = res.content
        if not audio:
            return None, "empty audio"
        return audio, None
    except httpx.HTTPError as exc:
        return None, _sanitize_error(f"xAI TTS unreachable: {exc}")
