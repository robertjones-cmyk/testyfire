"""Kill-criteria metrics.

Per camera per day:

* frames ingested / frames failed
* view changes
* ``possible_smoke`` alerts, and how many a human marked a false alarm
* ``verified`` alerts
* average inference cost per frame, and total cost

A camera is flagged **red** when false alarms needing a human exceed
``kill_criteria.max_false_alarms_per_camera_per_day`` (default 3) or view
changes exceed ``max_view_changes_per_camera_per_day`` (default 10). Both
thresholds live in config.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import db


def _day_bounds(day: str) -> tuple[str, str]:
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def per_camera_day(config, day: str | None = None) -> list[dict[str, Any]]:
    """One row per camera for ``day`` (UTC, ``YYYY-MM-DD``)."""
    day = day or today_utc()
    low, high = _day_bounds(day)
    max_false = int(config.get("kill_criteria.max_false_alarms_per_camera_per_day", 3))
    max_changes = int(config.get("kill_criteria.max_view_changes_per_camera_per_day", 10))
    target_cost = float(config.get("kill_criteria.target_cost_per_frame_usd", 0.001))

    rows: list[dict[str, Any]] = []
    for camera in db.query("SELECT key, name, feed_id FROM cameras ORDER BY name"):
        key = camera["key"]
        frames = db.query_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(view_changed),0) AS changes,"
            " COALESCE(SUM(cost_usd),0) AS cost, COALESCE(AVG(inference_ms),0) AS ms"
            " FROM frames WHERE camera_key = ? AND ts >= ? AND ts < ?",
            (key, low, high),
        )
        failures = db.query_one(
            "SELECT COUNT(*) AS n FROM ingest_failures WHERE camera_key = ? AND ts >= ? AND ts < ?",
            (key, low, high),
        )
        events = db.query_one(
            "SELECT"
            "  COALESCE(SUM(status = 'possible_smoke'), 0) AS possible,"
            "  COALESCE(SUM(status = 'verified'), 0) AS verified,"
            "  COALESCE(SUM(human_label = 'false_alarm'), 0) AS false_alarms,"
            "  COALESCE(SUM(human_label = 'real'), 0) AS real_alarms"
            " FROM events WHERE camera_key = ? AND ts >= ? AND ts < ?",
            (key, low, high),
        )

        ingested = int(frames["n"]) if frames else 0
        total_cost = float(frames["cost"]) if frames else 0.0
        view_changes = int(frames["changes"]) if frames else 0
        false_alarms = int(events["false_alarms"]) if events else 0

        red_reasons: list[str] = []
        if false_alarms > max_false:
            red_reasons.append(f"{false_alarms} false alarms needing a human (limit {max_false})")
        if view_changes > max_changes:
            red_reasons.append(f"{view_changes} view changes (limit {max_changes})")

        rows.append({
            "day": day,
            "camera_key": key,
            "camera_name": camera["name"],
            "feed_id": camera["feed_id"],
            "frames_ingested": ingested,
            "frames_failed": int(failures["n"]) if failures else 0,
            "view_changes": view_changes,
            "possible_smoke_alerts": int(events["possible"]) if events else 0,
            "verified_alerts": int(events["verified"]) if events else 0,
            "marked_false_alarm": false_alarms,
            "marked_real": int(events["real_alarms"]) if events else 0,
            "avg_inference_ms": round(float(frames["ms"]) if frames else 0.0, 2),
            "avg_cost_per_frame_usd": round(total_cost / ingested, 8) if ingested else 0.0,
            "total_cost_usd": round(total_cost, 6),
            "cost_target_met": (total_cost / ingested if ingested else 0.0) <= target_cost,
            "red": bool(red_reasons),
            "red_reasons": red_reasons,
        })
    return rows


def totals(config, day: str | None = None) -> dict[str, Any]:
    rows = per_camera_day(config, day)
    ingested = sum(r["frames_ingested"] for r in rows)
    cost = sum(r["total_cost_usd"] for r in rows)
    possible = sum(r["possible_smoke_alerts"] for r in rows)
    false_alarms = sum(r["marked_false_alarm"] for r in rows)
    return {
        "day": day or today_utc(),
        "cameras": len(rows),
        "frames_ingested": ingested,
        "frames_failed": sum(r["frames_failed"] for r in rows),
        "view_changes": sum(r["view_changes"] for r in rows),
        "possible_smoke_alerts": possible,
        "verified_alerts": sum(r["verified_alerts"] for r in rows),
        "sensor_only_alerts": _sensor_only_count(day),
        "marked_false_alarm": false_alarms,
        "marked_real": sum(r["marked_real"] for r in rows),
        "false_alarm_rate": round(false_alarms / possible, 3) if possible else 0.0,
        "avg_cost_per_frame_usd": round(cost / ingested, 8) if ingested else 0.0,
        "total_cost_usd": round(cost, 6),
        "cost_target_usd": float(config.get("kill_criteria.target_cost_per_frame_usd", 0.001)),
        "red_cameras": [r["camera_name"] for r in rows if r["red"]],
        "thresholds": {
            "max_false_alarms_per_camera_per_day": int(
                config.get("kill_criteria.max_false_alarms_per_camera_per_day", 3)
            ),
            "max_view_changes_per_camera_per_day": int(
                config.get("kill_criteria.max_view_changes_per_camera_per_day", 10)
            ),
        },
    }


def _sensor_only_count(day: str | None) -> int:
    low, high = _day_bounds(day or today_utc())
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM events WHERE status = 'sensor_only' AND ts >= ? AND ts < ?",
        (low, high),
    )
    return int(row["n"]) if row else 0


CSV_COLUMNS = [
    "day", "camera_key", "camera_name", "feed_id", "frames_ingested", "frames_failed",
    "view_changes", "possible_smoke_alerts", "marked_false_alarm", "marked_real",
    "verified_alerts", "avg_inference_ms", "avg_cost_per_frame_usd", "total_cost_usd",
    "red", "red_reasons",
]


def daily_csv(config, day: str | None = None) -> str:
    """The daily kill-criteria CSV."""
    rows = per_camera_day(config, day)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        record = dict(row)
        record["red_reasons"] = "; ".join(row["red_reasons"])
        writer.writerow(record)
    return buffer.getvalue()


def history(config, days: int = 7) -> list[dict[str, Any]]:
    today = date.fromisoformat(today_utc())
    return [
        totals(config, (today - timedelta(days=offset)).isoformat())
        for offset in range(days - 1, -1, -1)
    ]
