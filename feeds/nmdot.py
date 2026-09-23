"""NMDOT (New Mexico DOT) public camera feed.

The public endpoint ``https://servicev4.nmroads.com/RealMapWAR/GetCameraInfo``
returns a JSON list of cameras, each with a snapshot file on
``ss.nmroads.com/snapshots/*.jpg`` (1920x1080, refreshed roughly every minute).

FIELD NAMES
-----------
The exact JSON key names are resolved at runtime by :class:`FieldResolver`,
which tries a list of common aliases (case-insensitive) for each logical field
and also understands GeoJSON ``FeatureCollection`` payloads and nested
``views``/``images`` arrays. Two escape hatches exist if the server's real
shape differs:

* ``python -m feeds inspect nmdot_abq`` prints the raw top-level keys, the
  resolved mapping and a redacted sample record — run it once and you can see
  exactly what the server returns;
* pin the names explicitly with a ``field_map:`` block in ``config.yaml``, which
  always wins over the alias search.

Polling is deliberately polite: the camera list is cached, each snapshot is
pulled at most once per ``interval_s`` (default 120 s), a clear User-Agent is
sent, and failures back off exponentially.
"""
from __future__ import annotations

import json
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from app.security.images import UnsafeImage, normalise_to_jpeg
from app.security.net import BlockedRequest, FetchTooLarge, safe_fetch
from app.security.redact import redact

from .base import Camera, FeedAdapter, Frame
from .registry import register

#: Where a list of camera records may hide inside a JSON object.
LIST_KEYS = (
    "cameras", "camera", "camerainfo", "cameras_list", "data", "items",
    "results", "records", "features", "list", "rows", "value",
)

#: Aliases per logical field, lower-cased. First match wins.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "cameraid", "camid", "camera_id", "deviceid", "uid", "guid", "key", "cctvid"),
    "name": (
        "name", "cameraname", "camera_name", "title", "label", "description",
        "location", "locationname", "roadway", "route", "displayname",
    ),
    "lat": ("lat", "latitude", "y", "ycoord", "y_coord"),
    "lon": ("lon", "lng", "long", "longitude", "x", "xcoord", "x_coord"),
    "url": (
        "url", "imageurl", "image_url", "snapshoturl", "snapshot_url", "src",
        "image", "imagepath", "filename", "file", "filepath", "picture",
        "thumbnail", "thumb", "staticimage", "jpg",
    ),
    "heading": ("heading", "direction", "bearing", "azimuth", "facing"),
    "ptz": ("isptz", "ptz", "is_ptz", "movable", "pantilt"),
}

#: Nested arrays that themselves contain the snapshot URL.
NESTED_VIEW_KEYS = ("views", "images", "cameraviews", "snapshots", "streams", "files")


class FieldResolver:
    """Maps a feed record's real key names onto our logical field names."""

    def __init__(self, overrides: dict[str, str] | None = None):
        self.overrides = {k: str(v) for k, v in (overrides or {}).items()}
        self.resolved: dict[str, str] = {}

    @staticmethod
    def _lower_index(record: dict[str, Any]) -> dict[str, str]:
        return {str(k).lower().replace(" ", "").replace("-", "").replace("_", ""): str(k) for k in record}

    def pick(self, record: dict[str, Any], logical: str) -> Any:
        if logical in self.overrides:
            key = self.overrides[logical]
            self.resolved[logical] = key
            return record.get(key)
        index = self._lower_index(record)
        for alias in FIELD_ALIASES.get(logical, ()):  # aliases are already normalised
            norm = alias.replace("_", "")
            if norm in index:
                real = index[norm]
                value = record.get(real)
                if value not in (None, ""):
                    self.resolved[logical] = real
                    return value
        return None


