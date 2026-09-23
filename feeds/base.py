"""Feed adapter interface.

A *feed* is one source of camera imagery: a public DOT JSON API, a folder of
Axis snapshot URLs, an RTSP NVR, an HLS stream, a folder of JPEGs on disk, or a
vendor API. Every feed implements the same three methods, so the rest of the
system — ingest, view-change, detection, fusion, UI — never learns where a frame
came from.

Adding a new source is therefore *one new file plus a config block*; see
``docs/ADDING_A_FEED.md`` and ``feeds/template_adapter.py``.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Sequence

from pydantic import BaseModel, Field, field_validator

from app.security.paths import slugify_id
from app.security.redact import redact

MAX_NAME_LEN = 120


class Camera(BaseModel):
    """A camera as reported by a feed.

    Everything here may originate in untrusted feed JSON, so strings are length
    capped and ``id`` is forced through :func:`slugify_id` — a camera named
    ``../../etc/x`` can never become a path.
    """

    id: str = Field(max_length=64)
    name: str = Field(max_length=MAX_NAME_LEN)
    lat: float | None = None
    lon: float | None = None
    heading: float | None = None          # degrees clockwise from true north
    fov: float | None = None              # horizontal field of view, degrees
    mast_height: float | None = None      # metres above ground
    is_ptz: bool = False
    source: str = Field(default="", max_length=64)   # adapter type, e.g. "nmdot"
    feed_id: str = Field(default="", max_length=64)
    # Adapter-private data (snapshot URL, subdir, stream URL env var name...).
    # NEVER serialised to the API: it can contain credentials.
    extra: dict[str, Any] = Field(default_factory=dict, repr=False)

    @field_validator("id", mode="before")
    @classmethod
    def _safe_id(cls, value: Any) -> str:
        return slugify_id(str(value)[:64])

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: Any) -> str:
        return str(value or "unnamed")[:MAX_NAME_LEN]

    @field_validator("lat")
    @classmethod
    def _check_lat(cls, value: float | None) -> float | None:
        if value is not None and not (-90.0 <= value <= 90.0):
            raise ValueError("latitude out of range")
        return value

    @field_validator("lon")
    @classmethod
    def _check_lon(cls, value: float | None) -> float | None:
        if value is not None and not (-180.0 <= value <= 180.0):
            raise ValueError("longitude out of range")
        return value

    @property
    def key(self) -> str:
        """Globally unique, filesystem-safe key: ``<feed_id>__<camera_id>``."""
        return f"{slugify_id(self.feed_id or 'feed')}__{self.id}"

    def has_location(self) -> bool:
        return self.lat is not None and self.lon is not None

    def public_dict(self) -> dict[str, Any]:
        """Safe for the API/UI: no ``extra``, and any URL redacted."""
        data = self.model_dump(exclude={"extra"})
        data["key"] = self.key
        data["url_hint"] = redact(self.extra.get("url", "")) if self.extra else ""
        return data


@dataclass(slots=True)
class Frame:
    """One still image. The pipeline only ever sees this."""

    camera_key: str
    jpeg: bytes
    captured_at: datetime
    width: int = 0
    height: int = 0
    source_url: str = ""          # already redacted by the adapter

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)


@dataclass(slots=True)
class FeedHealth:
    reachable: bool = False
    last_success: datetime | None = None
    error_count: int = 0
    last_error: str = ""
    consecutive_failures: int = 0
    backoff_until: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "error_count": self.error_count,
            "last_error": redact(self.last_error),
            "consecutive_failures": self.consecutive_failures,
            "backoff_until": self.backoff_until.isoformat() if self.backoff_until else None,
        }


class FeedAdapter(ABC):
    """Base class every feed implements.

    Subclasses set :attr:`type` (the ``type:`` key used in ``config.yaml``) and
    are registered with :func:`feeds.registry.register`.
    """

    type: ClassVar[str] = "base"
    auth_required: ClassVar[bool] = False
    default_interval_s: ClassVar[int] = 120
    #: URL schemes this adapter may ever fetch. Enforced by the SSRF guard.
    allowed_schemes: ClassVar[tuple[str, ...]] = ("http", "https")

    def __init__(self, feed_config: dict[str, Any]):
        self.config = feed_config or {}
        self.feed_id: str = str(self.config.get("id") or self.type)
        self.interval_s: int = int(self.config.get("interval_s") or self.default_interval_s)
        self.enabled: bool = bool(self.config.get("enabled", True))
        #: LAN/loopback destinations are refused unless a feed opts in.
        self.allow_private_network: bool = bool(self.config.get("allow_private_network", False))
        self.health_state = FeedHealth()
        self._camera_cache: list[Camera] | None = None
        self._camera_cache_at: datetime | None = None

    # -- interface -----------------------------------------------------------
    @abstractmethod
    def list_cameras(self) -> list[Camera]:
        """Return the cameras this feed offers."""

    @abstractmethod
    def get_frame(self, camera: Camera) -> Frame | None:
        """Return one JPEG frame for ``camera``, or ``None`` on failure."""

    def health(self) -> dict[str, Any]:
        """Reachability, last success time and error count."""
        return self.health_state.as_dict()

    # -- shared helpers ------------------------------------------------------
    def record_success(self) -> None:
        self.health_state.reachable = True
        self.health_state.last_success = Frame.now()
        self.health_state.consecutive_failures = 0
        self.health_state.backoff_until = None
        self.health_state.last_error = ""

    def record_failure(self, error: str) -> None:
        self.health_state.reachable = False
        self.health_state.error_count += 1
        self.health_state.consecutive_failures += 1
        self.health_state.last_error = redact(error)[:400]

    def in_backoff(self, now: datetime | None = None) -> bool:
        until = self.health_state.backoff_until
        return bool(until and (now or Frame.now()) < until)

    def backoff_seconds(self) -> int:
        """Exponential backoff, capped at 30 minutes."""
        failures = max(0, self.health_state.consecutive_failures - 1)
        return min(1800, self.interval_s * (2 ** min(failures, 6)))

    def resolve_env(self, key: str) -> str | None:
        """Resolve a ``*_env`` config key to its environment value."""
        var = self.config.get(key)
        return os.environ.get(str(var)) if var else None

    def cameras(self, *, refresh: bool = False, ttl_s: int = 900) -> list[Camera]:
        """Cached :meth:`list_cameras` — feeds are polled politely."""
        now = Frame.now()
        fresh = (
            self._camera_cache is not None
            and self._camera_cache_at is not None
            and (now - self._camera_cache_at).total_seconds() < ttl_s
        )
        if refresh or not fresh:
            self._camera_cache = self.list_cameras()
            self._camera_cache_at = now
        return list(self._camera_cache or [])

    def apply_filter(self, cameras: Sequence[Camera]) -> list[Camera]:
        """Apply the optional ``filter: {name_contains: [...]}`` config block."""
        spec = self.config.get("filter") or {}
        needles = [str(n).lower() for n in (spec.get("name_contains") or [])]
        if not needles:
            return list(cameras)
        kept = []
        for cam in cameras:
            haystack = f"{cam.name} {cam.id}".lower()
            if any(n in haystack for n in needles):
                kept.append(cam)
        return kept

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<{type(self).__name__} feed_id={self.feed_id!r} type={self.type!r}>"


def cameras_from_config(
    feed_config: dict[str, Any],
    *,
    source: str,
    extra_keys: Sequence[str] = ("url", "url_env", "subdir", "path"),
) -> list[Camera]:
    """Build :class:`Camera` objects from an inline ``cameras:`` config list.

    Shared by the adapters whose cameras are declared in config rather than
    discovered from an API (snapshot_url, rtsp, hls, local_folder).
    """
    out: list[Camera] = []
    for entry in feed_config.get("cameras", []) or []:
        extra = {k: entry[k] for k in extra_keys if k in entry}
        out.append(
            Camera(
                id=entry.get("id") or entry.get("name") or "camera",
                name=entry.get("name") or entry.get("id") or "camera",
                lat=entry.get("lat"),
                lon=entry.get("lon"),
                heading=entry.get("heading"),
                fov=entry.get("fov"),
                mast_height=entry.get("mast_height"),
                is_ptz=bool(entry.get("is_ptz", False)),
                source=source,
                feed_id=str(feed_config.get("id") or source),
                extra=extra,
            )
        )
    return out
