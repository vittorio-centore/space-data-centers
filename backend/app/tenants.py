"""Shared-sky tenancy. Not accounts, SSO, or billing.

Default-open: when no keys are configured, every HTTP request is tenant ``local``.
Seeded tenants ``alpha`` and ``beta`` still exist so a second tenant's rows cannot
be smashed by the default tenant. Optional per-tenant keys map via
``SDC_TENANT_KEYS=sdc-alpha:alpha,sdc-beta:beta``. Legacy ``API_KEY`` maps to
``local`` (or ``SDC_DEFAULT_TENANT``).
"""

from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field

DEFAULT_TENANT_ID = "local"
SEEDED_TENANT_IDS = ("local", "alpha", "beta")

# Documented demo keys (used when SDC_TENANT_KEYS is set to the demo map).
DEMO_TENANT_KEYS = {
    "sdc-alpha": "alpha",
    "sdc-beta": "beta",
}


class Tenant(BaseModel):
    id: str
    display_name: str
    api_key: Optional[str] = None
    quota_reserved_s: float = 100_000.0
    quota_outstanding_jobs: int = 64
    quota_work: float = 1_000_000.0


def default_tenant() -> str:
    return (os.environ.get("SDC_DEFAULT_TENANT") or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID


def parse_tenant_key_map(raw: Optional[str] = None) -> dict[str, str]:
    """Return API key → tenant_id. Env plus legacy API_KEY → default tenant."""
    text = raw if raw is not None else (os.environ.get("SDC_TENANT_KEYS") or "")
    out: dict[str, str] = {}
    for part in text.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, tid = part.split(":", 1)
        key, tid = key.strip(), tid.strip()
        if key and tid:
            out[key] = tid
    legacy = (os.environ.get("API_KEY") or "").strip()
    if legacy and legacy not in out:
        out[legacy] = default_tenant()
    return out


def tenant_auth_required() -> bool:
    return bool(parse_tenant_key_map())


def tenant_for_key(provided: str, key_map: Optional[dict[str, str]] = None) -> Optional[str]:
    keys = key_map if key_map is not None else parse_tenant_key_map()
    if not keys:
        return default_tenant()
    if not provided:
        return None
    return keys.get(provided)


def seed_tenants(key_map: Optional[dict[str, str]] = None) -> dict[str, Tenant]:
    keys = key_map if key_map is not None else parse_tenant_key_map()
    inverse = {tid: key for key, tid in keys.items()}
    names = {
        "local": "Local default (open when keys unset)",
        "alpha": "Tenant alpha",
        "beta": "Tenant beta",
    }
    tenants: dict[str, Tenant] = {}
    for tid in SEEDED_TENANT_IDS:
        tenants[tid] = Tenant(
            id=tid,
            display_name=names.get(tid, tid),
            api_key=inverse.get(tid),
        )
    for tid in set(keys.values()):
        if tid not in tenants:
            tenants[tid] = Tenant(id=tid, display_name=tid, api_key=inverse.get(tid))
    return tenants
