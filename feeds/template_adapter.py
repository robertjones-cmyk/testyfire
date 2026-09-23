"""COPY ME. Template for a new camera feed.

HOW TO USE THIS FILE
====================
1. Copy it:            cp feeds/template_adapter.py feeds/my_vendor.py
2. Rename the class and set `type` to the key you will put in config.yaml.
3. Implement the three methods below.
4. Uncomment the `@register` decorator.
5. Import it in feeds/__init__.py so it registers on start-up.
6. Add a feed block to config.yaml, then run:
       python -m feeds test my_feed_id
7. Add a test in tests/ (copy tests/test_fake_adapter_flow.py).

You only need a new file like this if **no existing adapter fits**. Most
cameras are already covered:

  * a still-image URL            -> use `snapshot_url` (config only)
  * an RTSP stream               -> use `rtsp`        (config only)
  * an HLS .m3u8 stream          -> use `hls`         (config only)
  * a folder of JPEGs            -> use `local_folder`(config only)

See docs/ADDING_A_FEED.md for the decision table.

THINGS THIS TEMPLATE ALREADY DOES FOR YOU
=========================================
* `safe_fetch` applies the SSRF guard: scheme allowlist, private/loopback/
  metadata-IP blocking on every redirect hop, timeouts, a 10 MB cap.
* `normalise_to_jpeg` verifies magic bytes, decodes under a pixel cap
  (decompression-bomb guard), strips EXIF and re-encodes to clean JPEG.
* `Camera.id` is slugified, so a hostile camera name cannot escape the image
  folder.
* `redact()` removes credentials from anything you log or return.

Do not bypass these. If you need something they do not cover, say so in the PR.
"""
from __future__ import annotations

from typing import Any

from app.security.images import UnsafeImage, normalise_to_jpeg
from app.security.net import BlockedRequest, FetchTooLarge, safe_fetch
from app.security.redact import redact

from .base import Camera, FeedAdapter, Frame
from .registry import register  # noqa: F401  (used once you uncomment @register)


# @register          # <-- STEP 4: uncomment this line
class TemplateAdapter(FeedAdapter):
    """One-line description of the vendor/source this adapter talks to."""

    #: STEP 2: the value you write under `type:` in config.yaml. Must be unique.
    type = "template"

    #: True if this feed cannot work without credentials. Shown in the UI and
    #: checked by `python -m feeds test`.
    auth_required = False

    #: Default polling interval in seconds. Be polite: 120 s is the house
    #: default, and public agencies often ask for slower. Never go below the
    #: camera's own refresh rate — you would just re-download the same JPEG.
    default_interval_s = 120

    #: Schemes this adapter is ever allowed to fetch. The SSRF guard enforces
    #: this. Use ("http", "https") for web APIs, ("rtsp", "rtsps") for streams.
    allowed_schemes = ("https",)

    def __init__(self, feed_config: dict[str, Any]):
        super().__init__(feed_config)
        # Read your own config keys here. NEVER read a secret from config:
        # config holds the NAME of an env var, and you read the value.
        #   config.yaml:  api_key_env: MY_VENDOR_API_KEY
        #   here:         self.api_key = self.resolve_env("api_key_env")
        self.base_url: str = str(self.config.get("url") or "")
        self.api_key: str | None = self.resolve_env("api_key_env")

    # ------------------------------------------------------------------ #
    # STEP 3a: which cameras does this feed offer?
    # ------------------------------------------------------------------ #
    def list_cameras(self) -> list[Camera]:
        """Return the list of cameras.

        Two common shapes:

        * *discovered* — call the vendor API and map its JSON to `Camera`;
        * *declared*   — the cameras are listed in config.yaml, in which case
          just do: `return self.apply_filter(cameras_from_config(self.config,
          source=self.type))`.

        Treat every field in the vendor's response as untrusted: `Camera` is a
        pydantic model that caps string lengths and slugifies the id for you.
        Call `self.record_success()` / `self.record_failure(msg)` so the health
        dot in the UI means something.
        """
        try:
            result = safe_fetch(
                self.base_url,
                allowed_schemes=self.allowed_schemes,
                allow_private=self.allow_private_network,
                headers={"Accept": "application/json"},
            )
            payload = result.content  # TODO: json.loads(...) and map the records
        except (BlockedRequest, FetchTooLarge) as exc:
            self.record_failure(f"camera list failed: {exc}")
            return []
        except Exception as exc:
            self.record_failure(f"camera list failed: {exc}")
            return []

        cameras: list[Camera] = []
        # TODO: for record in payload["cameras"]:
        #     cameras.append(Camera(
        #         id=record["id"],                 # slugified for you
        #         name=record["name"],
        #         lat=record.get("lat"),           # None is allowed, but then the
        #         lon=record.get("lon"),           #   camera cannot appear on the
        #         heading=record.get("heading"),   #   map or in the blind-spot
        #         fov=record.get("fov"),           #   calculation until you set
        #         mast_height=record.get("height"),#   it in camera_overrides.
        #         is_ptz=bool(record.get("ptz")),
        #         source=self.type,
        #         feed_id=self.feed_id,
        #         extra={"url": record["snapshot_url"]},  # adapter-private, never
        #     ))                                          #   sent to the UI raw
        del payload

        if cameras:
            self.record_success()
        else:
            self.record_failure("no cameras returned")
        # apply_filter() honours the `filter: {name_contains: [...]}` config block.
        return self.apply_filter(cameras)

    # ------------------------------------------------------------------ #
    # STEP 3b: give me one JPEG for this camera.
    # ------------------------------------------------------------------ #
    def get_frame(self, camera: Camera) -> Frame | None:
        """Return one `Frame`, or `None` on failure. Never raise.

        The rest of the system only ever sees the JPEG bytes, so nothing
        downstream needs to know this vendor exists.
        """
        url = str(camera.extra.get("url") or "")
        if not url:
            self.record_failure(f"{camera.id}: no snapshot URL")
            return None
        try:
            result = safe_fetch(
                url,
                allowed_schemes=self.allowed_schemes,
                allow_private=self.allow_private_network,
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else None,
                expect=("image/",),
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
            source_url=redact(url),   # ALWAYS redact: URLs can carry credentials
        )

    # ------------------------------------------------------------------ #
    # STEP 3c: health. The base class implementation is usually enough.
    # ------------------------------------------------------------------ #
    def health(self) -> dict[str, Any]:
        """Reachable / last success / error count. Override only to add detail."""
        base = super().health()
        base["auth_configured"] = bool(self.api_key)
        return base
