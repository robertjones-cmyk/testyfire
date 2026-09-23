"""Torch sensors and their readings."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import db
from ..config import get_config
from .deps import require_session

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


def _status_for(row: Any, smoke_threshold: float, thermal_threshold: float) -> str:
    if row["smoke_index"] is None:
        return "unknown"
    if float(row["smoke_index"]) >= smoke_threshold or row["thermal_hotspot"]:
        return "alarm"
    if float(row["smoke_index"]) >= smoke_threshold * 0.5:
        return "elevated"
    return "nominal"


@router.get("")
def list_sensors(session: dict = Depends(require_session)) -> dict[str, Any]:
    config = get_config()
    smoke_threshold = float(config.get("sensors.thresholds.smoke_index", 60.0))
    thermal_threshold = float(config.get("sensors.thresholds.thermal_delta_c", 8.0))

    out: list[dict[str, Any]] = []
    for sensor in db.query("SELECT * FROM sensors ORDER BY id"):
        latest = db.query_one(
            "SELECT * FROM sensor_readings WHERE sensor_id = ? ORDER BY id DESC LIMIT 1",
            (sensor["id"],),
        )
        data = dict(sensor)
        data["latest"] = dict(latest) if latest else None
        data["status"] = _status_for(latest, smoke_threshold, thermal_threshold) if latest else "unknown"
        out.append(data)
    return {
        "sensors": out,
        "thresholds": {"smoke_index": smoke_threshold, "thermal_delta_c": thermal_threshold},
    }


@router.get("/{sensor_id}")
def get_sensor(
    sensor_id: str,
    session: dict = Depends(require_session),
    limit: int = Query(60, le=500),
) -> dict[str, Any]:
    sensor = db.query_one("SELECT * FROM sensors WHERE id = ?", (sensor_id,))
    if sensor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sensor not found")
    readings = db.rows_to_dicts(db.query(
        "SELECT * FROM sensor_readings WHERE sensor_id = ? ORDER BY id DESC LIMIT ?",
        (sensor_id, limit),
    ))
    data = dict(sensor)
    data["readings"] = list(reversed(readings))
    data["latest"] = readings[0] if readings else None
    return data
