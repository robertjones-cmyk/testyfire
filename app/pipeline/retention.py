"""Retention job.

* frames older than ``retention.frames_hours`` (default 48 h) are deleted from
  disk and from the database;
* frames attached to a confirmed event are **pinned**: they are kept with the
  event and deleted with it;
* audit entries, login attempts and dispatch logs older than
  ``retention.logs_days`` (default 30) are deleted;
* expired sessions are purged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import db
from ..security.auth import purge_expired_sessions

log = logging.getLogger("torch.retention")


def run_retention(config) -> dict[str, int]:
    frames_hours = int(config.get("retention.frames_hours", 48))
    logs_days = int(config.get("retention.logs_days", 30))
    now = datetime.now(timezone.utc)
    frame_cutoff = (now - timedelta(hours=frames_hours)).isoformat()
    log_cutoff = (now - timedelta(days=logs_days)).isoformat()

    # Frames: pinned ones belong to an event and are kept with it.
    stale = db.query(
        "SELECT id, path FROM frames WHERE ts < ? AND pinned = 0 LIMIT 5000",
        (frame_cutoff,),
    )
    removed_files = 0
    for row in stale:
        try:
            Path(row["path"]).unlink(missing_ok=True)
            removed_files += 1
        except OSError as exc:
            log.warning("could not delete frame %s: %s", row["id"], exc)
    if stale:
        db.execute(
            f"DELETE FROM frames WHERE id IN ({','.join('?' for _ in stale)})",
            [row["id"] for row in stale],
        )

    audit_cursor = db.execute("DELETE FROM audit_log WHERE ts < ?", (log_cutoff,))
    attempts_cursor = db.execute("DELETE FROM login_attempts WHERE ts < ?", (log_cutoff,))
    dispatch_cursor = db.execute("DELETE FROM dispatch_log WHERE ts < ?", (log_cutoff,))
    sessions = purge_expired_sessions()

    stats = {
        "frames_deleted": len(stale),
        "frame_files_deleted": removed_files,
        "audit_deleted": audit_cursor.rowcount or 0,
        "login_attempts_deleted": attempts_cursor.rowcount or 0,
        "dispatch_log_deleted": dispatch_cursor.rowcount or 0,
        "sessions_purged": sessions,
    }
    if any(stats.values()):
        log.info("retention: %s", stats)
    return stats


def delete_event_with_frames(event_id: int) -> None:
    """Deleting an event also deletes the imagery kept for it."""
    rows = db.query("SELECT frame_id FROM events WHERE id = ? AND frame_id IS NOT NULL", (event_id,))
    for row in rows:
        frame = db.query_one("SELECT path FROM frames WHERE id = ?", (row["frame_id"],))
        if frame:
            Path(frame["path"]).unlink(missing_ok=True)
            db.execute("DELETE FROM frames WHERE id = ?", (row["frame_id"],))
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
