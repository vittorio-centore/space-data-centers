"""Ask / Voice orchestration. Every action is validated before execution."""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

from app.assistant import grok
from app.assistant.executor import execute
from app.assistant.grok import GrokSettings, GrokTurn
from app.assistant.intents import ValidatedAction, ValidationError, WorldCatalog, validate_intent
from app.assistant.parser import parse_offline

OFFLINE_NOTE = "Offline (no XAI_API_KEY)."
MAX_ASK_CHARS = 4_000
MAX_TOOL_ROUNDS = 2


class AssistantService:
    def __init__(self, client=None, settings: Optional[GrokSettings] = None) -> None:
        self.client = client
        self.settings = settings

    def _settings(self) -> GrokSettings:
        return self.settings or GrokSettings.from_env()

    def status(self) -> dict[str, Any]:
        cfg = self._settings()
        live = cfg.api_key is not None
        return {
            "mode": "live" if live else "offline",
            "grok": live,
            "voice": live,
            "voice_offline": "browser",
            "model": cfg.model if live else None,
            "tools": [
                "read_state",
                "explain_plan",
                "submit_job",
                "play",
                "pause",
                "disrupt_link",
            ],
            "planner": "deterministic",
            "note": None if live else OFFLINE_NOTE,
        }

    async def ask(
        self,
        world: Any,
        text: str,
        source: str = "text",
        speak: bool = False,
    ) -> dict[str, Any]:
        text = (text or "").strip()[:MAX_ASK_CHARS]
        catalog = WorldCatalog.from_world(world)
        hint = _catalog_hint(catalog)
        cfg = self._settings()
        live = cfg.api_key is not None
        parser = "offline"
        grok_text: Optional[str] = None
        grok_error: Optional[str] = None
        raw_calls: list[dict[str, Any]] = []
        turn: Optional[GrokTurn] = None

        if live:
            turn = await grok.complete_turn(text, hint, settings=cfg, client=self.client)
            grok_error = turn.error
            if turn.calls:
                raw_calls = turn.calls
                parser = "grok"
                grok_text = turn.text
            elif turn.error:
                raw_calls = parse_offline(text, catalog)
                parser = "offline_fallback"
            else:
                offline = parse_offline(text, catalog)
                if offline and offline[0]["tool"] != "read_state":
                    raw_calls = offline
                    parser = "offline_fallback"
                elif turn.text:
                    raw_calls = []
                    parser = "grok"
                    grok_text = turn.text
                else:
                    raw_calls = offline
                    parser = "offline_fallback"
        else:
            raw_calls = parse_offline(text, catalog)

        validated, rejected, results = await self._run_validated(world, catalog, raw_calls)

        used_followup = False
        if live and turn and parser == "grok" and (validated or rejected):
            follow = await self._follow_up(turn, results, rejected, hint, cfg)
            if follow and follow.text:
                grok_text = follow.text
                used_followup = True
            if follow and follow.error and not grok_error:
                grok_error = follow.error

        reply = _compose_reply(
            text, parser, grok_text, results, rejected, live, used_followup
        )
        audio_b64 = None
        if speak and live and reply:
            audio, _err = await grok.speak(reply, settings=cfg, client=self.client)
            if audio:
                audio_b64 = base64.b64encode(audio).decode("ascii")

        return {
            "reply": reply,
            "source": source,
            "parser": parser,
            "mode": "live" if live else "offline",
            "grok_error": grok_error,
            "note": None if live else OFFLINE_NOTE,
            "actions": [{"tool": a.tool, "args": a.args, "ok": True} for a in validated],
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
        cfg = self._settings()
        if not cfg.api_key:
            return {
                "ok": False,
                "error": f"{OFFLINE_NOTE} Type in Ask, or use browser speech — the same validated tools run.",
                "mode": "offline",
                "parser": "offline",
                "note": OFFLINE_NOTE,
            }
        transcript, err = await grok.transcribe(
            audio, filename, content_type, settings=cfg, client=self.client
        )
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

    async def _run_validated(
        self, world: Any, catalog: WorldCatalog, raw_calls: list[dict[str, Any]]
    ) -> tuple[list[ValidatedAction], list[dict[str, Any]], list[dict[str, Any]]]:
        validated: list[ValidatedAction] = []
        rejected: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for call in raw_calls:
            result = validate_intent(call.get("tool", ""), call.get("args") or {}, catalog)
            if isinstance(result, ValidationError):
                rejected.append(
                    {
                        "tool": result.tool,
                        "error": result.message,
                        "call_id": call.get("call_id"),
                    }
                )
                continue
            validated.append(result)
            try:
                executed = await execute(world, result)
            except Exception as exc:  # noqa: BLE001 — surface to operator, do not crash Ask
                executed = {"ok": False, "tool": result.tool, "error": str(exc)}
            executed = {**executed, "call_id": call.get("call_id")}
            results.append(executed)
        return validated, rejected, results

    async def _follow_up(
        self,
        turn: GrokTurn,
        results: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        hint: str,
        cfg: GrokSettings,
    ) -> Optional[GrokTurn]:
        outputs: list[dict[str, Any]] = []
        for res in results:
            if not res.get("call_id"):
                continue
            payload = {k: v for k, v in res.items() if k != "call_id"}
            outputs.append({"call_id": res["call_id"], "output": json.dumps(payload, default=str)})
        for rej in rejected:
            if not rej.get("call_id"):
                continue
            outputs.append(
                {
                    "call_id": rej["call_id"],
                    "output": json.dumps({"ok": False, "error": rej["error"]}),
                }
            )
        if not outputs:
            return None
        # One continuation is enough; extra tool requests are ignored.
        _ = MAX_TOOL_ROUNDS
        return await grok.continue_with_results(
            turn, outputs, hint, settings=cfg, client=self.client
        )


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
    results: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    live: bool,
    used_followup: bool,
) -> str:
    parts: list[str] = []
    model_only = bool(grok_text) and parser == "grok" and not results and not rejected
    if model_only or (used_followup and grok_text):
        parts.append(grok_text.strip())
    if not (used_followup and grok_text):
        for res in results:
            tool = res.get("tool")
            payload = res.get("result") or {}
            if res.get("error") and not payload:
                parts.append(f"{tool} failed: {res['error']}")
                continue
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
                    parts.append(
                        f"{len(jobs)} job(s); clock t={settings.get('t', '?')}; playing={settings.get('playing')}."
                    )
                elif settings:
                    parts.append(f"Clock t={settings.get('t')}; playing={settings.get('playing')}.")
    for rej in rejected:
        parts.append(f"Rejected {rej.get('tool')}: {rej.get('error')}")

    if not parts:
        if parser in ("offline", "offline_fallback"):
            body = (
                "Try “pause”, “play”, “submit a job”, “explain the plan”, "
                "“status”, or “disrupt the ISS Ashburn link”."
            )
            return f"{OFFLINE_NOTE} {body}" if not live else body
        return grok_text or f"Heard: {text}"

    body = " ".join(parts)
    if not live:
        return f"{OFFLINE_NOTE} {body}"
    return body
