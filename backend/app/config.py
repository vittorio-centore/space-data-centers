"""Environment-driven service config."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent


class AppConfig(BaseModel):
    db_path: Path = Field(default_factory=lambda: Path(os.environ.get("SDC_DB_PATH", str(ROOT / "data" / "sdc.sqlite"))))
    scenario: str = Field(default_factory=lambda: os.environ.get("SDC_SCENARIO", "mvp-thesis"))
    headless: bool = Field(default_factory=lambda: os.environ.get("SDC_HEADLESS", "0") in ("1", "true", "yes"))
    log_json: bool = Field(default_factory=lambda: os.environ.get("SDC_LOG_JSON", "1") not in ("0", "false"))
    persist: bool = Field(default_factory=lambda: os.environ.get("SDC_PERSIST", "1") not in ("0", "false"))
    tick_fail_pause: int = Field(default_factory=lambda: int(os.environ.get("SDC_TICK_FAIL_PAUSE", "3")))
    instance_lock: bool = Field(
        default_factory=lambda: os.environ.get("SDC_INSTANCE_LOCK", "1") not in ("0", "false", "no")
    )


def load_config() -> AppConfig:
    return AppConfig()
