"""SQLite WAL persistence for sim world state."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, job_id TEXT, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_revisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT, job_id TEXT, revision INTEGER, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transfers (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS link_reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, t REAL, seq INTEGER, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evaluations (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outages (node_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
"""


class SqliteStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def set_meta(self, k: str, v: Any) -> None:
        self.conn.execute(
            "INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, json.dumps(v)),
        )
        self.conn.commit()

    def get_meta(self, k: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        if not row:
            return default
        return json.loads(row[0])

    def put_job(self, job: dict) -> None:
        self.conn.execute(
            "INSERT INTO jobs(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (job["id"], json.dumps(job)),
        )
        self.conn.commit()

    def put_plan(self, plan: dict) -> None:
        self.conn.execute(
            "INSERT INTO plans(id,payload,job_id) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, job_id=excluded.job_id",
            (plan["id"], json.dumps(plan), plan.get("job_id")),
        )
        self.conn.commit()

    def add_revision(self, plan: dict) -> None:
        self.conn.execute(
            "INSERT INTO plan_revisions(plan_id,job_id,revision,payload) VALUES(?,?,?,?)",
            (plan["id"], plan.get("job_id"), plan.get("revision", 1), json.dumps(plan)),
        )
        self.conn.commit()

    def put_transfer(self, tr: dict) -> None:
        self.conn.execute(
            "INSERT INTO transfers(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (tr["id"], json.dumps(tr)),
        )
        self.conn.commit()

    def put_event(self, ev: dict) -> None:
        self.conn.execute(
            "INSERT INTO events(id,t,seq,payload) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (ev["id"], ev.get("t"), ev.get("seq", 0), json.dumps(ev)),
        )
        self.conn.commit()

    def put_evaluation(self, report: dict) -> None:
        self.conn.execute(
            "INSERT INTO evaluations(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (report["id"], json.dumps(report)),
        )
        self.conn.commit()

    def put_outage(self, node_id: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO outages(node_id,payload) VALUES(?,?) ON CONFLICT(node_id) DO UPDATE SET payload=excluded.payload",
            (node_id, json.dumps(payload)),
        )
        self.conn.commit()

    def delete_outage(self, node_id: str) -> None:
        self.conn.execute("DELETE FROM outages WHERE node_id=?", (node_id,))
        self.conn.commit()

    def replace_reservations(self, rows: list[dict], link_rows: list[dict]) -> None:
        self.conn.execute("DELETE FROM reservations")
        self.conn.execute("DELETE FROM link_reservations")
        for r in rows:
            self.conn.execute("INSERT INTO reservations(payload) VALUES(?)", (json.dumps(r),))
        for r in link_rows:
            self.conn.execute("INSERT INTO link_reservations(payload) VALUES(?)", (json.dumps(r),))
        self.conn.commit()

    def load_all(self) -> dict[str, Any]:
        def rows(table: str) -> list[dict]:
            return [json.loads(r[0]) for r in self.conn.execute(f"SELECT payload FROM {table}").fetchall()]

        return {
            "meta": {k: json.loads(v) for k, v in self.conn.execute("SELECT k,v FROM meta")},
            "jobs": rows("jobs"),
            "plans": rows("plans"),
            "transfers": rows("transfers"),
            "reservations": rows("reservations"),
            "link_reservations": rows("link_reservations"),
            "events": [json.loads(r[0]) for r in self.conn.execute("SELECT payload FROM events ORDER BY seq, t").fetchall()],
            "evaluations": rows("evaluations"),
            "outages": {r[0]: json.loads(r[1]) for r in self.conn.execute("SELECT node_id,payload FROM outages")},
            "revisions": [json.loads(r[0]) for r in self.conn.execute("SELECT payload FROM plan_revisions ORDER BY seq").fetchall()],
        }

    def list_evaluations(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.conn.execute("SELECT payload FROM evaluations").fetchall()]

    def get_evaluation(self, eid: str) -> Optional[dict]:
        row = self.conn.execute("SELECT payload FROM evaluations WHERE id=?", (eid,)).fetchone()
        return json.loads(row[0]) if row else None

    def plan_history(self, job_id: str) -> list[dict]:
        return [
            json.loads(r[0])
            for r in self.conn.execute(
                "SELECT payload FROM plan_revisions WHERE job_id=? ORDER BY seq", (job_id,)
            ).fetchall()
        ]

    def clear_runtime(self) -> None:
        for t in ("jobs", "plans", "plan_revisions", "transfers", "reservations", "link_reservations", "events", "outages"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()
