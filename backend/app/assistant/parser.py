"""Offline keyword intent parser. Used when XAI_API_KEY is missing or Grok fails."""

from __future__ import annotations

import re
from typing import Any, Optional

from app.assistant.intents import WorldCatalog

LINK_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("ashburn", "iss"), "link-gs-ashburn-orbital-iss-cheap"),
    (("iss", "ashburn"), "link-gs-ashburn-orbital-iss-cheap"),
    (("madrid", "iss"), "link-gs-madrid-orbital-iss-cheap"),
    (("iss", "madrid"), "link-gs-madrid-orbital-iss-cheap"),
    (("ashburn", "css"), "link-gs-ashburn-orbital-css"),
    (("madrid", "css"), "link-gs-madrid-orbital-css"),
    (("ashburn", "noaa"), "link-gs-ashburn-orbital-noaa"),
    (("madrid", "noaa"), "link-gs-madrid-orbital-noaa"),
    (("earth", "ashburn"), "link-earth-us-east-gs-ashburn"),
    (("terrestrial", "ashburn"), "link-earth-us-east-gs-ashburn"),
    (("earth", "madrid"), "link-earth-us-east-gs-madrid"),
    (("terrestrial", "madrid"), "link-earth-us-east-gs-madrid"),
]

_SMALLTALK = re.compile(
    r"^(hi|hello|hey|thanks|thank you|ok|okay|yo|good (morning|afternoon|evening))[.!\s]*$"
)
_PRESET_B = re.compile(r"\b(case\s*b|thesis\s*b|cheap\s+wins)\b")
_PRESET_A = re.compile(r"\b(case\s*a|thesis\s*a|cheap\s+loses)\b")
_CLEAR_LINK = re.compile(
    r"\b(clear|restore|undisrupt|bring\s+up|heal)\b.+\b(link|contact|disruption)\b"
    r"|\b(clear|restore)\s+(the\s+)?(disruption|link)\b"
    r"|\b(clear|restore)\s+(the\s+)?(iss|css|noaa|ashburn|madrid|terrestrial)\b"
)
_DISRUPT = re.compile(r"\b(disrupt|drop|take\s+down|force\s+down|cut|kill)\b")
_LINKISH = re.compile(r"\b(link|contact|iss|css|noaa|ashburn|madrid|terrestrial)\b")
_SUBMIT = re.compile(
    r"\b(submit|place|queue|create|start|run)\b.+\b(job|batch)\b"
    r"|\b(new\s+job|place\s+a\s+job|submit\s+a\s+job|start\s+a\s+job)\b"
)
_PLAY = re.compile(r"\b(play|resume|unpause|start)\b.+\b(sim|simulation|clock)\b|^\s*(play|resume|unpause)\s*$")
_PLAY_BARE = re.compile(r"\b(play|resume|unpause|start)\b")
_PAUSE = re.compile(r"\b(pause|halt)\b|^\s*(stop)\s*$|\bstop\s+(the\s+)?(sim|simulation|clock)\b")
_EXPLAIN = re.compile(
    r"\b(explain|why\s+(did|does|was|is)|baseline|chosen\s+node|why\s+this\s+node)\b"
    r"|\b(show|what('s| is))\s+(the\s+)?(plan|route)\b"
)
_STATUS = re.compile(
    r"\b(status|state|snapshot|overview|how\s+many|is\s+it\s+playing"
    r"|what('s| is)\s+happening|clock)\b"
)


