"""Ask / Voice orchestration. Every action is validated before execution."""

from __future__ import annotations

import base64
from typing import Any, Optional

from app.assistant import grok
from app.assistant.executor import execute
from app.assistant.intents import ValidatedAction, ValidationError, WorldCatalog, validate_intent
from app.assistant.parser import parse_offline


class AssistantService:
    def status(self) -> dict[str, Any]:
        live = grok.live_enabled()
        return {
            "mode": "live" if live else "offline",
            "grok": live,
            "voice": live,
            "voice_offline": "browser",
            "model": grok.XAI_MODEL if live else None,
            "tools": [
                "read_state",
                "explain_plan",
                "submit_job",
                "play",
                "pause",
                "disrupt_link",
            ],
            "planner": "deterministic",
        }

    async def ask(
        self,
        world: Any,
        text: str,
        source: str = "text",
        speak: bool = False,
    ) -> dict[str, Any]:
        catalog = WorldCatalog.from_world(world)
        hint = _catalog_hint(catalog)
        parser = "offline"
        grok_text: Optional[str] = None
        grok_error: Optional[str] = None
        raw_calls: list[dict[str, Any]] = []

        if grok.live_enabled():
            raw_calls, grok_text, grok_error = await grok.parse_with_grok(text, hint)
            if raw_calls:
                parser = "grok"
            elif grok_error:
                raw_calls = parse_offline(text, catalog)
                parser = "offline_fallback"
            else:
                # Grok replied in prose with no tools — still try offline if it looks like a command
                offline = parse_offline(text, catalog)
                if offline and offline[0]["tool"] != "read_state":
                    raw_calls = offline
                    parser = "offline_fallback"
                elif grok_text:
                    raw_calls = []
                    parser = "grok"
                else:
                    raw_calls = offline
                    parser = "offline_fallback"
        else:
            raw_calls = parse_offline(text, catalog)

        validated: list[ValidatedAction] = []
        rejected: list[dict[str, Any]] = []
        for call in raw_calls:
            result = validate_intent(call.get("tool", ""), call.get("args") or {}, catalog)
            if isinstance(result, ValidationError):
                rejected.append({"tool": result.tool, "error": result.message})
            else:
                validated.append(result)

        results: list[dict[str, Any]] = []
        for action in validated:
            results.append(await execute(world, action))

        reply = _compose_reply(text, parser, grok_text, validated, results, rejected)
        audio_b64 = None
        if speak and grok.live_enabled() and reply:
            audio, _err = await grok.speak(reply)
            if audio:
                audio_b64 = base64.b64encode(audio).decode("ascii")

        return {
            "reply": reply,
            "source": source,
            "parser": parser,
            "mode": "live" if grok.live_enabled() else "offline",
            "grok_error": grok_error,
            "actions": [
                {"tool": a.tool, "args": a.args, "ok": True} for a in validated
            ],
            "rejected": rejected,
            "results": results,
            "audio_b64": audio_b64,
            "transcript": text if source == "voice" else None,
        }

    async def voice(
        self,
        world: Any,
        audio: bytes,
        filename: str,
        content_type: str,
        speak: bool = True,
    ) -> dict[str, Any]:
        if not grok.live_enabled():
            return {
                "ok": False,
                "error": "xAI Voice needs XAI_API_KEY. Type in Ask, or use browser speech in offline mode.",
                "mode": "offline",
                "parser": "offline",
            }
        transcript, err = await grok.transcribe(audio, filename, content_type)
        if err or not transcript:
            return {
                "ok": False,
                "error": err or "empty transcript",
                "mode": "live",
                "parser": "grok",
            }
        out = await self.ask(world, transcript, source="voice", speak=speak)
        out["ok"] = True
        out["transcript"] = transcript
        return out


def _catalog_hint(catalog: WorldCatalog) -> str:
    return (
        f"links={sorted(catalog.link_ids)}\n"
        f"jobs={sorted(catalog.job_ids)}\n"
        f"stations={sorted(catalog.station_ids)}\n"
        f"nodes={sorted(catalog.node_ids)}"
    )


def _compose_reply(
    text: str,
    parser: str,
    grok_text: Optional[str],
    actions: list[ValidatedAction],
    results: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    if grok_text and parser == "grok" and not actions:
        parts.append(grok_text.strip())
    for res in results:
        tool = res.get("tool")
        payload = res.get("result") or {}
        if tool == "play":
            parts.append(f"Simulation playing at t={payload.get('t', 0):.0f}s.")
        elif tool == "pause":
            parts.append(f"Simulation paused at t={payload.get('t', 0):.0f}s.")
        elif tool == "submit_job":
            if payload.get("error"):
                parts.append(f"Job submitted but placement failed: {payload['error']}")
            else:
                node = payload.get("assigned_node_id") or "unassigned"
                parts.append(
                    f"Job {payload.get('job_id')} placed on {node} "
                    f"(cost ${payload.get('estimated_cost')}, "
                    f"finish {payload.get('estimated_completion')}s). "
                    "The planner chose the node."
                )
        elif tool == "disrupt_link":
            if payload.get("disruption") is None:
                parts.append(f"Cleared disruption on {payload.get('link_id')}.")
            else:
                parts.append(f"Disrupted {payload.get('link_id')}.")
        elif tool == "explain_plan":
            if payload.get("error"):
                parts.append(payload["error"])
            else:
                reasons = ", ".join(payload.get("reasons") or []) or "see baseline comparison"
                parts.append(
                    f"Job {payload.get('job_id')} → {payload.get('chosen_node_id')}. "
                    f"{reasons}."
                )
        elif tool == "read_state":
            jobs = payload.get("jobs")
            settings = payload.get("settings") or {}
            if jobs is not None:
                parts.append(f"{len(jobs)} job(s); clock t={settings.get('t', '?')}; playing={settings.get('playing')}.")
            elif settings:
                parts.append(f"Clock t={settings.get('t')}; playing={settings.get('playing')}.")
    for rej in rejected:
        parts.append(f"Rejected {rej.get('tool')}: {rej.get('error')}")
    if not parts:
        if parser == "offline":
            return (
                "Offline parser ready. Try “pause”, “play”, “submit a job”, "
                "“explain the plan”, “status”, or “disrupt the ISS Ashburn link”."
            )
        return grok_text or f"Heard: {text}"
    return " ".join(parts)
