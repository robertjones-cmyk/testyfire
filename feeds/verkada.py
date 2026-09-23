"""Verkada adapter — STUB ONLY. This code does not call Verkada.

Everything below is a TODO. Nothing here issues a network request; the adapter
reports itself unhealthy with an explanatory message so the feed is visibly
"not wired up" rather than silently empty.

To finish this adapter you need, from the customer's Verkada org admin:

* an **API key** (Verkada Command -> Admin -> API; org-scoped, read-only is enough)
  -> store in the env var named by ``api_key_env``;
* the **org ID** -> env var named by ``org_id_env``;
* confirmation of the region/base URL for their tenancy.

TODO(feeds/verkada): implement ``list_cameras`` against the camera-list
endpoint (``GET /cameras/v1/devices`` style), mapping device id, name and the
site's lat/lon. Verkada does not publish per-camera heading/FOV, so those still
come from ``camera_overrides`` in config.yaml.

TODO(feeds/verkada): implement ``get_frame`` against the thumbnail/footage-link
endpoint. Prefer the still-image "thumbnail" endpoint over footage links: we
only ever want one JPEG, never video.

TODO(feeds/verkada): optionally subscribe to Verkada's own alert webhook and
feed those events in as a *sensor-like* corroboration source rather than as
camera frames.

TODO(feeds/verkada): many sites are simpler to integrate via RTSP/HLS streaming
— if the customer enables it, the existing ``rtsp``/``hls`` adapters work today
with no new code.
"""
from __future__ import annotations

from typing import Any

from .base import Camera, FeedAdapter, Frame
from .registry import register


@register
class VerkadaAdapter(FeedAdapter):
    type = "verkada"
    auth_required = True
    default_interval_s = 120
    allowed_schemes = ("https",)

    NOT_IMPLEMENTED = (
        "Verkada adapter is a stub: no API call is made. "
        "See the TODOs in feeds/verkada.py, or use the rtsp/hls adapter if the "
        "customer enables streaming."
    )

    def __init__(self, feed_config: dict[str, Any]):
        super().__init__(feed_config)
        self.record_failure(self.NOT_IMPLEMENTED)

    def list_cameras(self) -> list[Camera]:
        self.record_failure(self.NOT_IMPLEMENTED)
        return []

    def get_frame(self, camera: Camera) -> Frame | None:
        self.record_failure(self.NOT_IMPLEMENTED)
        return None
