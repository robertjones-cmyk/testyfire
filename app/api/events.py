"""Events (what the UI calls alerts)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from .. import db
from ..audit import record as audit_record
from .deps import client_ip, require_operator, require_session

router = APIRouter(prefix="/api/events", tags=["events"])

STATUS_LABELS = {
    "possible_smoke": "Possible smoke",
    "verified": "Verified",
    "sensor_only": "Sensor only",
}


def _event_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["bbox"] = json.loads(row["bbox"]) if row["bbox"] else None
    data["status_label"] = STATUS_LABELS.get(row["status"], row["status"])
    if row["camera_key"]:
        camera = db.query_one("SELECT name FROM cameras WHERE key = ?", (row["camera_key"],))
        data["camera_name"] = camera["name"] if camera else row["camera_key"]
    if row["sensor_id"]:
        sensor = db.query_one("SELECT name FROM sensors WHERE id = ?", (row["sensor_id"],))
        data["sensor_name"] = sensor["name"] if sensor else row["sensor_id"]
    return data


@router.get("")
def list_events(
    session: dict = Depends(require_session),
    status_filter: str | None = Query(None, alias="status"),
    category: str | None = None,
    severity: str | None = None,
    camera_key: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(200, le=1000),
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    if camera_key:
        clauses.append("camera_key = ?")
        params.append(camera_key)
    if since:
        clauses.append("ts >= ?")
        params.append(since)
    if until:
        clauses.append("ts <= ?")
        params.append(until)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = db.query(f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?", params)
    return {"events": [_event_dict(row) for row in rows], "count": len(rows)}


@router.get("/{event_id}")
def get_event(event_id: int, session: dict = Depends(require_session)) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    data = _event_dict(row)

    if row["confirming_reading_id"]:
        reading = db.query_one("SELECT * FROM sensor_readings WHERE id = ?", (row["confirming_reading_id"],))
        data["confirming_reading"] = dict(reading) if reading else None
    if row["sensor_id"]:
        data["sensor_history"] = db.rows_to_dicts(db.query(
            "SELECT ts, temp_c, smoke_index, thermal_delta_c, thermal_hotspot, audio_event, battery"
            " FROM sensor_readings WHERE sensor_id = ? ORDER BY id DESC LIMIT 30",
            (row["sensor_id"],),
        ))
    if row["camera_key"]:
        data["frame_strip"] = db.rows_to_dicts(db.query(
            "SELECT id, ts, score, view_changed FROM frames WHERE camera_key = ?"
            " ORDER BY id DESC LIMIT 10",
            (row["camera_key"],),
        ))
    data["dispatch_attempts"] = db.rows_to_dicts(db.query(
        "SELECT ts, url, attempt, status_code, ok, error FROM dispatch_log"
        " WHERE event_id = ? ORDER BY id",
        (event_id,),
    ))
    data["timeline"] = _timeline(row, data)
    return data


def _timeline(row: Any, data: dict[str, Any]) -> list[dict[str, str]]:
    steps = [{"ts": row["ts"], "text": f"Detected — {STATUS_LABELS.get(row['status'], row['status'])}"}]
    if row["status"] == "verified" and row["confirmation_detail"]:
        steps.append({"ts": row["updated_at"], "text": f"Upgraded to Verified. {row['confirmation_detail']}"})
    if row["dispatched_at"]:
        steps.append({"ts": row["dispatched_at"], "text": "Dispatched to webhook"})
    if row["human_at"]:
        label = "Real" if row["human_label"] == "real" else "False alarm"
        steps.append({"ts": row["human_at"], "text": f"Marked {label} by {row['human_by']}"})
    return steps


class DecisionRequest(BaseModel):
    label: Literal["real", "false_alarm"]
    note: str | None = None


@router.post("/{event_id}/decision")
def record_decision(
    event_id: int,
    payload: DecisionRequest,
    request: Request,
    session: dict = Depends(require_operator),
) -> dict[str, Any]:
    """Operator marks an event Real or False alarm. Written to the audit log."""
    row = db.query_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "UPDATE events SET human_label = ?, human_by = ?, human_at = ?, updated_at = ?,"
        " notes = COALESCE(?, notes) WHERE id = ?",
        (payload.label, session["email"], now, now, (payload.note or None), event_id),
    )
    audit_record(
        "event.decision",
        actor_email=session["email"],
        actor_role=session["role"],
        target=f"event:{event_id}",
        detail={"label": payload.label, "previous_status": row["status"]},
        ip=client_ip(request),
    )
    return {"event_id": event_id, "label": payload.label, "recorded_at": now}
