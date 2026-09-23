"""Fusion engine — camera score + Torch sensor agreement.

The product rule this module exists to enforce:

======================  ==========================================  ===========
status                  how it is reached                           dispatched?
======================  ==========================================  ===========
``possible_smoke``      a camera frame scored above threshold       **no**
``verified``            …and a Torch sensor in that camera's view    **yes**
                        agreed within ±10 minutes
``sensor_only``         a sensor anomaly no camera corroborated      **yes**
======================  ==========================================  ===========

``possible_smoke`` never leaves the dashboard. ``sensor_only`` *does* dispatch,
because sensors see things cameras cannot — smoke at night, gas, a hotspot
behind a ridge. Do not change this without a product decision.

A sensor counts as "in view" if it is inside the camera's view polygon **or**
within ``fusion.sensor_match_radius_m`` of the camera. Cameras with no known
heading get a 360° disc, and the UI flags those as approximate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .. import db
from ..geo.geom import haversine_m, point_in_polygon, view_cone

DISPATCHABLE_STATUSES = ("verified", "sensor_only")
CAMERA_ONLY_STATUS = "possible_smoke"


@dataclass(slots=True)
class CameraView:
    """A camera's approximate footprint on the ground."""

    key: str
    name: str
    lat: float
    lon: float
    heading: float | None
    fov: float | None
    range_m: float
    heading_known: bool

    @property
    def polygon(self) -> list[list[float]]:
        return view_cone(self.lat, self.lon, self.heading, self.fov, self.range_m)

    def as_geojson_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [self.polygon]},
            "properties": {
                "camera_key": self.key,
                "name": self.name,
                "heading": self.heading,
                "fov": self.fov,
                "range_m": self.range_m,
                "heading_known": self.heading_known,
                # The UI prints this next to the cone so nobody mistakes a
                # default disc for a surveyed field of view.
                "approximate_note": (
                    "Heading unknown — shown as a 360° radius"
                    if not self.heading_known
                    else "Approximate: heading and field of view are from config, not surveyed"
                ),
            },
        }


@dataclass(slots=True)
class SensorMatch:
    sensor_id: str
    reading_id: int
    distance_m: float
    in_polygon: bool
    reasons: list[str]
    reading_ts: str
    smoke_index: float
    thermal_delta_c: float
    thermal_hotspot: bool
    demo: bool

    def describe(self, *, with_camera: bool = True) -> str:
        if not with_camera:
            # sensor_only events have no camera, so no distance to one either.
            return f"Sensor {self.sensor_id}: " + "; ".join(self.reasons)
        where = (
            "inside the camera's view polygon"
            if self.in_polygon
            else f"{self.distance_m:.0f} m from the camera"
        )
        return f"Sensor {self.sensor_id} {where}: " + "; ".join(self.reasons)


# --------------------------------------------------------------------------- #
# pure decision helpers (unit-tested directly)
# --------------------------------------------------------------------------- #
def sensor_matches_camera(
    view: CameraView,
    sensor_lat: float,
    sensor_lon: float,
    *,
    match_radius_m: float,
) -> tuple[bool, bool, float]:
    """``(matches, in_polygon, distance_m)`` for one sensor against one camera."""
    distance = haversine_m(view.lat, view.lon, sensor_lat, sensor_lon)
    inside = point_in_polygon(sensor_lat, sensor_lon, view.polygon)
    return bool(inside or distance <= match_radius_m), inside, distance


def within_time_window(a: datetime, b: datetime, minutes: float) -> bool:
    return abs((a - b).total_seconds()) <= minutes * 60.0


def should_dispatch(status: str) -> bool:
    """Core product rule: only verified and sensor_only ever leave the system."""
    return status in DISPATCHABLE_STATUSES


