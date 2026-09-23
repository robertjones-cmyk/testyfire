"""TorchApiSensorSource — STUB for the real Torch platform sensor API.

This repository has no access to the live API, so nothing here makes a request.
Fusion, the UI and the database already speak :class:`SensorReading`, so
finishing this class is the *only* change needed to run the prototype against
real hardware.

TODO(sensors/torch_api): confirm the base URL and auth scheme with the platform
team (bearer token? mTLS? signed request?). Put the credential in an env var
named from config (``sensors.torch_api.token_env``) — never in config.yaml.

TODO(sensors/torch_api): implement ``list_sensors`` against the asset/device
endpoint, mapping device id, display name and lat/lon. The folder/site grouping
the Torch app uses ("All assets / Folders") should map to a sensor tag so the
prototype's site picker matches the real app.

TODO(sensors/torch_api): implement ``poll`` against the latest-readings
endpoint. Map their field names onto SensorReading:
    temp_c, thermal_hotspot, thermal_delta_c, smoke_index (PM2.5+VOC composite),
    audio_event, battery.
If the platform exposes a websocket or webhook stream, prefer that over polling
and push readings into the same ``record_readings`` path.

TODO(sensors/torch_api): decide what a Torch-side alert means here. A sensor
that has already self-alerted should probably count as corroboration
immediately, rather than being re-derived from raw values.
"""
from __future__ import annotations

from typing import Any

from .base import SensorReading, SensorSource, SensorSpec


class TorchApiSensorSource(SensorSource):
    name = "torch_api"

    NOT_IMPLEMENTED = (
        "TorchApiSensorSource is a stub: no live sensor API is wired up. "
        "See the TODOs in app/sensors/torch_api.py, or set sensors.source: mock."
    )

    def __init__(self, config) -> None:
        self.config = config
        self.base_url = str(config.get("sensors.torch_api.base_url", ""))
        self.token_env = str(config.get("sensors.torch_api.token_env", "TORCH_API_TOKEN"))

    def list_sensors(self) -> list[SensorSpec]:
        return []

    def poll(self) -> list[SensorReading]:
        return []

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "reachable": False, "last_error": self.NOT_IMPLEMENTED}
