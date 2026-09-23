"""Fusion rules: the upgrade, the time window, the distance rule, the dispatch rule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.pipeline.fusion import (
    CameraView,
    FusionEngine,
    resolve_severity,
    sensor_matches_camera,
    should_dispatch,
    within_time_window,
)


class RecordingDispatcher:
    """Stands in for the real webhook; records what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, event: dict) -> bool:
        assert should_dispatch(event["status"]), "dispatcher was handed a non-dispatchable event"
        self.sent.append(event)
        db.execute(
            "UPDATE events SET dispatched_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), event["id"]),
        )
        return True


def _add_reading(sensor_id: str, *, smoke: float, ts: datetime, thermal: float = 1.0, demo: int = 0) -> int:
    return db.insert(
        "INSERT INTO sensor_readings (sensor_id, ts, temp_c, thermal_hotspot, thermal_delta_c,"
        " smoke_index, audio_event, battery, demo) VALUES (?,?,?,?,?,?,?,?,?)",
        (sensor_id, ts.isoformat(), 22.0, 1 if thermal >= 8 else 0, thermal, smoke, 0, 90.0, demo),
    )


def _add_frame(camera_key: str, ts: datetime) -> int:
    return db.insert(
        "INSERT INTO frames (camera_key, ts, path, sha256) VALUES (?,?,?,?)",
        (camera_key, ts.isoformat(), "/dev/null", "x" * 64),
    )


# --------------------------------------------------------------------------- #
# pure rules
# --------------------------------------------------------------------------- #
def test_dispatch_rule_is_the_product_decision():
    """possible_smoke NEVER dispatches; verified and sensor_only always may."""
    assert should_dispatch("verified") is True
    assert should_dispatch("sensor_only") is True
    assert should_dispatch("possible_smoke") is False
    assert should_dispatch("anything_else") is False


def test_severity_mapping():
    assert resolve_severity("verified") == "Critical"
    assert resolve_severity("possible_smoke") == "Warning"
    assert resolve_severity("sensor_only") == "Warning"


def test_time_window():
    now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    assert within_time_window(now, now + timedelta(minutes=9), 10) is True
    assert within_time_window(now, now - timedelta(minutes=10), 10) is True
    assert within_time_window(now, now + timedelta(minutes=11), 10) is False


def test_distance_rule_inside_cone_and_by_radius():
    view = CameraView("k", "cam", 35.1002, -106.6817, 175.0, 60.0, 1500.0, True)

    # Due south, 1 km: inside the cone.
    inside, in_polygon, distance = sensor_matches_camera(view, 35.0912, -106.6810, match_radius_m=400)
    assert inside and in_polygon and 800 < distance < 1200

    # Due north, 300 m: outside the cone but within the match radius -> counts.
    inside, in_polygon, distance = sensor_matches_camera(view, 35.1029, -106.6817, match_radius_m=400)
    assert inside is True and in_polygon is False and distance < 400

    # Due north, 5 km: outside both -> does not count.
    inside, _, distance = sensor_matches_camera(view, 35.1450, -106.6817, match_radius_m=400)
    assert inside is False and distance > 4000


def test_unknown_heading_becomes_a_360_disc():
    view = CameraView("k", "cam", 35.1002, -106.6817, None, None, 1500.0, False)
    # A point due north is inside a disc even though it would be behind a cone.
    inside, in_polygon, _ = sensor_matches_camera(view, 35.1100, -106.6817, match_radius_m=100)
    assert inside and in_polygon
    assert view.as_geojson_feature()["properties"]["heading_known"] is False


# --------------------------------------------------------------------------- #
# engine behaviour
# --------------------------------------------------------------------------- #
def test_camera_alone_stays_possible_smoke_and_is_not_dispatched(seeded, config):
    dispatcher = RecordingDispatcher()
    engine = FusionEngine(config, dispatcher=dispatcher)
    now = datetime.now(timezone.utc)

    event_id = engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.80, bbox=[0.3, 0.2, 0.2, 0.2], view_changed=False, ts=now,
    )

    row = db.query_one("SELECT * FROM events WHERE id = ?", (event_id,))
    assert row["status"] == "possible_smoke"
    assert row["dispatched_at"] is None
    assert dispatcher.sent == []


def test_sensor_in_view_upgrades_to_verified_and_dispatches(seeded, config):
    dispatcher = RecordingDispatcher()
    engine = FusionEngine(config, dispatcher=dispatcher)
    now = datetime.now(timezone.utc)
    _add_reading("TS-IN", smoke=180.0, ts=now - timedelta(minutes=3), thermal=12.0)

    event_id = engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.72, bbox=None, view_changed=False, ts=now,
    )

    row = db.query_one("SELECT * FROM events WHERE id = ?", (event_id,))
    assert row["status"] == "verified"
    assert row["severity"] == "Critical"
    assert row["sensor_id"] == "TS-IN"
    assert row["confirming_reading_id"] is not None
    assert "TS-IN" in row["confirmation_detail"]
    assert len(dispatcher.sent) == 1


def test_sensor_outside_the_window_does_not_upgrade(seeded, config):
    engine = FusionEngine(config, dispatcher=RecordingDispatcher())
    now = datetime.now(timezone.utc)
    # Anomalous, in view, but 25 minutes earlier — outside the +/-10 min window.
    _add_reading("TS-IN", smoke=200.0, ts=now - timedelta(minutes=25), thermal=14.0)

    event_id = engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.72, bbox=None, view_changed=False, ts=now,
    )
    assert db.query_one("SELECT status FROM events WHERE id = ?", (event_id,))["status"] == "possible_smoke"


