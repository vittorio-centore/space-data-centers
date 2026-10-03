"""xAI Grok + Voice HTTP client. No-ops when XAI_API_KEY is unset."""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

XAI_BASE = os.environ.get("XAI_API_BASE", "https://api.x.ai/v1").rstrip("/")
XAI_MODEL = os.environ.get("XAI_MODEL", "grok-4")
XAI_STT_MODEL = os.environ.get("XAI_STT_MODEL", "grok-voice-transcribe-2.0")
XAI_TTS_VOICE = os.environ.get("XAI_TTS_VOICE", "eve")

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

SYSTEM = (
    "You are the Space Data Centers operator assistant. "
    "Call tools to inspect or control the sim. "
    "Never choose a compute node or invent link/job ids. "
    "Placement is a deterministic planner; you may only submit jobs. "
    "If the user asks why a placement won or lost, call explain_plan. "
    "If they want status, call read_state. "
    "For play/pause/disrupt/submit, call the matching tool. "
    "Reply briefly after tools run."
)


def api_key() -> Optional[str]:
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    return key or None


def live_enabled() -> bool:
    return api_key() is not None


async def parse_with_grok(text: str, catalog_hint: str) -> tuple[list[dict[str, Any]], Optional[str], Optional[str]]:
    """Return (tool_calls, assistant_text, error)."""
    key = api_key()
    if not key:
        return [], None, "XAI_API_KEY missing"

    payload = {
        "model": XAI_MODEL,
        "input": [
            {"role": "system", "content": SYSTEM + "\nKnown ids:\n" + catalog_hint},
            {"role": "user", "content": text},
        ],
        "tools": GROK_TOOLS,
        "store": False,
    }
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            res = await client.post(
                f"{XAI_BASE}/responses",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            if res.status_code >= 400:
                # Fallback to chat completions (legacy)
                chat = await client.post(
                    f"{XAI_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": XAI_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM + "\nKnown ids:\n" + catalog_hint},
                            {"role": "user", "content": text},
                        ],
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": t["name"],
                                    "description": t["description"],
                                    "parameters": t["parameters"],
                                },
                            }
                            for t in GROK_TOOLS
                        ],
                    },
                )
                if chat.status_code >= 400:
                    return [], None, f"xAI error {res.status_code}: {res.text[:240]}"
                return _from_chat(chat.json())
            return _from_responses(res.json())
    except httpx.HTTPError as exc:
        return [], None, f"xAI unreachable: {exc}"


def _from_responses(data: dict[str, Any]) -> tuple[list[dict[str, Any]], Optional[str], Optional[str]]:
    calls: list[dict[str, Any]] = []
    texts: list[str] = []
    for item in data.get("output") or []:
        typ = item.get("type")
        if typ in ("function_call", "tool_call"):
            args = item.get("arguments") or item.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            name = item.get("name") or item.get("function", {}).get("name")
            if name:
                calls.append({"tool": name, "args": args})
        elif typ == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
                elif isinstance(part, str):
                    texts.append(part)
    if not calls and not texts:
        # some payloads nest output_text
        ot = data.get("output_text")
        if ot:
            texts.append(str(ot))
    return calls, "\n".join(texts) or None, None


def _from_chat(data: dict[str, Any]) -> tuple[list[dict[str, Any]], Optional[str], Optional[str]]:
    calls: list[dict[str, Any]] = []
    texts: list[str] = []
    for choice in data.get("choices") or []:
        msg = choice.get("message") or {}
        if msg.get("content"):
            texts.append(str(msg["content"]))
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments") or "{}"
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            name = fn.get("name")
            if name:
                calls.append({"tool": name, "args": args})
    return calls, "\n".join(texts) or None, None


async def transcribe(audio: bytes, filename: str, content_type: str) -> tuple[Optional[str], Optional[str]]:
    key = api_key()
    if not key:
        return None, "XAI_API_KEY missing"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                f"{XAI_BASE}/stt",
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (filename or "clip.webm", audio, content_type or "application/octet-stream")},
                data={"model": XAI_STT_MODEL},
            )
            if res.status_code >= 400:
                return None, f"xAI STT error {res.status_code}: {res.text[:240]}"
            data = res.json()
            text = data.get("text") or data.get("transcript")
            if not text:
                return None, "empty transcript"
            return str(text), None
    except httpx.HTTPError as exc:
        return None, f"xAI STT unreachable: {exc}"


async def speak(text: str) -> tuple[Optional[bytes], Optional[str]]:
    key = api_key()
    if not key:
        return None, "XAI_API_KEY missing"
    snippet = (text or "").strip()
    if not snippet:
        return None, "empty text"
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            res = await client.post(
                f"{XAI_BASE}/tts",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"text": snippet[:800], "voice_id": XAI_TTS_VOICE, "language": "en"},
            )
            if res.status_code >= 400:
                return None, f"xAI TTS error {res.status_code}: {res.text[:240]}"
            return res.content, None
    except httpx.HTTPError as exc:
        return None, f"xAI TTS unreachable: {exc}"
