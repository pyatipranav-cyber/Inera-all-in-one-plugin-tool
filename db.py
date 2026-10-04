"""SQLite storage layer (WAL mode, one short-lived connection per call)."""
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

import config

_init_lock = threading.Lock()
_initialized = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    pw_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    profile_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL,
    ip TEXT, ua TEXT
);
CREATE TABLE IF NOT EXISTS secrets (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    data_enc TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, kind)
);
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    origin TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'file',
    label TEXT,
    job_id TEXT,
    public_token TEXT,
    public_expires REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_files_token ON files(public_token);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL DEFAULT '{}',
    log_json TEXT NOT NULL DEFAULT '[]',
    outputs_json TEXT NOT NULL DEFAULT '[]',
    state_json TEXT NOT NULL DEFAULT '{}',
    input_ids_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    progress REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    automation_id TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id, created_at);
CREATE TABLE IF NOT EXISTS automations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    problem TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    schedule_json TEXT NOT NULL,
    timezone TEXT NOT NULL,
    input_ids_json TEXT NOT NULL DEFAULT '[]',
    state_json TEXT NOT NULL DEFAULT '{}',
    next_run_at REAL,
    last_run_at REAL,
    last_status TEXT,
    last_job_id TEXT,
    run_count INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    approved INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auto_due ON automations(enabled, next_run_at);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init() -> None:
    global _initialized
    with _init_lock:
        if _initialized:
            return
        conn = _connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
        _initialized = True


@contextmanager
def tx():
    init()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:20]


def row_to_dict(row) -> dict:
    return dict(row) if row is not None else None


def query(sql: str, params=()) -> list:
    with tx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def query_one(sql: str, params=()):
    with tx() as c:
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None


def execute(sql: str, params=()) -> int:
    with tx() as c:
        cur = c.execute(sql, params)
        return cur.rowcount


def jload(text, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


# ------------------------------------------------------------------ users
def get_user(user_id: str):
    u = query_one("SELECT * FROM users WHERE id=?", (user_id,))
    if u:
        u["profile"] = jload(u.pop("profile_json"), {})
    return u


def get_user_by_email(email: str):
    u = query_one("SELECT * FROM users WHERE email=?", (email.lower().strip(),))
    if u:
        u["profile"] = jload(u.pop("profile_json"), {})
    return u


def count_users() -> int:
    return query_one("SELECT COUNT(*) AS n FROM users")["n"]


def now() -> float:
    return time.time()
