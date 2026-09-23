"""Generic "camera with a JPEG snapshot URL" adapter.

Fits the large majority of IP cameras, including Axis
(``/axis-cgi/jpg/image.cgi``), Hikvision (``/ISAPI/Streaming/channels/101/picture``)
and most public DOT still-image endpoints. Cameras are declared in config;
optional HTTP basic or digest credentials are read from environment variables.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.security.images import UnsafeImage, normalise_to_jpeg
from app.security.net import BlockedRequest, FetchTooLarge, safe_fetch
from app.security.redact import redact

from .base import Camera, FeedAdapter, Frame, cameras_from_config
from .registry import register


@register
class SnapshotUrlAdapter(FeedAdapter):
    type = "snapshot_url"
    auth_required = False          # optional; set per feed via `auth:`
    default_interval_s = 120
    allowed_schemes = ("http", "https")

    def __init__(self, feed_config: dict[str, Any]):
        super().__init__(feed_config)
        self.auth_spec: dict[str, Any] = self.config.get("auth") or {}

    def _auth(self) -> httpx.Auth | None:
        kind = str(self.auth_spec.get("type") or "").lower()
        if kind not in ("basic", "digest"):
            return None
        username = self.resolve_env_from(self.auth_spec, "username_env")
        password = self.resolve_env_from(self.auth_spec, "password_env")
        if not username or not password:
            raise BlockedRequest(
                f"feed {self.feed_id}: auth is configured as {kind} but "
                f"{self.auth_spec.get('username_env')}/{self.auth_spec.get('password_env')} "
                "are not set in the environment"
            )
        return httpx.DigestAuth(username, password) if kind == "digest" else httpx.BasicAuth(username, password)

    @staticmethod
    def resolve_env_from(spec: dict[str, Any], key: str) -> str | None:
        import os

        var = spec.get(key)
        return os.environ.get(str(var)) if var else None

    def list_cameras(self) -> list[Camera]:
        cameras = cameras_from_config(self.config, source=self.type)
        for cam in cameras:
            # A camera may name an env var instead of an inline URL.
            if not cam.extra.get("url") and cam.extra.get("url_env"):
                import os

                cam.extra["url"] = os.environ.get(str(cam.extra["url_env"]), "")
        usable = [c for c in cameras if c.extra.get("url")]
        if usable:
            self.record_success()
        elif cameras:
            self.record_failure("no camera in this feed resolved to a URL")
        return self.apply_filter(usable)

    def get_frame(self, camera: Camera) -> Frame | None:
        url = str(camera.extra.get("url") or "")
        if not url:
            self.record_failure(f"{camera.id}: no URL")
            return None
        try:
            result = safe_fetch(
                url,
                allowed_schemes=self.allowed_schemes,
                allow_private=self.allow_private_network,
                auth=self._auth(),
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
