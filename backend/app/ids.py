"""Deterministic sequential identifiers (no random UUIDs in product mode)."""

from __future__ import annotations


class IdSeq:
    def __init__(self, start: int = 0):
        self.n = int(start)

    def next(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}-{self.n:08d}"

    def peek(self) -> int:
        return self.n
