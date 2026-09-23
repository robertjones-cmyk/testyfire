"""Detector interface.

Two implementations ship today:

* :class:`~app.pipeline.detect.baseline.BaselineDetector` — cheap, runs on
  every frame, no model weights, no network, no GPU;
* :class:`~app.pipeline.detect.vision_llm.VisionLLMEscalation` — optional
  second opinion on frames the baseline already found suspicious.

A third, :class:`~app.pipeline.detect.onnx.OnnxSmokeDetector`, is wired up for
a permissively-licensed ONNX model but is disabled until weights are pinned.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DetectionResult:
    """One detector's opinion about one frame."""

    score: float                      # 0..1
    #: Normalised [x, y, w, h] in 0..1 frame coordinates, or None.
    bbox: list[float] | None = None
    detector: str = ""
    inference_ms: float = 0.0
    cost_usd: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)

    def clamp(self) -> "DetectionResult":
        self.score = max(0.0, min(1.0, float(self.score)))
        return self


class Detector(ABC):
    """Anything that scores a JPEG frame for wildfire smoke."""

    name: str = "detector"

    @abstractmethod
    def detect(self, jpeg: bytes, *, camera_key: str) -> DetectionResult:
        """Score one frame. Must never raise: return score 0.0 on failure."""

    def reset(self, camera_key: str) -> None:
        """Drop any per-camera temporal state (called after a view change)."""


def build_detector(config) -> Detector:
    """Instantiate the detector named by ``detection.detector`` in config."""
    from .baseline import BaselineDetector
    from .onnx import OnnxSmokeDetector

    choice = str(config.get("detection.detector", "baseline")).lower()
    if choice == "onnx":
        return OnnxSmokeDetector(config)
    return BaselineDetector(config)
