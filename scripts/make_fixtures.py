"""Generate synthetic replay frames for the offline demo.

Produces a deterministic sequence per camera under ``data/replay/<subdir>/``:

* ``bosque_c``: clean frames, then a smoke plume that grows (drives a
  ``possible_smoke`` event, and a ``verified`` one once the fire scenario ramps
  sensor TS-004);
* ``bosque_n``: a PTZ pan part-way through (drives the view-change detector);
* ``bosque_s``: clean throughout (the control camera).

These are synthetic scenes, not photographs: they exercise the pipeline when
the real NMDOT feed is unavailable. Run:

    python scripts/make_fixtures.py
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image

WIDTH, HEIGHT = 960, 540
RNG = np.random.default_rng(20260922)


def _base_scene(pan: float = 0.0, seed: int = 0, tilt: float = 0.0) -> np.ndarray:
    """A plausible high-desert river scene: sky, mesa, bosque band, river."""
    rng = np.random.default_rng(1000 + seed)
    ys, xs = np.mgrid[0:HEIGHT, 0:WIDTH]
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float64)

    # `tilt` moves the horizon: a PTZ tilt-down fills the frame with ground.
    horizon = int(HEIGHT * (0.46 - 0.34 * tilt))
    # Sky: blue gradient, lighter at the horizon.
    t = np.clip(ys / max(horizon, 1), 0, 1)
    img[..., 0] = 120 + 95 * t
    img[..., 1] = 155 + 75 * t
    img[..., 2] = 205 + 40 * t

    # Distant mesa ridge, shifted by `pan` so a PTZ move changes the geometry.
    ridge = horizon - 18 + 12 * np.sin((xs / 150.0) + pan * 3.1) + 6 * np.sin(xs / 47.0 + pan)
    mesa = ys > ridge
    img[mesa] = np.array([150, 126, 110])

    # Bosque (cottonwood band) and ground.
    band_top = horizon + int(HEIGHT * 0.06)
    ground = ys > band_top
    img[ground] = np.array([96, 104, 62])
    texture = rng.normal(0, 9, size=(HEIGHT, WIDTH, 1))
    img[ground] += texture[ground]

    # River, a bright sinuous line through the bosque.
    river_x = WIDTH * (0.42 + 0.10 * pan) + 60 * np.sin(ys / 90.0)
    river = (np.abs(xs - river_x) < 16) & (ys > band_top)
    img[river] = np.array([138, 152, 168])

    img += rng.normal(0, 3.5, size=img.shape)
    return np.clip(img, 0, 255)


def _add_smoke(img: np.ndarray, intensity: float, cx: float, cy: float) -> np.ndarray:
    """Overlay a translucent grey plume: lifts brightness, kills saturation."""
    if intensity <= 0:
        return img
    ys, xs = np.mgrid[0:HEIGHT, 0:WIDTH]
    # A plume that leans and widens as it rises.
    lean = (cy - ys) * 0.22
    width = 34 + 0.55 * np.clip(cy - ys, 0, None)
    dist = np.abs(xs - (cx + lean)) / np.clip(width, 1, None)
    vertical = np.clip((cy - ys) / (HEIGHT * 0.42), 0, 1)
    plume = np.exp(-dist ** 2) * np.clip(1.15 - vertical, 0, 1)
    plume *= (ys < cy)
    # Wispy edges.
    plume *= 0.75 + 0.25 * np.sin(ys / 11.0 + xs / 29.0)
    alpha = np.clip(plume * intensity, 0, 0.92)[..., None]

    smoke_colour = np.array([196.0, 196.0, 199.0])
    return img * (1 - alpha) + smoke_colour * alpha


def _save(img: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path, "JPEG", quality=86)


def build(root: Path, frames: int = 12) -> None:
    # --- bosque_c: clean -> smoke ramp ------------------------------------
    for i in range(frames):
        img = _base_scene(seed=i)
        if i >= frames // 2:
            step = (i - frames // 2 + 1) / (frames - frames // 2)
            img = _add_smoke(img, intensity=0.55 + 0.75 * step,
                             cx=WIDTH * 0.36, cy=HEIGHT * 0.50)
        _save(img, root / "bosque_c" / f"frame_{i:03d}.jpg")

    # --- bosque_n: operator re-aims the camera half-way through -----------
    # A real PTZ move changes framing, not just detail: the camera pans AND
    # tilts down, so the horizon leaves the top half of the frame.
    for i in range(frames):
        moved = i >= frames // 2
        _save(
            _base_scene(pan=0.85 if moved else 0.0, seed=100 + i, tilt=0.95 if moved else 0.0),
            root / "bosque_n" / f"frame_{i:03d}.jpg",
        )

    # --- bosque_s: clean control ------------------------------------------
    for i in range(frames):
        _save(_base_scene(seed=200 + i), root / "bosque_s" / f"frame_{i:03d}.jpg")

    print(f"Wrote {frames * 3} replay frames under {root.resolve()}")
    print("  bosque_c: clean frames then a growing smoke plume")
    print(f"  bosque_n: operator re-aims the camera at frame {frames // 2:03d} (view-change test)")
    print("  bosque_s: clean control camera")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="./data/replay")
    parser.add_argument("--frames", type=int, default=12)
    args = parser.parse_args()
    build(Path(args.out), args.frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
