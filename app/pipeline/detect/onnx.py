"""Optional ONNX smoke model — disabled until weights are pinned.

Why this is not the default
---------------------------
The obvious choice is a YOLO model trained on the public **D-Fire** dataset.
The problem is licensing: the popular YOLOv5/YOLOv8 packages (Ultralytics) are
**AGPL-3.0**, which is a poor fit for a commercial product, and many published
D-Fire checkpoints inherit that licence. Rather than quietly ship an AGPL
dependency, the prototype defaults to the dependency-free
:class:`~app.pipeline.detect.baseline.BaselineDetector`, and this class is the
slot for a **permissively licensed (MIT/Apache-2.0/BSD)** ONNX model once one
is chosen and its licence recorded.

To enable it:

1. pick a model whose licence is MIT/Apache-2.0/BSD and record it in
   ``detection.onnx.license``;
2. set ``detection.onnx.url`` and the expected ``sha256`` (weights are only
   loaded if the checksum matches — see :func:`ensure_weights`);
3. ``pip install onnxruntime`` (MIT) and set ``detection.detector: onnx``.

Nothing here downloads anything unless ``detection.onnx.enabled`` is true.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from ...security.net import safe_fetch
from .base import DetectionResult, Detector


class WeightsUnavailable(Exception):
    pass


def ensure_weights(url: str, sha256: str, dest: Path) -> Path:
    """Download weights from a pinned URL and verify the checksum.

    A mismatch deletes the file and raises: we never load unverified weights.
    """
    if not url or not sha256:
        raise WeightsUnavailable(
            "detection.onnx.url and detection.onnx.sha256 must both be set before "
            "the ONNX detector can be used"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and _sha256(dest) == sha256.lower():
        return dest

    result = safe_fetch(url, allowed_schemes=("https",), max_bytes=200 * 1024 * 1024)
    dest.write_bytes(result.content)
    actual = _sha256(dest)
    if actual != sha256.lower():
        dest.unlink(missing_ok=True)
        raise WeightsUnavailable(
            f"checksum mismatch for model weights: expected {sha256}, got {actual}"
        )
    return dest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OnnxSmokeDetector(Detector):
    name = "onnx"

    def __init__(self, config) -> None:
        self.enabled = bool(config.get("detection.onnx.enabled", False))
        self.url = str(config.get("detection.onnx.url", ""))
        self.sha256 = str(config.get("detection.onnx.sha256", ""))
        self.license = str(config.get("detection.onnx.license", ""))
        self.input_size = int(config.get("detection.onnx.input_size", 640))
        self.weights_path = Path(config.get("app.data_dir", "./data")) / "models" / "smoke.onnx"
        self._session = None
        # Fall back to the baseline so choosing "onnx" without weights still runs.
        from .baseline import BaselineDetector

        self._fallback = BaselineDetector(config)

    def _load(self):
        if self._session is not None:
            return self._session
        if not self.enabled:
            raise WeightsUnavailable("detection.onnx.enabled is false")
        if not self.license:
            raise WeightsUnavailable(
                "refusing to load model weights with no recorded licence "
                "(set detection.onnx.license)"
            )
        try:
            import onnxruntime  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise WeightsUnavailable("onnxruntime is not installed (pip install onnxruntime)") from exc
        path = ensure_weights(self.url, self.sha256, self.weights_path)
        self._session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        return self._session

    def reset(self, camera_key: str) -> None:
        self._fallback.reset(camera_key)

    def detect(self, jpeg: bytes, *, camera_key: str) -> DetectionResult:
        started = time.perf_counter()
        try:
            self._load()
        except WeightsUnavailable as exc:
            result = self._fallback.detect(jpeg, camera_key=camera_key)
            result.detail["onnx"] = f"unavailable, used baseline instead: {exc}"
            return result

        # TODO(detect/onnx): pre-process to the model's input size, run
        # self._session.run(...), and map the highest-confidence smoke box to a
        # normalised bbox. Left unimplemented on purpose: wiring it to a model
        # we have not licence-checked would be worse than an honest TODO.
        result = self._fallback.detect(jpeg, camera_key=camera_key)
        result.detail["onnx"] = "session loaded but post-processing is not implemented (TODO)"
        result.inference_ms = (time.perf_counter() - started) * 1000
        return result
