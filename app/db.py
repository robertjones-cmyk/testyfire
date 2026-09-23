"""SQLite storage.

Every statement in this codebase is parameterised — no string-built SQL. The
connection is opened per-thread with WAL enabled so the ingest worker and the
API can run concurrently.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

_LOCAL = threading.local()
_DB_PATH: Path | None = None

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('viewer','operator','admin')),
    created_at    TEXT NOT NULL,
    disabled      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    ip          TEXT,
    user_agent  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS login_attempts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    email   TEXT,
    ip      TEXT,
    ts      TEXT NOT NULL,
    success INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ts ON login_attempts(ts);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    actor_email TEXT,
    actor_role  TEXT,
    action      TEXT NOT NULL,
    target      TEXT,
    detail      TEXT,
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS cameras (
    key          TEXT PRIMARY KEY,
    feed_id      TEXT NOT NULL,
    camera_id    TEXT NOT NULL,
    name         TEXT NOT NULL,
    lat          REAL,
    lon          REAL,
    heading      REAL,
    fov          REAL,
    mast_height  REAL,
    is_ptz       INTEGER NOT NULL DEFAULT 0,
    source       TEXT,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cameras_feed ON cameras(feed_id);

CREATE TABLE IF NOT EXISTS frames (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_key    TEXT NOT NULL,
    ts            TEXT NOT NULL,
    path          TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    width         INTEGER,
    height        INTEGER,
    view_changed  INTEGER NOT NULL DEFAULT 0,
    phash         TEXT,
    score         REAL,
    detector      TEXT,
    bbox          TEXT,
    inference_ms  REAL,
    cost_usd      REAL NOT NULL DEFAULT 0,
    pinned        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_frames_cam_ts ON frames(camera_key, ts);

CREATE TABLE IF NOT EXISTS ingest_failures (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_key TEXT NOT NULL,
    feed_id    TEXT,
    ts         TEXT NOT NULL,
    error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_failures_ts ON ingest_failures(camera_key, ts);

CREATE TABLE IF NOT EXISTS camera_reference (
    camera_key       TEXT PRIMARY KEY,
    phash            TEXT NOT NULL,
    frame_id         INTEGER,
    updated_at       TEXT NOT NULL,
    candidate_phash  TEXT,
    candidate_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sensors (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    source     TEXT NOT NULL,
    battery    REAL,
    last_seen  TEXT
);

CREATE TABLE IF NOT EXISTS sensor_readings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id        TEXT NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    ts               TEXT NOT NULL,
    temp_c           REAL,
    thermal_hotspot  INTEGER NOT NULL DEFAULT 0,
    thermal_delta_c  REAL,
    smoke_index      REAL,
    audio_event      INTEGER NOT NULL DEFAULT 0,
    battery          REAL,
    demo             INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_readings_sensor_ts ON sensor_readings(sensor_id, ts);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON sensor_readings(ts);

CREATE TABLE IF NOT EXISTS events (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('possible_smoke','verified','sensor_only')),
    category              TEXT NOT NULL DEFAULT 'Fire',
    severity              TEXT NOT NULL DEFAULT 'Warning',
    camera_key            TEXT,
    frame_id              INTEGER,
    score                 REAL,
    bbox                  TEXT,
    sensor_id             TEXT,
    confirming_reading_id INTEGER,
    confirmation_detail   TEXT,
    human_label           TEXT CHECK (human_label IN ('real','false_alarm') OR human_label IS NULL),
    human_by              TEXT,
    human_at              TEXT,
    demo                  INTEGER NOT NULL DEFAULT 0,
    dispatched_at         TEXT,
    notes                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);

CREATE TABLE IF NOT EXISTS dispatch_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    ts          TEXT NOT NULL,
    url         TEXT NOT NULL,
    attempt     INTEGER NOT NULL,
    status_code INTEGER,
    ok          INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS llm_spend (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL NOT NULL,
    frame_id      INTEGER,
    verdict       TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_spend_ts ON llm_spend(ts);

CREATE TABLE IF NOT EXISTS feed_health (
    feed_id      TEXT PRIMARY KEY,
    ts           TEXT NOT NULL,
    reachable    INTEGER NOT NULL DEFAULT 0,
    last_success TEXT,
    error_count  INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    camera_count INTEGER NOT NULL DEFAULT 0,
    enabled      INTEGER NOT NULL DEFAULT 1,
    type         TEXT
);
"""


def configure(db_path: str | Path) -> None:
    """Point the module at a database file (call once at start-up)."""
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(_LOCAL, "conn"):
        try:
            _LOCAL.conn.close()
        finally:
            del _LOCAL.conn


def connect() -> sqlite3.Connection:
    """Per-thread connection."""
    if _DB_PATH is None:
        raise RuntimeError("db.configure() must be called before db.connect()")
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(_DB_PATH), timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        _LOCAL.conn = conn
    return conn


def init_db() -> None:
    connect().executescript(SCHEMA)


def query(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return list(connect().execute(sql, tuple(params)).fetchall())


def query_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    return connect().execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    return connect().execute(sql, tuple(params))


def execute_many(sql: str, rows: Iterable[Sequence[Any]]) -> None:
    connect().executemany(sql, [tuple(r) for r in rows])


def insert(sql: str, params: Sequence[Any] = ()) -> int:
    cursor = connect().execute(sql, tuple(params))
    return int(cursor.lastrowid or 0)


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
