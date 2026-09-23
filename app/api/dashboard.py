"""Dashboard: kill-criteria metrics, blind-spot summary, feed list, map config."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from .. import db, metrics
from ..config import get_config
from ..geo import blindspot
from .deps import require_session

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/metrics/today")
def metrics_today(session: dict = Depends(require_session), day: str | None = None) -> dict[str, Any]:
    config = get_config()
    return {
        "totals": metrics.totals(config, day),
        "per_camera": metrics.per_camera_day(config, day),
    }


@router.get("/metrics/history")
def metrics_history(session: dict = Depends(require_session), days: int = Query(7, le=30)) -> dict[str, Any]:
    return {"history": metrics.history(get_config(), days)}


@router.get("/metrics/daily.csv")
def metrics_csv(session: dict = Depends(require_session), day: str | None = None) -> Response:
    csv_text = metrics.daily_csv(get_config(), day)
    filename = f"torch-kill-criteria-{day or metrics.today_utc()}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/blindspot")
def get_blindspot(session: dict = Depends(require_session), refresh: bool = False) -> dict[str, Any]:
    report = blindspot.build(get_config(), refresh=refresh)
    # The CSV is served separately; keep the JSON payload lean.
    return {
        "summary": report["summary"],
        "geojson": report["geojson"],
        "proposals": report["proposals"],
        "accuracy_note": report["accuracy_note"],
    }


@router.get("/blindspot/proposals.csv")
def blindspot_csv(session: dict = Depends(require_session)) -> Response:
    report = blindspot.build(get_config())
    return Response(
        content=report["csv"],
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="torch-proposed-sensors.csv"'},
    )


@router.get("/feeds")
def list_feeds(session: dict = Depends(require_session)) -> dict[str, Any]:
    """Read-only feed list for Settings: type, camera count, last success, errors."""
    config = get_config()
    health = {row["feed_id"]: dict(row) for row in db.query("SELECT * FROM feed_health")}
    out: list[dict[str, Any]] = []
    for entry in config.feeds():
        feed_id = str(entry.get("id"))
        record = health.get(feed_id, {})
        out.append({
            "id": feed_id,
            "type": entry.get("type"),
            "enabled": bool(entry.get("enabled", True)),
            "interval_s": entry.get("interval_s"),
            "camera_count": record.get("camera_count", 0),
            "reachable": bool(record.get("reachable", 0)),
            "last_success": record.get("last_success"),
            "error_count": record.get("error_count", 0),
            # Already redacted when it was written.
            "last_error": record.get("last_error"),
        })
    return {"feeds": out}


@router.get("/config/ui")
def ui_config(session: dict = Depends(require_session)) -> dict[str, Any]:
    """Non-secret settings the frontend needs.

    The Mapbox token here must be a **public** ``pk.`` token. A secret ``sk.``
    token is refused rather than shipped to a browser.
    """
    config = get_config()
    token = os.environ.get("MAPBOX_TOKEN", "")
    token_problem = ""
    if token.startswith("sk."):
        token_problem = "MAPBOX_TOKEN is a SECRET sk. token — refusing to send it to the browser. Use a pk. token."
        token = ""
    elif not token:
        token_problem = "MAPBOX_TOKEN is not set — the map will show a placeholder."

    return {
        "app_name": config.get("app.name"),
        "map": {
            "token": token,
            "token_problem": token_problem,
            "style": config.get("map.style"),
            "center": config.get("map.center"),
            "zoom": config.get("map.zoom"),
        },
        "thresholds": {
            "score": config.get("detection.score_threshold"),
            "kill_criteria": config.get("kill_criteria"),
        },
        "session": {
            "idle_timeout_minutes": config.get("app.session.idle_timeout_minutes"),
            "idle_warning_seconds": config.get("app.session.idle_warning_seconds"),
        },
        "dispatch": {
            "enabled": bool(config.get("dispatch.enabled", False)),
            "using_test_receiver": bool(config.get("dispatch.local_test_receiver.enabled", True)),
        },
        "role": session.get("role"),
    }
