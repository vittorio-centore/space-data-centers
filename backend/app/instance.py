"""Single-process WAL ownership. This service is not a cluster.

A second process that points at the same SQLite file must not write.
``InstanceGuard`` takes an exclusive flock on ``<db_path>.owner.lock``.
Disable only with ``SDC_INSTANCE_LOCK=0`` (unsupported multi-writer).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore


class InstanceGuard:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.lock_path = Path(str(self.db_path) + ".owner.lock")
        self._fd: Optional[Any] = None
        self.held = False

    def acquire(self) -> bool:
        if fcntl is None:
            # Windows / missing fcntl: documented single-instance; do not pretend to lock.
            self.held = True
            return True
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = open(self.lock_path, "a+")
        try:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._fd.close()
            self._fd = None
            self.held = False
            return False
        self._fd.seek(0)
        self._fd.truncate()
        self._fd.write(
            json.dumps({"pid": os.getpid(), "role": "wal_owner", "db": str(self.db_path)}) + "\n"
        )
        self._fd.flush()
        self.held = True
        return True

    def release(self) -> None:
        if self._fd is None:
            self.held = False
            return
        if fcntl is not None:
            try:
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            self._fd.close()
        except OSError:
            pass
        self._fd = None
        self.held = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "single_instance": True,
            "cluster": False,
            "lock_path": str(self.lock_path),
            "held": self.held,
            "role": "wal_owner" if self.held else "blocked",
        }