def _iter_records(payload: Any) -> list[dict[str, Any]]:
    """Find the list of camera records in whatever shape the server returned."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        # GeoJSON FeatureCollection
        if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
            flattened: list[dict[str, Any]] = []
            for feature in payload["features"]:
                if not isinstance(feature, dict):
                    continue
                record = dict(feature.get("properties") or {})
                coords = ((feature.get("geometry") or {}).get("coordinates") or [None, None])
                if isinstance(coords, list) and len(coords) >= 2:
                    record.setdefault("lon", coords[0])
                    record.setdefault("lat", coords[1])
                flattened.append(record)
            return flattened
        lowered = {str(k).lower(): k for k in payload}
        for candidate in LIST_KEYS:
            if candidate in lowered:
                value = payload[lowered[candidate]]
                if isinstance(value, list):
                    return [r for r in value if isinstance(r, dict)]
                if isinstance(value, dict):
                    return _iter_records(value)
        # Single record?
        if any(str(k).lower() in FIELD_ALIASES["url"] for k in payload):
            return [payload]
    return []


def _nested_url(record: dict[str, Any]) -> str | None:
    """Pull a snapshot URL out of a nested views/images array."""
    for key in record:
        if str(key).lower().replace("_", "") in NESTED_VIEW_KEYS:
            value = record[key]
            entries = value if isinstance(value, list) else [value]
            for entry in entries:
                if isinstance(entry, str) and entry.strip():
                    return entry
                if isinstance(entry, dict):
                    resolver = FieldResolver()
                    found = resolver.pick(entry, "url")
                    if found:
                        return str(found)
    return None


@register
class NmdotAdapter(FeedAdapter):
    """New Mexico DOT public camera JSON + snapshot URLs."""

    type = "nmdot"
    auth_required = False
    default_interval_s = 120
    allowed_schemes = ("http", "https")

    DEFAULT_URL = "https://servicev4.nmroads.com/RealMapWAR/GetCameraInfo"
    DEFAULT_SNAPSHOT_BASE = "https://ss.nmroads.com/snapshots/"

    def __init__(self, feed_config: dict[str, Any]):
        super().__init__(feed_config)
        self.url: str = str(self.config.get("url") or self.DEFAULT_URL)
        self.snapshot_base: str = str(self.config.get("snapshot_base") or self.DEFAULT_SNAPSHOT_BASE)
        self.resolver = FieldResolver(self.config.get("field_map"))
        #: Populated by :meth:`list_cameras`; surfaced by ``feeds inspect``.
        self.last_payload_keys: list[str] = []
        self.last_sample_record: dict[str, Any] | None = None
        self.last_record_count: int = 0

    # -- interface -----------------------------------------------------------
    def list_cameras(self) -> list[Camera]:
        try:
            result = safe_fetch(
                self.url,
                allowed_schemes=self.allowed_schemes,
                allow_private=self.allow_private_network,
                headers={"Accept": "application/json"},
            )
            payload = json.loads(result.content.decode("utf-8", errors="replace"))
        except (BlockedRequest, FetchTooLarge, json.JSONDecodeError, OSError) as exc:
            self.record_failure(f"camera list failed: {exc}")
            return []
        except Exception as exc:  # network stack raises a wide range
            self.record_failure(f"camera list failed: {exc}")
            return []

        records = _iter_records(payload)
        self.last_record_count = len(records)
        if isinstance(payload, dict):
            self.last_payload_keys = [str(k) for k in payload][:40]
        elif records:
            self.last_payload_keys = [str(k) for k in records[0]][:40]
        if records:
            self.last_sample_record = {k: redact(v) for k, v in list(records[0].items())[:40]}

        cameras = [cam for cam in (self._to_camera(r) for r in records) if cam is not None]
        if cameras:
            self.record_success()
        else:
            self.record_failure("camera list parsed but produced no usable cameras")
        return self.apply_filter(cameras)

    def get_frame(self, camera: Camera) -> Frame | None:
        url = str(camera.extra.get("url") or "")
        if not url:
            self.record_failure(f"camera {camera.id} has no snapshot URL")
            return None
        try:
            result = safe_fetch(
                url,
                allowed_schemes=self.allowed_schemes,
                allow_private=self.allow_private_network,
                expect=("image/", "application/octet-stream", "binary/"),
            )
            jpeg, size = normalise_to_jpeg(result.content)
        except (BlockedRequest, FetchTooLarge, UnsafeImage) as exc:
            self.record_failure(f"{camera.id}: {exc}")
            return None
        except Exception as exc:
            self.record_failure(f"{camera.id}: {exc}")
            return None

        self.record_success()
        return Frame(
            camera_key=camera.key,
            jpeg=jpeg,
            captured_at=Frame.now(),
            width=size[0],
            height=size[1],
            source_url=redact(url),
        )

    # -- helpers -------------------------------------------------------------
    def _to_camera(self, record: dict[str, Any]) -> Camera | None:
        pick = self.resolver.pick
        raw_url = pick(record, "url") or _nested_url(record)
        if not raw_url:
            return None
        url = self._absolute_url(str(raw_url))
        if not url:
            return None

        raw_id = pick(record, "id") or pick(record, "name") or url
        name = str(pick(record, "name") or raw_id)
        lat = _as_float(pick(record, "lat"))
        lon = _as_float(pick(record, "lon"))
        heading = _as_float(pick(record, "heading"))
        ptz_flag = pick(record, "ptz")

        try:
            return Camera(
                id=str(raw_id),
                name=name,
                lat=lat,
                lon=lon,
                heading=heading,
                # NMDOT cameras are operator-movable; assume PTZ unless told otherwise.
                is_ptz=bool(ptz_flag) if ptz_flag is not None else True,
                source=self.type,
                feed_id=self.feed_id,
                extra={"url": url},
            )
        except Exception as exc:  # pydantic validation of untrusted feed data
            self.record_failure(f"skipped malformed camera record: {exc}")
            return None

    def _absolute_url(self, raw: str) -> str | None:
        raw = raw.strip()
        if not raw:
            return None
        parsed = urlparse(raw)
        if parsed.scheme in ("http", "https"):
            return raw
        if parsed.scheme:  # file:, ftp:, javascript: ... — refuse outright
            return None
        # Bare filename or relative path -> join onto the configured snapshot base.
        return urljoin(self.snapshot_base, raw.lstrip("/"))

    def describe_schema(self) -> dict[str, Any]:
        """What ``python -m feeds inspect`` prints: the server's real key names."""
        return {
            "endpoint": redact(self.url),
            "records_found": self.last_record_count,
            "top_level_keys": self.last_payload_keys,
            "resolved_field_map": dict(self.resolver.resolved),
            "sample_record": self.last_sample_record,
        }


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None
