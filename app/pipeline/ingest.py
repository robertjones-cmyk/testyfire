"""Ingest worker.

For each enabled feed, every ``interval_s`` per camera:

1. ask the feed adapter for a frame (the adapter hides the source entirely);
2. store the JPEG on disk under a path built **only** from generated ids, and a
   row in SQLite (camera, timestamp, path, SHA-256);
3. run view-change detection — a moved PTZ camera is flagged and cannot raise a
   smoke alert;
4. score the frame with the configured detector, optionally escalating to the
   vision LLM;
5. hand the score to the fusion engine.

Sensors are polled on their own cadence in the same worker.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feeds
from feeds.base import Camera, FeedAdapter

from .. import db
from ..config import Config
from ..geo.geom import haversine_m
from ..security.paths import safe_join, slugify_id
from ..security.redact import redact
from ..sensors import build_sensor_source
from .detect import build_detector
from .detect.vision_llm import VisionLLMEscalation
from .dispatch import Dispatcher
from .fusion import FusionEngine
from .viewchange import ViewChangeDetector

log = logging.getLogger("torch.ingest")


class IngestWorker:
    """Background poller. One thread for frames, one for sensors."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.frames_dir = Path(config.frames_dir)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.adapters: dict[str, FeedAdapter] = {}
        self.detector = build_detector(config)
        self.escalation = VisionLLMEscalation(config)
        self.view_change = ViewChangeDetector(config)
        self.dispatcher = Dispatcher(config)
        self.fusion = FusionEngine(config, dispatcher=self.dispatcher)
        self.sensor_source = build_sensor_source(config)
        self.sensor_interval_s = int(config.get("sensors.emit_interval_s", 60))
        self._next_due: dict[str, float] = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        self.build_adapters()
        self.sync_cameras()
        self.sync_sensors()
        self._threads = [
            threading.Thread(target=self._frame_loop, name="torch-ingest", daemon=True),
            threading.Thread(target=self._sensor_loop, name="torch-sensors", daemon=True),
            threading.Thread(target=self._housekeeping_loop, name="torch-housekeeping", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        log.info("ingest worker started with %d feed(s)", len(self.adapters))

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3)

    # -- setup ---------------------------------------------------------------
    def build_adapters(self) -> None:
        self.adapters = {}
        for entry in self.config.enabled_feeds():
            try:
                adapter = feeds.build(entry)
            except Exception as exc:
                log.error("feed %s could not be built: %s", entry.get("id"), redact(str(exc)))
                continue
            self.adapters[adapter.feed_id] = adapter

    def sync_cameras(self) -> None:
        """Refresh the camera table from every adapter, applying config overrides."""
        now = datetime.now(timezone.utc).isoformat()
        for feed_id, adapter in self.adapters.items():
            try:
                cameras = adapter.cameras(refresh=True)
            except Exception as exc:
                log.warning("feed %s list_cameras failed: %s", feed_id, redact(str(exc)))
                cameras = []
            for camera in cameras:
                self.apply_overrides(camera)
                db.execute(
                    "INSERT INTO cameras (key, feed_id, camera_id, name, lat, lon, heading, fov,"
                    " mast_height, is_ptz, source, first_seen, last_seen)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(key) DO UPDATE SET name=excluded.name, lat=excluded.lat,"
                    " lon=excluded.lon, heading=excluded.heading, fov=excluded.fov,"
                    " mast_height=excluded.mast_height, is_ptz=excluded.is_ptz,"
                    " last_seen=excluded.last_seen",
                    (
                        camera.key, feed_id, camera.id, camera.name, camera.lat, camera.lon,
                        camera.heading, camera.fov, camera.mast_height,
                        1 if camera.is_ptz else 0, camera.source, now, now,
                    ),
                )
            self._record_feed_health(adapter, len(cameras))

    def apply_overrides(self, camera: Camera) -> None:
        """Apply ``camera_overrides`` from config (geometry the feed cannot give us)."""
        overrides: dict[str, Any] = self.config.get("camera_overrides", {}) or {}
        applied: dict[str, Any] = {}
        for key, values in overrides.items():
            key = str(key)
            if key.startswith("name:"):
                needle = key[5:].lower()
                haystack = f"{camera.name} {camera.id}".lower()
                if needle.replace("_", "-") in haystack.replace("_", "-"):
                    applied.update(values or {})
            elif key == f"{camera.feed_id}:{camera.id}" or key == camera.key:
                applied.update(values or {})
        for field in ("lat", "lon", "heading", "fov", "mast_height", "is_ptz"):
            if field in applied and applied[field] is not None:
                setattr(camera, field, applied[field])
        if camera.mast_height is None:
            camera.mast_height = float(self.config.get("blind_spot.mast_height_m", 10.0))

    def sync_sensors(self) -> None:
        for spec in self.sensor_source.list_sensors():
            db.execute(
                "INSERT INTO sensors (id, name, lat, lon, source) VALUES (?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name, lat=excluded.lat,"
                " lon=excluded.lon, source=excluded.source",
                (spec.id, spec.name, spec.lat, spec.lon, spec.source),
            )

    def _record_feed_health(self, adapter: FeedAdapter, camera_count: int) -> None:
        health = adapter.health()
        db.execute(
            "INSERT INTO feed_health (feed_id, ts, reachable, last_success, error_count,"
            " last_error, camera_count, enabled, type) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(feed_id) DO UPDATE SET ts=excluded.ts, reachable=excluded.reachable,"
            " last_success=excluded.last_success, error_count=excluded.error_count,"
            " last_error=excluded.last_error, camera_count=excluded.camera_count,"
            " enabled=excluded.enabled, type=excluded.type",
            (
                adapter.feed_id, datetime.now(timezone.utc).isoformat(),
                1 if health.get("reachable") else 0, health.get("last_success"),
                int(health.get("error_count", 0)), health.get("last_error"),
                camera_count, 1 if adapter.enabled else 0, adapter.type,
            ),
        )

    # -- loops ---------------------------------------------------------------
    def _frame_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("ingest cycle failed")
            self._stop.wait(5.0)

    def _sensor_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_sensors()
            except Exception:
                log.exception("sensor cycle failed")
            self._stop.wait(self.sensor_interval_s)

    def _housekeeping_loop(self) -> None:
        from .retention import run_retention

        while not self._stop.is_set():
            try:
                run_retention(self.config)
            except Exception:
                log.exception("retention failed")
            self._stop.wait(3600)

    # -- work ----------------------------------------------------------------
    def poll_once(self) -> int:
        """Fetch every camera that is due. Returns the number of frames stored."""
        stored = 0
        now_monotonic = time.monotonic()
        for feed_id, adapter in self.adapters.items():
            if adapter.in_backoff():
                continue
            try:
                cameras = adapter.cameras()
            except Exception as exc:
                log.warning("feed %s: %s", feed_id, redact(str(exc)))
                continue
            for camera in cameras:
                due_at = self._next_due.get(camera.key, 0.0)
                if now_monotonic < due_at:
                    continue
                self.apply_overrides(camera)
                self._next_due[camera.key] = now_monotonic + adapter.interval_s
                if self.ingest_camera(adapter, camera):
                    stored += 1
            self._record_feed_health(adapter, len(cameras))
            if adapter.health_state.consecutive_failures:
                from datetime import timedelta

                adapter.health_state.backoff_until = datetime.now(timezone.utc) + timedelta(
                    seconds=adapter.backoff_seconds()
                )
        return stored

    def ingest_camera(self, adapter: FeedAdapter, camera: Camera) -> bool:
        frame = adapter.get_frame(camera)
        if frame is None:
            db.execute(
                "INSERT INTO ingest_failures (camera_key, feed_id, ts, error) VALUES (?,?,?,?)",
                (
                    camera.key, adapter.feed_id, datetime.now(timezone.utc).isoformat(),
                    redact(adapter.health().get("last_error") or "no frame returned")[:300],
                ),
            )
            return False

        now = datetime.now(timezone.utc)
        path = self._store_jpeg(camera.key, frame.jpeg, now)
        digest = hashlib.sha256(frame.jpeg).hexdigest()
        frame_id = db.insert(
            "INSERT INTO frames (camera_key, ts, path, sha256, width, height) VALUES (?,?,?,?,?,?)",
            (camera.key, now.isoformat(), str(path), digest, frame.width, frame.height),
        )

        # 1. Did the operator move the camera?
        change = self.view_change.check(camera.key, frame.jpeg, frame_id)
        if change.view_changed:
            self.detector.reset(camera.key)
        db.execute(
            "UPDATE frames SET view_changed = ?, phash = ? WHERE id = ?",
            (1 if change.view_changed else 0, change.phash, frame_id),
        )

        # 2. Score it.
        result = self.detector.detect(frame.jpeg, camera_key=camera.key)
        if not change.view_changed and self.escalation.should_escalate(result.score):
            result = self.escalation.escalate(frame.jpeg, baseline=result, frame_id=frame_id)

        db.execute(
            "UPDATE frames SET score = ?, detector = ?, bbox = ?, inference_ms = ?, cost_usd = ?"
            " WHERE id = ?",
            (
                round(result.score, 4), result.detector,
                json.dumps(result.bbox) if result.bbox else None,
                round(result.inference_ms, 2), round(result.cost_usd, 6), frame_id,
            ),
        )

        # 3. Fuse.
        self.fusion.on_frame_scored(
            camera_key=camera.key, frame_id=frame_id, score=result.score,
            bbox=result.bbox, view_changed=change.view_changed, ts=now,
        )
        return True

    def _store_jpeg(self, camera_key: str, jpeg: bytes, when: datetime) -> Path:
        """Path components are generated ids only — never a feed-supplied name."""
        directory = safe_join(self.frames_dir, slugify_id(camera_key), when.strftime("%Y%m%d"))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid.uuid4().hex}.jpg"
        path.write_bytes(jpeg)
        return path

    def poll_sensors(self) -> int:
        readings = self.sensor_source.poll()
        ids: list[int] = []
        for reading in readings:
            reading_id = db.insert(
                "INSERT INTO sensor_readings (sensor_id, ts, temp_c, thermal_hotspot,"
                " thermal_delta_c, smoke_index, audio_event, battery, demo)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    reading.sensor_id, reading.ts.isoformat(), reading.temp_c,
                    1 if reading.thermal_hotspot else 0, reading.thermal_delta_c,
                    reading.smoke_index, 1 if reading.audio_event else 0,
                    reading.battery, 1 if reading.demo else 0,
                ),
            )
            db.execute(
                "UPDATE sensors SET battery = ?, last_seen = ? WHERE id = ?",
                (reading.battery, reading.ts.isoformat(), reading.sensor_id),
            )
            ids.append(reading_id)
        self.fusion.on_sensor_readings(ids)
        return len(ids)

    # -- demo ----------------------------------------------------------------
    def start_fire_scenario(self, sensor_id: str | None = None) -> str:
        starter = getattr(self.sensor_source, "start_fire_scenario", None)
        if starter is None:
            raise RuntimeError("the configured sensor source has no fire scenario")
        target = starter(sensor_id)
        self.poll_sensors()
        return target

    def stop_fire_scenario(self) -> None:
        stopper = getattr(self.sensor_source, "stop_fire_scenario", None)
        if stopper:
            stopper()

    def nearest_camera_to_sensor(self, sensor_id: str) -> str | None:
        sensor = db.query_one("SELECT * FROM sensors WHERE id = ?", (sensor_id,))
        if sensor is None:
            return None
        best, best_distance = None, float("inf")
        for row in db.query("SELECT * FROM cameras WHERE lat IS NOT NULL"):
            distance = haversine_m(row["lat"], row["lon"], sensor["lat"], sensor["lon"])
            if distance < best_distance:
                best, best_distance = row["key"], distance
        return best