def test_sensor_outside_the_view_does_not_upgrade(seeded, config):
    engine = FusionEngine(config, dispatcher=RecordingDispatcher())
    now = datetime.now(timezone.utc)
    _add_reading("TS-OUT", smoke=220.0, ts=now, thermal=15.0)

    event_id = engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.9, bbox=None, view_changed=False, ts=now,
    )
    assert db.query_one("SELECT status FROM events WHERE id = ?", (event_id,))["status"] == "possible_smoke"


def test_quiet_sensor_does_not_upgrade(seeded, config):
    engine = FusionEngine(config, dispatcher=RecordingDispatcher())
    now = datetime.now(timezone.utc)
    _add_reading("TS-IN", smoke=11.0, ts=now, thermal=1.1)   # nominal

    event_id = engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.9, bbox=None, view_changed=False, ts=now,
    )
    assert db.query_one("SELECT status FROM events WHERE id = ?", (event_id,))["status"] == "possible_smoke"


def test_view_changed_frame_never_raises_an_alert(seeded, config):
    engine = FusionEngine(config, dispatcher=RecordingDispatcher())
    now = datetime.now(timezone.utc)
    event_id = engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.99, bbox=None, view_changed=True, ts=now,
    )
    assert event_id is None
    assert db.query("SELECT * FROM events") == []


def test_score_below_threshold_raises_nothing(seeded, config):
    engine = FusionEngine(config, dispatcher=RecordingDispatcher())
    now = datetime.now(timezone.utc)
    assert engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.2, bbox=None, view_changed=False, ts=now,
    ) is None


def test_sensor_anomaly_with_no_camera_becomes_sensor_only_and_dispatches(seeded, config):
    dispatcher = RecordingDispatcher()
    engine = FusionEngine(config, dispatcher=dispatcher)
    now = datetime.now(timezone.utc)
    reading_id = _add_reading("TS-OUT", smoke=300.0, ts=now, thermal=20.0)

    created = engine.on_sensor_readings([reading_id])

    assert len(created) == 1
    row = db.query_one("SELECT * FROM events WHERE id = ?", (created[0],))
    assert row["status"] == "sensor_only"
    assert row["sensor_id"] == "TS-OUT"
    assert len(dispatcher.sent) == 1


def test_late_sensor_reading_upgrades_an_open_camera_event(seeded, config):
    """The sensor can arrive after the camera and still verify it."""
    dispatcher = RecordingDispatcher()
    engine = FusionEngine(config, dispatcher=dispatcher)
    now = datetime.now(timezone.utc)

    event_id = engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.7, bbox=None, view_changed=False, ts=now,
    )
    assert db.query_one("SELECT status FROM events WHERE id=?", (event_id,))["status"] == "possible_smoke"

    reading_id = _add_reading("TS-IN", smoke=190.0, ts=now + timedelta(minutes=4), thermal=13.0)
    engine.on_sensor_readings([reading_id])

    row = db.query_one("SELECT * FROM events WHERE id = ?", (event_id,))
    assert row["status"] == "verified"
    assert len(dispatcher.sent) == 1
    # It upgraded the existing event rather than opening a second one.
    assert db.query_one("SELECT COUNT(*) AS n FROM events")["n"] == 1


def test_demo_readings_tag_the_event(seeded, config):
    engine = FusionEngine(config, dispatcher=RecordingDispatcher())
    now = datetime.now(timezone.utc)
    _add_reading("TS-IN", smoke=250.0, ts=now, thermal=18.0, demo=1)

    event_id = engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.8, bbox=None, view_changed=False, ts=now,
    )
    assert db.query_one("SELECT demo FROM events WHERE id = ?", (event_id,))["demo"] == 1


def test_a_sensor_that_verified_a_camera_does_not_also_raise_sensor_only(seeded, config):
    """One fire must not page twice.

    A sensor that keeps alarming after it has already upgraded a camera event to
    `verified` must not then open a parallel `sensor_only` alert for the same
    incident — that dispatched the same fire to the webhook a second time.
    """
    dispatcher = RecordingDispatcher()
    engine = FusionEngine(config, dispatcher=dispatcher)
    now = datetime.now(timezone.utc)

    event_id = engine.on_frame_scored(
        camera_key="feed__cam1", frame_id=_add_frame("feed__cam1", now),
        score=0.75, bbox=None, view_changed=False, ts=now,
    )
    first = _add_reading("TS-IN", smoke=150.0, ts=now, thermal=12.0)
    engine.on_sensor_readings([first])
    assert db.query_one("SELECT status FROM events WHERE id=?", (event_id,))["status"] == "verified"
    assert len(dispatcher.sent) == 1

    # The fire keeps burning: more anomalous readings from the same sensor.
    for minutes in (1, 2, 3):
        later = _add_reading("TS-IN", smoke=240.0, ts=now + timedelta(minutes=minutes), thermal=19.0)
        engine.on_sensor_readings([later])

    assert db.query_one("SELECT COUNT(*) AS n FROM events")["n"] == 1, "one incident, one event"
    assert len(dispatcher.sent) == 1, "the same fire must not dispatch twice"


def test_sensor_only_wording_does_not_mention_a_camera(seeded, config):
    """A sensor_only event has no camera, so it must not claim a distance to one."""
    engine = FusionEngine(config, dispatcher=RecordingDispatcher())
    now = datetime.now(timezone.utc)
    reading_id = _add_reading("TS-OUT", smoke=300.0, ts=now, thermal=20.0)

    created = engine.on_sensor_readings([reading_id])
    detail = db.query_one("SELECT confirmation_detail FROM events WHERE id=?", (created[0],))

    assert "from the camera" not in detail["confirmation_detail"]
    assert "TS-OUT" in detail["confirmation_detail"]
