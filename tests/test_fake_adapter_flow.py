"""A NEW feed type must flow through ingest -> detection -> fusion untouched.

This is the load-bearing test for the feed architecture. ``FakeSatelliteAdapter``
below is a feed type that did not exist when the pipeline was written. Adding it
takes exactly two things:

1. a class implementing ``list_cameras`` / ``get_frame`` / ``health``, and
2. a config block naming its ``type``.

If this test ever needs a change to ``app/pipeline/*``, the abstraction has
leaked and the "one file plus a config block" promise is broken.
"""
from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.pipeline.ingest import IngestWorker  # noqa: E402
from feeds.base import Camera, FeedAdapter, Frame, cameras_from_config  # noqa: E402
from feeds.registry import available_types, build, register  # noqa: E402


def _render(smoke: float) -> bytes:
    """A frame with an optional grey plume over a blue sky."""
    height, width = 270, 480
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    img = np.zeros((height, width, 3))
    img[..., 0], img[..., 1], img[..., 2] = 120, 160, 215
    ground = ys > height * 0.55
    img[ground] = np.array([95, 105, 62])
    if smoke > 0:
        plume = np.exp(-(((xs - width * 0.4) / 55.0) ** 2)) * (ys < height * 0.55)
        alpha = np.clip(plume * smoke, 0, 0.9)[..., None]
        img = img * (1 - alpha) + np.array([198.0, 198.0, 200.0]) * alpha
    img += np.random.default_rng(0).normal(0, 2.0, img.shape)
    out = io.BytesIO()
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(out, "JPEG", quality=85)
    return out.getvalue()


@register
class FakeSatelliteAdapter(FeedAdapter):
    """A feed type invented by this test. The pipeline has never heard of it."""

    type = "fake_satellite"
    auth_required = False
    default_interval_s = 60
    allowed_schemes = ()          # generates frames locally, makes no requests

    def __init__(self, feed_config):
        super().__init__(feed_config)
        self.calls = 0
        # Escalating smoke so the detector's temporal baseline has something to
        # react to: clean, clean, clean, then a plume.
        self.sequence = [0.0, 0.0, 0.0, 0.95, 0.98]

    def list_cameras(self) -> list[Camera]:
        self.record_success()
        return self.apply_filter(cameras_from_config(self.config, source=self.type))

    def get_frame(self, camera: Camera) -> Frame | None:
        smoke = self.sequence[min(self.calls, len(self.sequence) - 1)]
        self.calls += 1
        jpeg = _render(smoke)
        self.record_success()
        return Frame(
            camera_key=camera.key, jpeg=jpeg, captured_at=Frame.now(),
            width=480, height=270, source_url="fake://satellite",
        )


FEED_CONFIG = {
    "id": "fake_sat",
    "type": "fake_satellite",
    "enabled": True,
    "interval_s": 0,
    "cameras": [{
        "id": "sat1", "name": "Fake Satellite 1",
        "lat": 35.1002, "lon": -106.6817, "heading": 175, "fov": 60, "mast_height": 12,
    }],
}


@pytest.fixture()
def fake_feed_config(config):
    """The whole integration: replace the feed list with the new type."""
    config.raw["feeds"] = [FEED_CONFIG]
    return config


def test_the_new_type_registers_itself(fake_feed_config):
    assert "fake_satellite" in available_types()
    assert build(FEED_CONFIG).type == "fake_satellite"


def test_a_brand_new_feed_type_flows_all_the_way_to_a_verified_event(database, fake_feed_config):
    worker = IngestWorker(fake_feed_config)
    worker.build_adapters()
    worker.sync_cameras()
    worker.sync_sensors()

    # --- the camera the new feed declared reached the database --------------
    camera = db.query_one("SELECT * FROM cameras WHERE feed_id = 'fake_sat'")
    assert camera is not None
    assert camera["name"] == "Fake Satellite 1"
    camera_key = camera["key"]

    # --- ingest stores frames, with no knowledge of the feed type -----------
    for _ in range(5):
        worker._next_due.clear()
        worker.poll_once()

    frames = db.query("SELECT * FROM frames WHERE camera_key = ? ORDER BY id", (camera_key,))
    assert len(frames) == 5
    assert all(row["sha256"] for row in frames), "every frame is hashed"
    assert all(Path(row["path"]).exists() for row in frames), "every frame is on disk"

    # --- the detector scored them, and the score rose when smoke appeared ---
    assert all(row["detector"] == "baseline" for row in frames)
    assert frames[0]["score"] == 0.0
    assert frames[-1]["score"] >= fake_feed_config.get("detection.score_threshold")

    # --- fusion opened a camera-only event ----------------------------------
    event = db.query_one("SELECT * FROM events WHERE camera_key = ?", (camera_key,))
    assert event is not None
    assert event["status"] == "possible_smoke", "no sensor has agreed yet"
    assert event["dispatched_at"] is None

    # --- a Torch sensor in view agrees -> verified --------------------------
    db.execute(
        "INSERT INTO sensors (id, name, lat, lon, source) "
        "VALUES ('TS-FAKE','Sensor In View',35.0912,-106.6810,'mock')"
    )
    reading_id = db.insert(
        "INSERT INTO sensor_readings (sensor_id, ts, temp_c, thermal_hotspot, thermal_delta_c,"
        " smoke_index, audio_event, battery) VALUES (?,?,?,?,?,?,?,?)",
        ("TS-FAKE", datetime.now(timezone.utc).isoformat(), 24.0, 1, 14.0, 210.0, 1, 88.0),
    )
    worker.fusion.on_sensor_readings([reading_id])

    upgraded = db.query_one("SELECT * FROM events WHERE id = ?", (event["id"],))
    assert upgraded["status"] == "verified"
    assert upgraded["sensor_id"] == "TS-FAKE"
    assert upgraded["severity"] == "Critical"


def test_the_new_feed_reports_health_like_any_other(fake_feed_config):
    adapter = build(FEED_CONFIG)
    adapter.cameras(refresh=True)
    health = adapter.health()
    assert health["reachable"] is True
    assert health["error_count"] == 0
    assert "last_success" in health


def test_metrics_count_the_new_feeds_cameras(database, fake_feed_config):
    from app import metrics

    worker = IngestWorker(fake_feed_config)
    worker.build_adapters()
    worker.sync_cameras()
    worker._next_due.clear()
    worker.poll_once()

    rows = metrics.per_camera_day(fake_feed_config)
    assert any(row["feed_id"] == "fake_sat" and row["frames_ingested"] == 1 for row in rows)
