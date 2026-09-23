"""MockSensorSource — N virtual Torch sensors along the Rio Grande bosque.

Emits a reading per sensor every ``sensors.emit_interval_s`` (default 60 s)
with a plausible diurnal temperature curve, a low background smoke/gas index,
occasional audio events and a slowly draining battery.

``start_fire_scenario()`` ramps one sensor over ``ramp_minutes`` so a
``possible_smoke`` camera alert can be upgraded to ``verified`` on demand. Every
reading produced during a scenario is tagged ``demo=True``, which propagates to
the event, shows a DEMO badge in the UI, and restricts dispatch to the local
test receiver.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from .base import SensorReading, SensorSource, SensorSpec


class MockSensorSource(SensorSource):
    name = "mock"

    def __init__(self, config) -> None:
        self.config = config
        self._specs = [
            SensorSpec(
                id=str(entry["id"]),
                name=str(entry.get("name", entry["id"])),
                lat=float(entry["lat"]),
                lon=float(entry["lon"]),
                source=self.name,
            )
            for entry in config.get("sensors.mock.sensors", []) or []
        ]
        self.fire_sensor_id = str(config.get("sensors.mock.fire_scenario.sensor_id", ""))
        self.ramp_minutes = float(config.get("sensors.mock.fire_scenario.ramp_minutes", 6))
        self._scenario_started: datetime | None = None
        self._battery = {spec.id: random.uniform(78.0, 99.0) for spec in self._specs}
        self._rng = random.Random(4242)

    # -- interface -----------------------------------------------------------
    def list_sensors(self) -> list[SensorSpec]:
        return list(self._specs)

    def poll(self) -> list[SensorReading]:
        now = datetime.now(timezone.utc)
        return [self._reading(spec, now) for spec in self._specs]

    # -- demo control --------------------------------------------------------
    def start_fire_scenario(self, sensor_id: str | None = None) -> str:
        """Begin ramping one sensor. Returns the sensor id being ramped."""
        if sensor_id:
            self.fire_sensor_id = sensor_id
        self._scenario_started = datetime.now(timezone.utc)
        return self.fire_sensor_id

    def stop_fire_scenario(self) -> None:
        self._scenario_started = None

    @property
    def scenario_active(self) -> bool:
        if self._scenario_started is None:
            return False
        # The ramp holds for a while after peaking so there is time to demo it.
        return datetime.now(timezone.utc) < self._scenario_started + timedelta(
            minutes=self.ramp_minutes + 20
        )

    def scenario_progress(self) -> float:
        """0..1 ramp position, 1.0 once fully ramped."""
        if self._scenario_started is None:
            return 0.0
        elapsed = (datetime.now(timezone.utc) - self._scenario_started).total_seconds() / 60.0
        return float(min(1.0, elapsed / max(self.ramp_minutes, 0.1)))

    # -- generation ----------------------------------------------------------
    def _reading(self, spec: SensorSpec, now: datetime) -> SensorReading:
        # Diurnal curve: coolest around 06:00 UTC-6, warmest mid-afternoon.
        hour = now.hour + now.minute / 60.0
        ambient = 18.0 + 11.0 * math.sin((hour - 9.0) / 24.0 * 2 * math.pi)
        jitter = self._rng.uniform(-0.8, 0.8)
        temp = ambient + jitter
        smoke_index = max(0.0, self._rng.gauss(12.0, 4.0))
        thermal_delta = max(0.0, self._rng.gauss(1.2, 0.7))
        audio_event = self._rng.random() < 0.02
        demo = False

        if self.scenario_active and spec.id == self.fire_sensor_id:
            ramp = self.scenario_progress()
            # PM2.5 + VOC climb hard; the IR sensor sees a hotspot once it is real.
            smoke_index = 12.0 + 260.0 * ramp + self._rng.uniform(-6, 6)
            thermal_delta = 1.2 + 16.0 * ramp
            temp = ambient + 3.0 * ramp
            audio_event = ramp > 0.4 and self._rng.random() < 0.5
            demo = True

        battery = self._battery.get(spec.id, 90.0)
        self._battery[spec.id] = max(20.0, battery - self._rng.uniform(0.0, 0.01))

        return SensorReading(
            sensor_id=spec.id,
            ts=now,
            temp_c=round(temp, 2),
            thermal_hotspot=bool(thermal_delta >= float(
                self.config.get("sensors.thresholds.thermal_delta_c", 8.0)
            )),
            thermal_delta_c=round(thermal_delta, 2),
            smoke_index=round(smoke_index, 1),
            audio_event=audio_event,
            battery=round(self._battery[spec.id], 1),
            demo=demo,
            detail={"scenario": "fire" if demo else "nominal"},
        )
