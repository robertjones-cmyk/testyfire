"""BaselineDetector — cheap per-frame smoke scoring.

Runs on every frame on a laptop CPU in a few milliseconds, with **no model
weights and no network call**, so it has no licensing or cost exposure at all
(see the licence note in README.md for why we did not ship a YOLO/D-Fire model
by default).

What it looks for, in the configured sky/horizon region:

1. **Desaturation** — smoke is grey. Clear sky is blue (saturated); terrain is
   green/brown. A grey, mid-bright pixel where there was colour before is the
   core signal.
2. **Temporal change** — the strongest discriminator. Each camera keeps a short
   rolling baseline of recent stable frames; smoke appears as a region that
   departs from that baseline. Static haze, a permanently pale horizon or a
   grey building are in the baseline, so they score ~0.
3. **Contrast collapse** — smoke veils detail, so local gradient energy drops
   where the plume is.

The three signals are combined into a 0..1 score and the strongest connected
band gives the bounding box. Temporal state is reset on a view change, because
after a PTZ move the old baseline describes a different scene.
"""
from __future__ import annotations

import io
import time
from collections import deque

import numpy as np
from PIL import Image

from .base import DetectionResult, Detector

WORK_W, WORK_H = 240, 135        # analysis resolution: fast and noise-tolerant
BASELINE_FRAMES = 5


def _decode(jpeg: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(jpeg)) as img:
        small = img.convert("RGB").resize((WORK_W, WORK_H), Image.BILINEAR)
        return np.asarray(small, dtype=np.float32) / 255.0


def _saturation(rgb: np.ndarray) -> np.ndarray:
    high = rgb.max(axis=2)
    low = rgb.min(axis=2)
    return np.where(high > 1e-6, (high - low) / np.maximum(high, 1e-6), 0.0)


def _gradient_energy(gray: np.ndarray) -> np.ndarray:
    gy = np.zeros_like(gray)
    gx = np.zeros_like(gray)
    gy[1:-1, :] = np.abs(gray[2:, :] - gray[:-2, :])
    gx[:, 1:-1] = np.abs(gray[:, 2:] - gray[:, :-2])
    return gx + gy


class BaselineDetector(Detector):
    name = "baseline"

    def __init__(self, config) -> None:
        self.sky_fraction = float(config.get("detection.sky_region_fraction", 0.55))
        self._baselines: dict[str, deque[np.ndarray]] = {}
        self._grad_baselines: dict[str, deque[np.ndarray]] = {}

    def reset(self, camera_key: str) -> None:
        self._baselines.pop(camera_key, None)
        self._grad_baselines.pop(camera_key, None)

    def detect(self, jpeg: bytes, *, camera_key: str) -> DetectionResult:
        started = time.perf_counter()
        try:
            rgb = _decode(jpeg)
        except Exception as exc:  # a corrupt frame must not stop ingest
            return DetectionResult(0.0, None, self.name, 0.0, 0.0, {"error": str(exc)[:200]})

        rows = max(8, int(WORK_H * self.sky_fraction))
        region = rgb[:rows]
        gray = region.mean(axis=2)
        sat = _saturation(region)
        grad = _gradient_energy(gray)

        history = self._baselines.setdefault(camera_key, deque(maxlen=BASELINE_FRAMES))
        grad_history = self._grad_baselines.setdefault(camera_key, deque(maxlen=BASELINE_FRAMES))

        detail: dict[str, float | str] = {}
        bbox: list[float] | None = None

        if not history:
            # First frame for this camera: learn, do not accuse.
            history.append(gray.copy())
            grad_history.append(grad.copy())
            elapsed = (time.perf_counter() - started) * 1000
            return DetectionResult(
                0.0, None, self.name, elapsed, 0.0,
                {"note": "building temporal baseline"},
            )

        base_gray = np.mean(np.stack(history), axis=0)
        base_grad = np.mean(np.stack(grad_history), axis=0)

        # --- signal 1: grey where it should not be --------------------------
        greyish = (sat < 0.16) & (gray > 0.28) & (gray < 0.97)

        # --- signal 2: departure from this camera's own recent history ------
        delta = np.abs(gray - base_gray)
        changed = delta > 0.045

        # --- signal 3: detail veiled by the plume ---------------------------
        grad_drop = np.clip(base_grad - grad, 0, None)

        mask = greyish & changed
        coverage = float(mask.mean())
        mask_pixels = int(mask.sum())
        # A handful of stray pixels is noise, not a plume.
        significant = mask_pixels >= 24

        # A plume also *lowers* colour where colour used to be.
        base_sat_proxy = float(np.mean(sat[~mask])) if (~mask).any() else float(sat.mean())
        sat_drop = float(np.clip(base_sat_proxy - np.mean(sat[mask]), 0, 1)) if significant else 0.0
        veil = float(grad_drop[mask].mean()) if significant else 0.0

        # --- combine --------------------------------------------------------
        # Sub-linear in coverage: a distant plume is a small part of the frame,
        # so the response has to rise fast at 1-2% and then saturate.
        coverage_term = float(np.clip(np.sqrt(coverage / 0.06), 0, 1)) if significant else 0.0
        sat_term = float(np.clip(sat_drop / 0.18, 0, 1))
        veil_term = float(np.clip(veil / 0.05, 0, 1))
        score = 0.55 * coverage_term + 0.25 * sat_term + 0.20 * veil_term

        # A change covering almost everything is a lighting/exposure shift or a
        # camera move, not a plume: damp it.
        if coverage > 0.70:
            score *= 0.35
            detail["damped"] = "change covers most of the region"

        if mask.any() and score > 0.15:
            bbox = _mask_bbox(mask, rows)

        detail.update({
            "coverage": round(coverage, 4),
            "mask_pixels": mask_pixels,
            "sat_drop": round(sat_drop, 4),
            "veil": round(veil, 4),
            "baseline_frames": len(history),
        })

        # Only frames that look ordinary feed the baseline, so a slowly growing
        # plume cannot quietly become "normal".
        if score < 0.30:
            history.append(gray.copy())
            grad_history.append(grad.copy())

        elapsed = (time.perf_counter() - started) * 1000
        return DetectionResult(score, bbox, self.name, elapsed, 0.0, detail).clamp()


def _mask_bbox(mask: np.ndarray, region_rows: int) -> list[float]:
    """Normalised [x, y, w, h] of the densest band of the mask."""
    cols = mask.sum(axis=0).astype(np.float32)
    rows_profile = mask.sum(axis=1).astype(np.float32)
    col_idx = np.where(cols > max(1.0, cols.max() * 0.25))[0]
    row_idx = np.where(rows_profile > max(1.0, rows_profile.max() * 0.25))[0]
    if col_idx.size == 0 or row_idx.size == 0:
        return [0.0, 0.0, 1.0, region_rows / WORK_H]
    x0, x1 = int(col_idx[0]), int(col_idx[-1]) + 1
    y0, y1 = int(row_idx[0]), int(row_idx[-1]) + 1
    # Pad slightly so the box reads as a region, not a hairline.
    x0 = max(0, x0 - 2)
    y0 = max(0, y0 - 2)
    x1 = min(WORK_W, x1 + 2)
    y1 = min(region_rows, y1 + 2)
    return [
        round(x0 / WORK_W, 4),
        round(y0 / WORK_H, 4),
        round((x1 - x0) / WORK_W, 4),
        round((y1 - y0) / WORK_H, 4),
    ]
