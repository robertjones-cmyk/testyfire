"""HLS adapter — one frame every N seconds from an ``.m3u8`` playlist."""
from __future__ import annotations

import os

from app.security.images import UnsafeImage, normalise_to_jpeg
from app.security.net import BlockedRequest, check_url
from app.security.redact import redact

from .base import Camera, FeedAdapter, Frame, cameras_from_config
from .ffmpeg_grab import FfmpegGrabFailed, FfmpegUnavailable, grab_frame
from .registry import register


@register
class HlsAdapter(FeedAdapter):
    type = "hls"
    auth_required = False
    default_interval_s = 300
    allowed_schemes = ("http", "https")

    PROTOCOLS = "https,tls,tcp,http,file,crypto"

    def list_cameras(self) -> list[Camera]:
        cameras = cameras_from_config(self.config, source=self.type)
        usable: list[Camera] = []
        for cam in cameras:
            url = cam.extra.get("url") or (
                os.environ.get(str(cam.extra["url_env"]), "") if cam.extra.get("url_env") else ""
            )
            if not url:
                self.record_failure(f"{cam.id}: no HLS URL configured")
                continue
            cam.extra["url"] = url
            usable.append(cam)
        if usable:
            self.record_success()
        return self.apply_filter(usable)

    def get_frame(self, camera: Camera) -> Frame | None:
        url = str(camera.extra.get("url") or "")
        try:
            check_url(url, allowed_schemes=self.allowed_schemes, allow_private=self.allow_private_network)
            raw = grab_frame(url, protocols=self.PROTOCOLS, rtsp_transport=None)
            jpeg, size = normalise_to_jpeg(raw)
        except (BlockedRequest, FfmpegGrabFailed, FfmpegUnavailable, UnsafeImage) as exc:
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
