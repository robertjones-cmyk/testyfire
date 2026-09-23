"""Local-folder adapter — replays JPEGs from disk.

Used for tests, replays and demos with no network at all. Each camera reads
from its own subdirectory; frames are served in filename order and wrap around,
so a folder of N images behaves like a slow live camera.
"""
from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from app.security.images import UnsafeImage, normalise_to_jpeg
from app.security.paths import is_safe_id

from .base import Camera, FeedAdapter, Frame, cameras_from_config
from .registry import register

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


@register
class LocalFolderAdapter(FeedAdapter):
    type = "local_folder"
    auth_required = False
    default_interval_s = 120
    allowed_schemes = ()           # never makes a network request

    def __init__(self, feed_config: dict[str, Any]):
        super().__init__(feed_config)
        self.root = Path(str(self.config.get("folder") or "./data/replay"))
        self._cursors: dict[str, itertools.count] = {}

    def list_cameras(self) -> list[Camera]:
        cameras = cameras_from_config(self.config, source=self.type)
        usable: list[Camera] = []
        for cam in cameras:
            subdir = str(cam.extra.get("subdir") or cam.id)
            if not is_safe_id(subdir):
                self.record_failure(f"{cam.id}: unsafe subdir {subdir!r} ignored")
                continue
            cam.extra["dir"] = str(self.root / subdir)
            usable.append(cam)
        if usable:
            self.record_success()
        else:
            self.record_failure("no usable cameras configured for local_folder feed")
        return self.apply_filter(usable)

    def _files(self, camera: Camera) -> list[Path]:
        directory = Path(str(camera.extra.get("dir") or ""))
        if not directory.is_dir():
            return []
        return sorted(p for p in directory.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)

    def get_frame(self, camera: Camera) -> Frame | None:
        files = self._files(camera)
        if not files:
            self.record_failure(
                f"{camera.id}: no images in {camera.extra.get('dir')} "
                "(run `python scripts/make_fixtures.py` to generate replay frames)"
            )
            return None
        cursor = self._cursors.setdefault(camera.key, itertools.count())
        chosen = files[next(cursor) % len(files)]
        try:
            jpeg, size = normalise_to_jpeg(chosen.read_bytes())
        except (UnsafeImage, OSError) as exc:
            self.record_failure(f"{camera.id}: {exc}")
            return None
        self.record_success()
        return Frame(
            camera_key=camera.key,
            jpeg=jpeg,
            captured_at=Frame.now(),
            width=size[0],
            height=size[1],
            source_url=f"file://{chosen.name}",
        )