def resolve_severity(status: str) -> str:
    """Torch severity vocabulary: Critical or Warning."""
    return "Critical" if status == "verified" else "Warning"


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
class FusionEngine:
    def __init__(self, config, dispatcher=None) -> None:
        self.config = config
        self.dispatcher = dispatcher
        self.range_m = float(config.get("fusion.view_range_m", 1500))
        self.match_radius_m = float(config.get("fusion.sensor_match_radius_m", 400))
        self.window_minutes = float(config.get("fusion.time_window_minutes", 10))
        self.dedupe_minutes = float(config.get("fusion.dedupe_minutes", 30))
        self.unknown_heading_is_360 = bool(config.get("fusion.unknown_heading_is_360", True))
        self.score_threshold = float(config.get("detection.score_threshold", 0.55))
        self.smoke_threshold = float(config.get("sensors.thresholds.smoke_index", 60.0))
        self.thermal_threshold = float(config.get("sensors.thresholds.thermal_delta_c", 8.0))

    # -- views ---------------------------------------------------------------
    def camera_view(self, row: Any) -> CameraView | None:
        lat, lon = row["lat"], row["lon"]
        if lat is None or lon is None:
            return None
        heading = row["heading"]
        fov = row["fov"]
        heading_known = heading is not None
        if not heading_known and self.unknown_heading_is_360:
            heading, fov = None, None
        return CameraView(
            key=row["key"],
            name=row["name"],
            lat=float(lat),
            lon=float(lon),
            heading=float(heading) if heading is not None else None,
            fov=float(fov) if fov is not None else (60.0 if heading_known else None),
            range_m=self.range_m,
            heading_known=heading_known,
        )

    def all_views(self) -> list[CameraView]:
        views = [self.camera_view(row) for row in db.query("SELECT * FROM cameras")]
        return [v for v in views if v is not None]

    # -- corroboration -------------------------------------------------------
    def find_corroborating_sensor(self, view: CameraView, at: datetime) -> SensorMatch | None:
        """Any anomalous sensor reading in this camera's view within ±window."""
        low = (at - timedelta(minutes=self.window_minutes)).isoformat()
        high = (at + timedelta(minutes=self.window_minutes)).isoformat()
        rows = db.query(
            "SELECT r.*, s.lat AS s_lat, s.lon AS s_lon FROM sensor_readings r"
            " JOIN sensors s ON s.id = r.sensor_id"
            " WHERE r.ts BETWEEN ? AND ?"
            " ORDER BY r.ts DESC",
            (low, high),
        )
        best: SensorMatch | None = None
        for row in rows:
            reasons = self._anomaly_reasons(row)
            if not reasons:
                continue
            matches, inside, distance = sensor_matches_camera(
                view, float(row["s_lat"]), float(row["s_lon"]), match_radius_m=self.match_radius_m
            )
            if not matches:
                continue
            candidate = SensorMatch(
                sensor_id=row["sensor_id"],
                reading_id=int(row["id"]),
                distance_m=distance,
                in_polygon=bool(inside),
                reasons=reasons,
                reading_ts=row["ts"],
                smoke_index=float(row["smoke_index"] or 0.0),
                thermal_delta_c=float(row["thermal_delta_c"] or 0.0),
                thermal_hotspot=bool(row["thermal_hotspot"]),
                demo=bool(row["demo"]),
            )
            # Prefer the strongest signal, then the closest sensor.
            if best is None or (candidate.smoke_index, -candidate.distance_m) > (
                best.smoke_index, -best.distance_m
            ):
                best = candidate
        return best

    def _anomaly_reasons(self, row: Any) -> list[str]:
        reasons: list[str] = []
        smoke = float(row["smoke_index"] or 0.0)
        thermal = float(row["thermal_delta_c"] or 0.0)
        if smoke >= self.smoke_threshold:
            reasons.append(f"smoke/gas index {smoke:.0f} ≥ {self.smoke_threshold:.0f}")
        if row["thermal_hotspot"]:
            reasons.append("thermal hotspot flag set")
        if thermal >= self.thermal_threshold:
            reasons.append(f"thermal delta {thermal:.1f}°C ≥ {self.thermal_threshold:.1f}°C")
        if reasons and row["audio_event"]:
            reasons.append("audio event")
        return reasons

    # -- camera path ---------------------------------------------------------
    def on_frame_scored(
        self,
        *,
        camera_key: str,
        frame_id: int,
        score: float,
        bbox: list[float] | None,
        view_changed: bool,
        ts: datetime,
    ) -> int | None:
        """Create or update an event for a scored frame. Returns the event id."""
        if view_changed:
            # A moved camera is not evidence of smoke. Explicit product rule.
            return None
        if score < self.score_threshold:
            return None

        row = db.query_one("SELECT * FROM cameras WHERE key = ?", (camera_key,))
        if row is None:
            return None
        view = self.camera_view(row)

        event_id = self._recent_open_event(camera_key, ts)
        if event_id is None:
            event_id = db.insert(
                "INSERT INTO events (ts, updated_at, status, category, severity, camera_key,"
                " frame_id, score, bbox) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    ts.isoformat(), ts.isoformat(), CAMERA_ONLY_STATUS, "Fire",
                    resolve_severity(CAMERA_ONLY_STATUS), camera_key, frame_id,
                    round(float(score), 4), json.dumps(bbox) if bbox else None,
                ),
            )
        else:
            db.execute(
                "UPDATE events SET updated_at = ?, score = MAX(COALESCE(score,0), ?),"
                " frame_id = ?, bbox = COALESCE(?, bbox) WHERE id = ?",
                (ts.isoformat(), round(float(score), 4), frame_id,
                 json.dumps(bbox) if bbox else None, event_id),
            )
        db.execute("UPDATE frames SET pinned = 1 WHERE id = ?", (frame_id,))

        if view is not None:
            match = self.find_corroborating_sensor(view, ts)
            if match is not None:
                self.upgrade_to_verified(event_id, match)
        return event_id

    def upgrade_to_verified(self, event_id: int, match: SensorMatch) -> None:
        current = db.query_one("SELECT status, demo FROM events WHERE id = ?", (event_id,))
        if current is None or current["status"] == "verified":
            return
        db.execute(
            "UPDATE events SET status = 'verified', severity = ?, sensor_id = ?,"
            " confirming_reading_id = ?, confirmation_detail = ?, updated_at = ?,"
            " demo = MAX(demo, ?) WHERE id = ?",
            (
                resolve_severity("verified"), match.sensor_id, match.reading_id,
                match.describe(), datetime.now(timezone.utc).isoformat(),
                1 if match.demo else 0, event_id,
            ),
        )
        self._maybe_dispatch(event_id)

    # -- sensor path ---------------------------------------------------------
    def on_sensor_readings(self, readings: Iterable[Any]) -> list[int]:
        """Create ``sensor_only`` events for anomalies no camera corroborated.

        Also upgrades any open ``possible_smoke`` event the new reading now
        corroborates — the sensor may arrive after the camera did.
        """
        created: list[int] = []
        views = self.all_views()
        for reading in readings:
            row = db.query_one(
                "SELECT r.*, s.lat AS s_lat, s.lon AS s_lon FROM sensor_readings r"
                " JOIN sensors s ON s.id = r.sensor_id WHERE r.id = ?",
                (int(reading),) if isinstance(reading, int) else (int(reading["id"]),),
            )
            if row is None:
                continue
            reasons = self._anomaly_reasons(row)
            if not reasons:
                continue

            reading_ts = _parse_ts(row["ts"])
            match = SensorMatch(
                sensor_id=row["sensor_id"], reading_id=int(row["id"]), distance_m=0.0,
                in_polygon=False, reasons=reasons, reading_ts=row["ts"],
                smoke_index=float(row["smoke_index"] or 0.0),
                thermal_delta_c=float(row["thermal_delta_c"] or 0.0),
                thermal_hotspot=bool(row["thermal_hotspot"]), demo=bool(row["demo"]),
            )

            # 1. Does this reading confirm a camera that is already suspicious?
            upgraded = False
            for view in views:
                matches, inside, distance = sensor_matches_camera(
                    view, float(row["s_lat"]), float(row["s_lon"]),
                    match_radius_m=self.match_radius_m,
                )
                if not matches:
                    continue
                open_event = self._recent_open_event(view.key, reading_ts, statuses=(CAMERA_ONLY_STATUS,))
                if open_event is not None:
                    match.in_polygon, match.distance_m = bool(inside), distance
                    self.upgrade_to_verified(open_event, match)
                    upgraded = True
            if upgraded:
                continue

            # 2. Has this sensor already confirmed a camera event for this same
            #    incident? If so, the incident is already being handled as
            #    `verified`; opening a parallel sensor_only alert would page the
            #    same fire twice.
            if self._recently_confirmed_a_camera(row["sensor_id"], reading_ts):
                continue

            # 3. No camera agrees -> still an alert. Sensors see what cameras cannot.
            existing = self._recent_open_sensor_event(row["sensor_id"], reading_ts)
            if existing is not None:
                db.execute(
                    "UPDATE events SET updated_at = ?, confirming_reading_id = ?,"
                    " confirmation_detail = ? WHERE id = ?",
                    (
                        reading_ts.isoformat(), match.reading_id,
                        match.describe(with_camera=False), existing,
                    ),
                )
                continue

            event_id = db.insert(
                "INSERT INTO events (ts, updated_at, status, category, severity, sensor_id,"
                " confirming_reading_id, confirmation_detail, demo)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    reading_ts.isoformat(), reading_ts.isoformat(), "sensor_only",
                    "Fire", resolve_severity("sensor_only"), row["sensor_id"],
                    match.reading_id, match.describe(with_camera=False),
                    1 if match.demo else 0,
                ),
            )
            created.append(event_id)
            self._maybe_dispatch(event_id)
        return created

    # -- dispatch ------------------------------------------------------------
    def _maybe_dispatch(self, event_id: int) -> None:
        row = db.query_one("SELECT * FROM events WHERE id = ?", (event_id,))
        if row is None or not should_dispatch(row["status"]) or row["dispatched_at"]:
            return
        if self.dispatcher is None:
            return
        self.dispatcher.send(dict(row))

    # -- helpers -------------------------------------------------------------
    def _recent_open_event(
        self,
        camera_key: str,
        at: datetime,
        statuses: tuple[str, ...] = (CAMERA_ONLY_STATUS, "verified"),
    ) -> int | None:
        since = (at - timedelta(minutes=self.dedupe_minutes)).isoformat()
        placeholders = ",".join("?" for _ in statuses)
        row = db.query_one(
            f"SELECT id FROM events WHERE camera_key = ? AND ts >= ?"
            f" AND status IN ({placeholders}) AND human_label IS NULL"
            " ORDER BY id DESC LIMIT 1",
            (camera_key, since, *statuses),
        )
        return int(row["id"]) if row else None

    def _recently_confirmed_a_camera(self, sensor_id: str, at: datetime) -> bool:
        """True if this sensor already verified a camera event in the dedupe window.

        Without this, a sensor that keeps alarming after verifying a camera
        event opens a second, redundant `sensor_only` alert for the same fire
        and dispatches it again.
        """
        since = (at - timedelta(minutes=self.dedupe_minutes)).isoformat()
        row = db.query_one(
            "SELECT id FROM events WHERE sensor_id = ? AND status = 'verified'"
            " AND ts >= ? ORDER BY id DESC LIMIT 1",
            (sensor_id, since),
        )
        return row is not None

    def _recent_open_sensor_event(self, sensor_id: str, at: datetime) -> int | None:
        since = (at - timedelta(minutes=self.dedupe_minutes)).isoformat()
        row = db.query_one(
            "SELECT id FROM events WHERE sensor_id = ? AND status = 'sensor_only'"
            " AND ts >= ? AND human_label IS NULL ORDER BY id DESC LIMIT 1",
            (sensor_id, since),
        )
        return int(row["id"]) if row else None


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
