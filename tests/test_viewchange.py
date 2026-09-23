"""View-change detection: a PTZ move must not look like smoke."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.viewchange import (  # noqa: E402
    ViewChangeDetector,
    evaluate,
    hamming,
    phash,
    ssim,
)

REPLAY = Path(__file__).resolve().parents[1] / "data" / "replay"


def _scene(shift: int = 0, seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:270, 0:480]
    img = np.zeros((270, 480, 3), dtype=np.float64)
    img[..., 2] = 200
    ridge = 120 + 25 * np.sin((xs + shift) / 60.0)
    ground = ys > ridge
    img[ground] = np.array([100, 110, 70])
    img += rng.normal(0, 2.0, img.shape)
    out = io.BytesIO()
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(out, "JPEG", quality=85)
    return out.getvalue()


def test_phash_is_stable_under_noise():
    a, b = _scene(seed=1), _scene(seed=2)
    assert hamming(phash(a), phash(b)) <= 4


def test_phash_changes_when_the_camera_pans():
    assert hamming(phash(_scene(shift=0)), phash(_scene(shift=200))) > 8


def test_ssim_self_is_one():
    frame = _scene()
    assert ssim(frame, frame) == pytest.approx(1.0, abs=1e-6)


def test_ssim_drops_for_a_different_view():
    assert ssim(_scene(shift=0), _scene(shift=220)) < 0.9


# --- the decision function -------------------------------------------------
def test_first_frame_becomes_the_reference():
    result, candidate, count = evaluate(
        new_phash="a" * 16, reference_phash=None, similarity=1.0,
        candidate_phash=None, candidate_count=0,
        distance_threshold=14, ssim_threshold=0.55, stable_frames_to_adopt=3,
    )
    assert result.view_changed is False and result.reference_adopted is True
    assert candidate is None and count == 0


def test_matching_reference_is_not_a_view_change():
    reference = phash(_scene(seed=3))
    result, candidate, count = evaluate(
        new_phash=phash(_scene(seed=4)), reference_phash=reference, similarity=0.95,
        candidate_phash=None, candidate_count=0,
        distance_threshold=14, ssim_threshold=0.55, stable_frames_to_adopt=3,
    )
    assert result.view_changed is False
    assert candidate is None and count == 0


def test_low_ssim_alone_flags_a_view_change():
    reference = phash(_scene(seed=5))
    result, _, count = evaluate(
        new_phash=reference, reference_phash=reference, similarity=0.20,
        candidate_phash=None, candidate_count=0,
        distance_threshold=14, ssim_threshold=0.55, stable_frames_to_adopt=3,
    )
    assert result.view_changed is True and count == 1


def test_new_view_is_adopted_after_three_stable_frames():
    reference = phash(_scene(shift=0, seed=6))
    moved = phash(_scene(shift=240, seed=7))

    candidate, count = None, 0
    adopted_on = None
    for frame_number in range(1, 5):
        result, candidate, count = evaluate(
            new_phash=moved, reference_phash=reference, similarity=0.3,
            candidate_phash=candidate, candidate_count=count,
            distance_threshold=14, ssim_threshold=0.55, stable_frames_to_adopt=3,
        )
        assert result.view_changed is True
        if result.reference_adopted and adopted_on is None:
            adopted_on = frame_number
    assert adopted_on == 3


def test_unstable_view_does_not_get_adopted():
    """A camera still being moved keeps producing new candidates, never a reference.

    Hashes are constructed rather than rendered so the distances are exact: each
    successive view is far from the reference AND far from the previous
    candidate, which is what "still moving" means.
    """
    reference = "0" * 16
    far_apart = [
        f"{(2 ** 40 - 1):016x}",   # 40 bits set
        f"{(2 ** 60 - 1):016x}",   # 60 bits set
        f"{(2 ** 20 - 1):016x}",   # 20 bits set
    ]
    # Sanity: each view really is a long way from the reference and its predecessor.
    assert all(hamming(reference, h) > 14 for h in far_apart)
    assert all(hamming(a, b) > 14 for a, b in zip(far_apart, far_apart[1:]))

    candidate, count = None, 0
    for view_hash in far_apart:
        result, candidate, count = evaluate(
            new_phash=view_hash, reference_phash=reference, similarity=0.3,
            candidate_phash=candidate, candidate_count=count,
            distance_threshold=14, ssim_threshold=0.55, stable_frames_to_adopt=3,
        )
        assert result.view_changed is True
        assert result.reference_adopted is False
        assert count == 1, "each new view restarts the stability count"


# --- against the replay fixtures -------------------------------------------
@pytest.mark.skipif(not (REPLAY / "bosque_n").is_dir(), reason="run scripts/make_fixtures.py first")
def test_detector_flags_the_pan_in_the_replay_camera(database, config):
    detector = ViewChangeDetector(config)
    frames = sorted((REPLAY / "bosque_n").iterdir())
    flags = [detector.check("bosque_n", path.read_bytes()).view_changed for path in frames]

    assert not any(flags[:len(frames) // 2]), "steady frames must not be flagged"
    assert flags[len(frames) // 2], "the pan must be flagged on the frame it happens"


@pytest.mark.skipif(not (REPLAY / "bosque_c").is_dir(), reason="run scripts/make_fixtures.py first")
def test_growing_smoke_is_not_mistaken_for_a_view_change(database, config):
    """Smoke must stay a smoke signal, not get written off as a camera move."""
    detector = ViewChangeDetector(config)
    frames = sorted((REPLAY / "bosque_c").iterdir())
    flags = [detector.check("bosque_c", path.read_bytes()).view_changed for path in frames]
    assert not any(flags), "a plume changed the scene but the camera did not move"
