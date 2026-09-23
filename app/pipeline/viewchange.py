"""View-change detection for PTZ cameras.

NMDOT-style cameras get panned and tilted by operators. A moved camera looks
like a completely different scene, which would otherwise produce a burst of
false smoke alerts. So:

* every frame gets a 64-bit DCT perceptual hash;
* it is compared against the camera's **reference frame** by Hamming distance
  and by a structural-similarity score;
* if either says the view moved, the frame is marked ``view_changed`` and
  **no smoke alert is raised from it**;
* once the new view has been stable for N frames (default 3), it is adopted as
  the new reference;
* view changes are counted per camera per day — one of the kill-criteria
  metrics.

Pure numpy: no OpenCV, no model, runs in ~2 ms per frame on a laptop CPU.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from PIL import Image

from .. import db

HASH_SIZE = 8          # 8x8 low-frequency DCT block -> 64-bit hash
DCT_INPUT = 32


def to_gray_array(jpeg: bytes, size: tuple[int, int] = (DCT_INPUT, DCT_INPUT)) -> np.ndarray:
    with Image.open(io.BytesIO(jpeg)) as img:
        gray = img.convert("L").resize(size, Image.LANCZOS)
        return np.asarray(gray, dtype=np.float64)


def _dct_2d(block: np.ndarray) -> np.ndarray:
    """2-D DCT-II via matrix multiplication (small input, so this is cheap)."""
    n = block.shape[0]
    k = np.arange(n)
    basis = np.cos(np.pi * (2 * k[:, None] + 1) * k[None, :] / (2 * n))
    basis[0, :] = basis[0, :] * (1 / np.sqrt(2))
    return basis @ block @ basis.T


def phash(jpeg: bytes) -> str:
    """64-bit perceptual hash as a 16-character hex string."""
    gray = to_gray_array(jpeg)
    dct = _dct_2d(gray)[:HASH_SIZE, :HASH_SIZE]
    # Exclude the DC term from the median so overall brightness does not flip bits.
    coefficients = dct.flatten()
    median = np.median(coefficients[1:])
    bits = coefficients > median
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def hamming(hash_a: str, hash_b: str) -> int:
    if not hash_a or not hash_b:
        return 64
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")


def ssim(jpeg_a: bytes, jpeg_b: bytes, size: tuple[int, int] = (128, 128)) -> float:
    """Global structural similarity on a downscaled grayscale pair (0..1)."""
    a = to_gray_array(jpeg_a, size)
    b = to_gray_array(jpeg_b, size)
    return ssim_arrays(a, b)


def ssim_arrays(a: np.ndarray, b: np.ndarray) -> float:
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu_a, mu_b = a.mean(), b.mean()
    var_a, var_b = a.var(), b.var()
    cov = ((a - mu_a) * (b - mu_b)).mean()
    numerator = (2 * mu_a * mu_b + c1) * (2 * cov + c2)
    denominator = (mu_a ** 2 + mu_b ** 2 + c1) * (var_a + var_b + c2)
    return float(numerator / denominator) if denominator else 0.0


@dataclass(slots=True)
class ViewChangeResult:
    view_changed: bool
    phash: str
    distance: int
    ssim: float
    reference_adopted: bool
    reason: str = ""


def evaluate(
    *,
    new_phash: str,
    reference_phash: str | None,
    similarity: float,
    candidate_phash: str | None,
    candidate_count: int,
    distance_threshold: int,
    ssim_threshold: float,
    stable_frames_to_adopt: int,
) -> tuple[ViewChangeResult, str | None, int]:
    """Pure decision function.

    Returns ``(result, new_candidate_phash, new_candidate_count)``. Kept free of
    I/O so the behaviour is directly unit-testable (see tests/test_viewchange.py).
    """
    if not reference_phash:
        return (
            ViewChangeResult(False, new_phash, 0, similarity, True, "first frame becomes reference"),
            None,
            0,
        )

    distance = hamming(new_phash, reference_phash)
    moved = distance > distance_threshold or similarity < ssim_threshold

    if not moved:
        # Back on the reference view: drop any pending candidate.
        return (
            ViewChangeResult(False, new_phash, distance, similarity, False, "matches reference"),
            None,
            0,
        )

    # The view moved. Is it settling on a new stable view?
    if candidate_phash and hamming(new_phash, candidate_phash) <= distance_threshold:
        count = candidate_count + 1
    else:
        candidate_phash, count = new_phash, 1

    if count >= stable_frames_to_adopt:
        return (
            ViewChangeResult(
                True, new_phash, distance, similarity, True,
                f"new view stable for {count} frames — reference adopted",
            ),
            None,
            0,
        )

    return (
        ViewChangeResult(
            True, new_phash, distance, similarity, False,
            f"view changed (distance {distance}, ssim {similarity:.2f}), "
            f"{count}/{stable_frames_to_adopt} stable frames",
        ),
        candidate_phash,
        count,
    )


class ViewChangeDetector:
    """Stateful wrapper that persists each camera's reference frame."""

    def __init__(self, config) -> None:
        self.distance_threshold = int(config.get("view_change.phash_distance_threshold", 14))
        self.ssim_threshold = float(config.get("view_change.ssim_threshold", 0.55))
        self.stable_frames = int(config.get("view_change.stable_frames_to_adopt", 3))
        self._reference_jpeg: dict[str, bytes] = {}

    def check(self, camera_key: str, jpeg: bytes, frame_id: int | None = None) -> ViewChangeResult:
        new_hash = phash(jpeg)
        row = db.query_one("SELECT * FROM camera_reference WHERE camera_key = ?", (camera_key,))

        reference_jpeg = self._reference_jpeg.get(camera_key)
        similarity = ssim(jpeg, reference_jpeg) if reference_jpeg else 1.0

        result, candidate, count = evaluate(
            new_phash=new_hash,
            reference_phash=row["phash"] if row else None,
            similarity=similarity,
            candidate_phash=row["candidate_phash"] if row else None,
            candidate_count=int(row["candidate_count"]) if row else 0,
            distance_threshold=self.distance_threshold,
            ssim_threshold=self.ssim_threshold,
            stable_frames_to_adopt=self.stable_frames,
        )

        now = datetime.now(timezone.utc).isoformat()
        if result.reference_adopted:
            db.execute(
                "INSERT INTO camera_reference (camera_key, phash, frame_id, updated_at,"
                " candidate_phash, candidate_count) VALUES (?,?,?,?,NULL,0)"
                " ON CONFLICT(camera_key) DO UPDATE SET phash=excluded.phash,"
                " frame_id=excluded.frame_id, updated_at=excluded.updated_at,"
                " candidate_phash=NULL, candidate_count=0",
                (camera_key, new_hash, frame_id, now),
            )
            self._reference_jpeg[camera_key] = jpeg
        elif row is not None:
            db.execute(
                "UPDATE camera_reference SET candidate_phash = ?, candidate_count = ?,"
                " updated_at = ? WHERE camera_key = ?",
                (candidate, count, now, camera_key),
            )
        return result


def view_changes_today(camera_key: str) -> int:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM frames WHERE camera_key = ? AND view_changed = 1 AND ts LIKE ?",
        (camera_key, f"{day}%"),
    )
    return int(row["n"]) if row else 0
