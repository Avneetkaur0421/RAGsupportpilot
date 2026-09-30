"""Plain SQLite for everything that isn't vectors: question logs, the
review queue, and documents added from the UI. Standard library only."""
import json
import sqlite3
import time
import uuid

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
  id TEXT PRIMARY KEY, question TEXT, audience TEXT, topic TEXT,
  confidence TEXT, status TEXT, sources TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, question TEXT, audience TEXT, topic TEXT, draft TEXT,
  missing TEXT, status TEXT, reply TEXT, created_at REAL, resolved_at REAL);
CREATE TABLE IF NOT EXISTS added_docs (
  id TEXT PRIMARY KEY, title TEXT, audience TEXT, markdown TEXT, created_at REAL);
"""


def _conn():
    config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.SQLITE_PATH)
    con.row_factory = sqlite3.Row
    return con


def init():
    with _conn() as con:
        con.executescript(SCHEMA)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def add_log(question, audience, topic, confidence, status, sources):
    with _conn() as con:
        con.execute("INSERT INTO logs VALUES (?,?,?,?,?,?,?,?)",
                    (new_id(), question, audience, topic, confidence, status,
                     json.dumps(sources), time.time()))


def add_review(question, audience, topic, draft, missing) -> str:
    rid = new_id()
    with _conn() as con:
        con.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (rid, question, audience, topic, draft, missing, "open", None, time.time(), None))
    return rid


def list_reviews() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM reviews ORDER BY status = 'resolved', created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_review(rid: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM reviews WHERE id = ?", (rid,)).fetchone()
    return dict(row) if row else None


def resolve_review(rid: str, reply: str) -> None:
    with _conn() as con:
        con.execute("UPDATE reviews SET status='resolved', reply=?, resolved_at=? WHERE id=?",
                    (reply, time.time(), rid))


def list_logs() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM logs ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"] or "[]")
        out.append(d)
    return out


def add_doc(title, audience, markdown) -> str:
    did = new_id()
    with _conn() as con:
        con.execute("INSERT INTO added_docs VALUES (?,?,?,?,?)", (did, title, audience, markdown, time.time()))
    return did
