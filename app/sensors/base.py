"""Sensor source interface.

A Torch sensor is a solar-powered mast at human height with a 5 MP 360 camera,
thermal IR, gas/air-quality sensing and a microphone. This prototype has no
live sensor API, so :class:`~app.sensors.mock.MockSensorSource` stands in;
:class:`~app.sensors.torch_api.TorchApiSensorSource` is the slot for the real
one. Fusion only ever sees :class:`SensorReading`, so swapping the source
changes nothing downstream.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SensorSpec:
    """A physical sensor's identity and location."""

    id: str
    name: str
    lat: float
    lon: float
    source: str = "mock"


@dataclass(slots=True)
class SensorReading:
    """One sample from one sensor."""

    sensor_id: str
    ts: datetime
    temp_c: float
    thermal_hotspot: bool
    thermal_delta_c: float
    smoke_index: float          # PM2.5 + VOC composite, 0..500
    audio_event: bool
    battery: float              # percent
    demo: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def is_anomalous(self, *, smoke_threshold: float, thermal_threshold: float) -> bool:
        """Does this reading indicate smoke/gas or a thermal anomaly?"""
        return bool(
            self.smoke_index >= smoke_threshold
            or self.thermal_hotspot
            or self.thermal_delta_c >= thermal_threshold
        )

    def anomaly_reasons(self, *, smoke_threshold: float, thermal_threshold: float) -> list[str]:
        reasons = []
        if self.smoke_index >= smoke_threshold:
            reasons.append(f"smoke/gas index {self.smoke_index:.0f} ≥ {smoke_threshold:.0f}")
        if self.thermal_hotspot:
            reasons.append("thermal hotspot flag set")
        if self.thermal_delta_c >= thermal_threshold:
            reasons.append(f"thermal delta {self.thermal_delta_c:.1f}°C ≥ {thermal_threshold:.1f}°C")
        if self.audio_event:
            reasons.append("audio event")
        return reasons


class SensorSource(ABC):
    """Where sensor readings come from."""

    name: str = "sensor_source"

    @abstractmethod
    def list_sensors(self) -> list[SensorSpec]:
        """The sensors this source knows about."""

    @abstractmethod
    def poll(self) -> list[SensorReading]:
        """Return the latest reading for each sensor (called every emit_interval_s)."""

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "reachable": True}


def build_sensor_source(config) -> SensorSource:
    from .mock import MockSensorSource
    from .torch_api import TorchApiSensorSource

    choice = str(config.get("sensors.source", "mock")).lower()
    if choice == "torch_api":
        return TorchApiSensorSource(config)
    return MockSensorSource(config)
