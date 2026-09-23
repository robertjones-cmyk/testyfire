"""Elevation model.

Source: **AWS Terrain Tiles** (``elevation-tiles-prod``), a free public dataset
built from SRTM/NED — no API key, no account. Tiles are ``terrarium`` PNGs
where elevation in metres is ``(R * 256 + G + B / 256) - 32768``.

Tiles are downloaded once and cached under ``blind_spot.dem.cache_dir``. A
``manifest.json`` records each cached tile's SHA-256, and a cached tile whose
checksum no longer matches is discarded and re-fetched, so a corrupted or
tampered cache cannot silently feed the viewshed.

If the network is unavailable and ``allow_synthetic_fallback`` is true, a
synthetic river-valley DEM is generated instead. It is clearly labelled
``synthetic`` all the way through to the UI: **numbers computed from it are
illustrative, not survey data**.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..security.net import safe_fetch

log = logging.getLogger("torch.dem")

TILE_PX = 256


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Fractional web-mercator tile coordinates."""
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(max(-85.05, min(85.05, lat)))
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


@dataclass(slots=True)
class DemGrid:
    """A stitched elevation raster with web-mercator tile-space bounds."""

    elevation: np.ndarray        # metres, shape (rows, cols)
    x0: float                    # tile-space origin (fractional tile coords)
    y0: float
    zoom: int
    source: str                  # "terrarium" or "synthetic"

    def sample(self, lat: float, lon: float) -> float:
        """Nearest-neighbour elevation lookup in metres."""
        tx, ty = lonlat_to_tile(lon, lat, self.zoom)
        col = int((tx - self.x0) * TILE_PX)
        row = int((ty - self.y0) * TILE_PX)
        rows, cols = self.elevation.shape
        col = max(0, min(cols - 1, col))
        row = max(0, min(rows - 1, row))
        return float(self.elevation[row, col])

    @property
    def is_synthetic(self) -> bool:
        return self.source == "synthetic"


class DemSource:
    def __init__(self, config) -> None:
        self.url_template = str(config.get(
            "blind_spot.dem.url_template",
            "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
        ))
        self.zoom = int(config.get("blind_spot.dem.zoom", 12))
        self.cache_dir = Path(config.get("blind_spot.dem.cache_dir", "./data/dem"))
        self.allow_synthetic = bool(config.get("blind_spot.dem.allow_synthetic_fallback", True))
        self._cached: DemGrid | None = None

    # -- cache manifest ------------------------------------------------------
    def _manifest_path(self) -> Path:
        return self.cache_dir / "manifest.json"

    def _manifest(self) -> dict[str, str]:
        try:
            return json.loads(self._manifest_path().read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_manifest(self, manifest: dict[str, str]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path().write_text(json.dumps(manifest, indent=2, sort_keys=True))

    # -- tiles ---------------------------------------------------------------
    def _tile_bytes(self, x: int, y: int) -> bytes | None:
        name = f"{self.zoom}_{x}_{y}.png"
        path = self.cache_dir / name
        manifest = self._manifest()

        if path.exists():
            data = path.read_bytes()
            expected = manifest.get(name)
            actual = hashlib.sha256(data).hexdigest()
            if expected and expected == actual:
                return data
            log.warning("DEM tile %s failed checksum verification — refetching", name)
            path.unlink(missing_ok=True)

        url = self.url_template.format(z=self.zoom, x=x, y=y)
        try:
            result = safe_fetch(url, allowed_schemes=("https",), expect=("image/",))
        except Exception as exc:
            log.warning("DEM tile fetch failed (%s): %s", name, exc)
            return None

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result.content)
        manifest[name] = hashlib.sha256(result.content).hexdigest()
        self._write_manifest(manifest)
        return result.content

    # -- grid ----------------------------------------------------------------
    def grid_for_bounds(
        self, min_lon: float, min_lat: float, max_lon: float, max_lat: float, *, pad_tiles: int = 1
    ) -> DemGrid:
        """Stitch the tiles covering a bounding box into one elevation raster."""
        if self._cached is not None:
            return self._cached

        x_min, y_max = lonlat_to_tile(min_lon, min_lat, self.zoom)
        x_max, y_min = lonlat_to_tile(max_lon, max_lat, self.zoom)
        tx0, tx1 = int(math.floor(x_min)) - pad_tiles, int(math.floor(x_max)) + pad_tiles
        ty0, ty1 = int(math.floor(y_min)) - pad_tiles, int(math.floor(y_max)) + pad_tiles

        cols, rows = (tx1 - tx0 + 1), (ty1 - ty0 + 1)
        canvas = np.full((rows * TILE_PX, cols * TILE_PX), np.nan, dtype=np.float32)
        fetched = 0
        for iy in range(ty0, ty1 + 1):
            for ix in range(tx0, tx1 + 1):
                data = self._tile_bytes(ix, iy)
                if data is None:
                    continue
                try:
                    with Image.open(io.BytesIO(data)) as img:
                        rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
                except Exception as exc:
                    log.warning("DEM tile decode failed: %s", exc)
                    continue
                elevation = (rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0) - 32768.0
                row_offset = (iy - ty0) * TILE_PX
                col_offset = (ix - tx0) * TILE_PX
                canvas[row_offset:row_offset + TILE_PX, col_offset:col_offset + TILE_PX] = elevation
                fetched += 1

        if fetched == 0:
            if not self.allow_synthetic:
                raise RuntimeError(
                    "no DEM tiles could be fetched and blind_spot.dem.allow_synthetic_fallback "
                    "is false"
                )
            log.warning("no DEM tiles available — using the SYNTHETIC fallback DEM")
            self._cached = synthetic_grid(tx0, ty0, cols, rows, self.zoom)
            return self._cached

        # Fill any gaps with the mean so a missing tile cannot poison the maths.
        if np.isnan(canvas).any():
            canvas = np.nan_to_num(canvas, nan=float(np.nanmean(canvas)))
        self._cached = DemGrid(canvas, float(tx0), float(ty0), self.zoom, "terrarium")
        log.info("DEM ready: %d tile(s), %s", fetched, canvas.shape)
        return self._cached


def synthetic_grid(tx0: int, ty0: int, cols: int, rows: int, zoom: int) -> DemGrid:
    """A plausible river-valley DEM for offline runs. Clearly labelled synthetic."""
    height, width = rows * TILE_PX, cols * TILE_PX
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    # Valley floor near the middle column, mesas rising to either side.
    centre = width * 0.5 + 40.0 * np.sin(ys / 260.0)
    distance = np.abs(xs - centre) / max(width * 0.5, 1.0)
    elevation = 1500.0 + 220.0 * np.clip(distance, 0, 1) ** 1.6
    elevation += 12.0 * np.sin(xs / 55.0) * np.cos(ys / 70.0)   # local relief
    elevation -= ys / height * 35.0                              # gentle N-S fall
    return DemGrid(elevation.astype(np.float32), float(tx0), float(ty0), zoom, "synthetic")
