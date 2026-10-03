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


def parse_offline(text: str, catalog: Optional[WorldCatalog] = None) -> list[dict[str, Any]]:
    """Return raw tool calls from a spoken or typed phrase."""
    t = (text or "").strip().lower()
    if not t:
        return []

    if re.search(r"\b(case\s*b|thesis\s*b|cheap\s+wins)\b", t):
        return [{"tool": "submit_job", "args": {"preset": "b"}}]
    if re.search(r"\b(case\s*a|thesis\s*a|cheap\s+loses)\b", t):
        return [{"tool": "submit_job", "args": {"preset": "a"}}]

    if re.search(r"\b(clear|restore|undisrupt|bring\s+up)\b.+\b(link|contact)\b", t) or re.search(
        r"\b(clear|restore)\s+(the\s+)?(disruption|link)\b", t
    ):
        link_id = _guess_link(t, catalog)
        if link_id:
            return [{"tool": "disrupt_link", "args": {"link_id": link_id, "action": "clear"}}]
        return [{"tool": "read_state", "args": {"focus": "links"}}]

    if re.search(r"\b(disrupt|drop|take\s+down|force\s+down|cut)\b", t) and re.search(
        r"\b(link|contact|iss|css|noaa|ashburn|madrid|terrestrial)\b", t
    ):
        link_id = _guess_link(t, catalog)
        if link_id:
            return [{"tool": "disrupt_link", "args": {"link_id": link_id, "action": "down"}}]
        return [{"tool": "read_state", "args": {"focus": "links"}}]

    if re.search(r"\b(explain|why|plan|route|baseline)\b", t):
        job_id = _guess_job(t, catalog)
        args: dict[str, Any] = {}
        if job_id:
            args["job_id"] = job_id
        return [{"tool": "explain_plan", "args": args}]

    if re.search(r"\b(submit|place|run)\b.+\b(job|batch)\b", t) or re.search(
        r"\b(new\s+job|place\s+a\s+job|submit\s+a\s+job)\b", t
    ):
        return [{"tool": "submit_job", "args": _job_args_from_text(t)}]

    if re.search(r"\b(play|resume|start|unpause)\b", t) and not re.search(r"\b(job|case)\b", t):
        return [{"tool": "play", "args": {}}]

    if re.search(r"\b(pause|stop|halt)\b", t) and not re.search(r"\b(job)\b", t):
        return [{"tool": "pause", "args": {}}]

    if re.search(r"\b(status|state|what('s| is)\s+happening|how\s+many|snapshot|overview)\b", t):
        return [{"tool": "read_state", "args": {"focus": "all"}}]

    if re.search(r"\b(submit|place)\b", t):
        return [{"tool": "submit_job", "args": _job_args_from_text(t)}]

    return [{"tool": "read_state", "args": {"focus": "all"}}]


def _job_args_from_text(t: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    m = re.search(r"(\d+(?:\.\d+)?)\s*mb\s+(input|in)", t)
    if m:
        args["input_bytes"] = int(float(m.group(1)) * 1_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*mb\s+(output|out)", t)
    if m:
        args["output_bytes"] = int(float(m.group(1)) * 1_000_000)
    if "madrid" in t and "source" in t:
        args["source_id"] = "gs-madrid"
    if "madrid" in t and "destination" in t:
        args["destination_id"] = "gs-madrid"
    return args


def _guess_job(t: str, catalog: Optional[WorldCatalog]) -> Optional[str]:
    if not catalog:
        return None
    for jid in catalog.job_ids:
        if jid.lower() in t:
            return jid
    return None


def _guess_link(t: str, catalog: Optional[WorldCatalog]) -> Optional[str]:
    for keys, lid in LINK_ALIASES:
        if all(k in t for k in keys):
            if not catalog or lid in catalog.link_ids:
                return lid
    if catalog:
        for lid in sorted(catalog.link_ids):
            token = lid.replace("link-", "").replace("-", " ")
            if token in t:
                return lid
            short = lid.split("-")[-1]
            if short and short in t and lid in catalog.link_ids:
                # too loose; skip single token
                continue
    return None