def parse_offline(text: str, catalog: Optional[WorldCatalog] = None) -> list[dict[str, Any]]:
    """Return raw tool calls from a spoken or typed phrase."""
    t = (text or "").strip().lower()
    if not t:
        return []
    if _SMALLTALK.match(t):
        return []

    if _PRESET_B.search(t):
        return [{"tool": "submit_job", "args": {"preset": "b"}}]
    if _PRESET_A.search(t):
        return [{"tool": "submit_job", "args": {"preset": "a"}}]

    if _CLEAR_LINK.search(t):
        link_id = _guess_link(t, catalog)
        if link_id:
            return [{"tool": "disrupt_link", "args": {"link_id": link_id, "action": "clear"}}]
        return [{"tool": "read_state", "args": {"focus": "links"}}]

    if _DISRUPT.search(t) and _LINKISH.search(t):
        link_id = _guess_link(t, catalog)
        if link_id:
            return [{"tool": "disrupt_link", "args": {"link_id": link_id, "action": "down"}}]
        return [{"tool": "read_state", "args": {"focus": "links"}}]

    if _SUBMIT.search(t):
        return [{"tool": "submit_job", "args": _job_args_from_text(t)}]

    if _PLAY.search(t) or (
        _PLAY_BARE.search(t) and not re.search(r"\b(job|case|batch)\b", t)
    ):
        return [{"tool": "play", "args": {}}]

    if _PAUSE.search(t) and not re.search(r"\b(job)\b", t):
        return [{"tool": "pause", "args": {}}]

    if _EXPLAIN.search(t):
        job_id = _guess_job(t, catalog)
        args: dict[str, Any] = {}
        if job_id:
            args["job_id"] = job_id
        return [{"tool": "explain_plan", "args": args}]

    if _STATUS.search(t):
        return [{"tool": "read_state", "args": {"focus": "all"}}]

    if re.search(r"\b(submit|place|queue)\b", t):
        return [{"tool": "submit_job", "args": _job_args_from_text(t)}]

    return [{"tool": "read_state", "args": {"focus": "all"}}]


def _job_args_from_text(t: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    m = re.search(r"(\d+(?:\.\d+)?)\s*m(?:b|egabytes?)\s*(input|in)?", t)
    if m and (m.group(2) or "input" in t or "in" not in t):
        if not m.group(2) and re.search(r"output|out", t) and "input" not in t and "in " not in t:
            args["output_bytes"] = int(float(m.group(1)) * 1_000_000)
        else:
            args["input_bytes"] = int(float(m.group(1)) * 1_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*m(?:b|egabytes?)\s*(output|out)", t)
    if m:
        args["output_bytes"] = int(float(m.group(1)) * 1_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(work|flops|units)", t)
    if m:
        args["work"] = float(m.group(1))
    m = re.search(r"deadline\s*(?:of|in|at)?\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds|m|min|mins|minutes|h|hr|hours)?", t)
    if m:
        qty = float(m.group(1))
        unit = (m.group(2) or "s").lower()
        if unit.startswith("h"):
            qty *= 3600
        elif unit.startswith("m"):
            qty *= 60
        args["deadline_offset_s"] = qty
    if "madrid" in t and re.search(r"\b(source|from|origin)\b", t):
        args["source_id"] = "gs-madrid"
    if "madrid" in t and re.search(r"\b(destination|to|sink|dest)\b", t):
        args["destination_id"] = "gs-madrid"
    if "ashburn" in t and re.search(r"\b(source|from|origin)\b", t):
        args["source_id"] = "gs-ashburn"
    return args


def _guess_job(t: str, catalog: Optional[WorldCatalog]) -> Optional[str]:
    if not catalog:
        return None
    for jid in sorted(catalog.job_ids, key=len, reverse=True):
        if jid.lower() in t:
            return jid
    m = re.search(r"\bjob[-_ ]?(\d+)\b", t)
    if m:
        needle = m.group(1)
        for jid in catalog.job_ids:
            if jid.endswith(needle) or needle in jid:
                return jid
    return None


def _guess_link(t: str, catalog: Optional[WorldCatalog]) -> Optional[str]:
    for keys, lid in LINK_ALIASES:
        if all(k in t for k in keys):
            if not catalog or lid in catalog.link_ids:
                return lid
    if catalog:
        compact = re.sub(r"[^a-z0-9]+", "", t)
        for lid in sorted(catalog.link_ids):
            token = lid.replace("link-", "").replace("-", " ")
            if token in t:
                return lid
            if re.sub(r"[^a-z0-9]+", "", lid.replace("link-", "")) in compact:
                return lid
    return None
