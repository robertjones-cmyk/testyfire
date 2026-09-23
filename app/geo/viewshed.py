"""Viewshed and blind-spot computation.

For each camera we ask, for every cell of the area of interest: *could this
camera actually see the ground here?* A cell counts as seen when it is

1. inside the camera's view cone (or its 360° disc if the heading is unknown),
2. within ``fusion.view_range_m``, and
3. in line of sight — the terrain between camera and cell does not rise above
   the sight line, given the camera's mast height.

Everything the cameras cannot see becomes the **blind-spot layer**, which is
the sensor-placement proposal.

Accuracy note, stated plainly because it matters for a go/no-go: this is a
bare-earth viewshed from a public DEM. It does **not** model the cottonwood
canopy, buildings, or the actual optics and resolution of each camera, and the
headings and fields of view come from config rather than a survey. Treat the
coverage percentage as an estimate with a wide error bar, not a measurement.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from .. import db
from .dem import DemGrid, DemSource
from .geom import (
    EARTH_RADIUS_M,
    angle_difference,
    bearing_deg,
    haversine_m,
    m2_to_acres,
    point_in_polygon,
    polygon_bounds,
)

log = logging.getLogger("torch.viewshed")


@dataclass(slots=True)
class Cell:
    lat: float
    lon: float
    seen_by: list[str] = field(default_factory=list)

    @property
    def seen(self) -> bool:
        return bool(self.seen_by)


@dataclass(slots=True)
class CameraGeometry:
    key: str
    name: str
    lat: float
    lon: float
    heading: float | None
    fov: float | None
    mast_height: float
    range_m: float

    @property
    def heading_known(self) -> bool:
        return self.heading is not None


def build_grid(polygon, spacing_m: float) -> list[Cell]:
    """Regular lat/lon grid clipped to the area-of-interest polygon."""
    min_lon, min_lat, max_lon, max_lat = polygon_bounds(polygon)
    lat_step = math.degrees(spacing_m / EARTH_RADIUS_M)
    mid_lat = math.radians((min_lat + max_lat) / 2)
    lon_step = lat_step / max(math.cos(mid_lat), 1e-6)

    cells: list[Cell] = []
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            if point_in_polygon(lat, lon, polygon):
                cells.append(Cell(lat, lon))
            lon += lon_step
        lat += lat_step
    return cells


def line_of_sight(
    dem: DemGrid,
    camera: CameraGeometry,
    target_lat: float,
    target_lon: float,
    *,
    step_m: float = 60.0,
    target_height_m: float = 1.6,
) -> bool:
    """Is the target visible from the camera over bare-earth terrain?

    ``target_height_m`` is human/sensor height: we care about seeing something
    standing on the ground, not the soil itself.
    """
    distance = haversine_m(camera.lat, camera.lon, target_lat, target_lon)
    if distance < 1e-6:
        return True
    if distance > camera.range_m:
        return False

    camera_elevation = dem.sample(camera.lat, camera.lon) + camera.mast_height
    target_elevation = dem.sample(target_lat, target_lon) + target_height_m
    steps = max(2, int(distance / step_m))

    # Required slope from camera to target; any terrain above the line blocks it.
    target_slope = (target_elevation - camera_elevation) / distance
    for i in range(1, steps):
        fraction = i / steps
        lat = camera.lat + (target_lat - camera.lat) * fraction
        lon = camera.lon + (target_lon - camera.lon) * fraction
        along = distance * fraction
        # Earth-curvature drop, small at 1.5 km but free to include.
        curvature = (along ** 2) / (2 * EARTH_RADIUS_M)
        terrain = dem.sample(lat, lon) - curvature
        if (terrain - camera_elevation) / along > target_slope:
            return False
    return True


def in_view_direction(camera: CameraGeometry, lat: float, lon: float) -> bool:
    if camera.heading is None or camera.fov is None:
        return True   # unknown heading -> 360 degree disc
    bearing = bearing_deg(camera.lat, camera.lon, lat, lon)
    return angle_difference(bearing, camera.heading) <= camera.fov / 2.0


@dataclass(slots=True)
class ViewshedResult:
    cells: list[Cell]
    spacing_m: float
    cell_area_m2: float
    dem_source: str
    cameras: list[CameraGeometry]

    @property
    def seen_cells(self) -> list[Cell]:
        return [c for c in self.cells if c.seen]

    @property
    def blind_cells(self) -> list[Cell]:
        return [c for c in self.cells if not c.seen]

    def summary(self) -> dict[str, Any]:
        total = len(self.cells)
        seen = len(self.seen_cells)
        total_acres = m2_to_acres(total * self.cell_area_m2)
        blind_acres = m2_to_acres((total - seen) * self.cell_area_m2)
        return {
            "total_cells": total,
            "seen_cells": seen,
            "blind_cells": total - seen,
            "coverage_percent": round(100.0 * seen / total, 1) if total else 0.0,
            "corridor_acres": round(total_acres, 1),
            "blind_acres": round(blind_acres, 1),
            "seen_acres": round(total_acres - blind_acres, 1),
            "cell_spacing_m": self.spacing_m,
            "dem_source": self.dem_source,
            "dem_is_synthetic": self.dem_source == "synthetic",
            "cameras_used": len(self.cameras),
        }


def cameras_from_db(config) -> list[CameraGeometry]:
    default_mast = float(config.get("blind_spot.mast_height_m", 10.0))
    range_m = float(config.get("fusion.view_range_m", 1500))
    out: list[CameraGeometry] = []
    for row in db.query("SELECT * FROM cameras WHERE lat IS NOT NULL AND lon IS NOT NULL"):
        out.append(CameraGeometry(
            key=row["key"], name=row["name"], lat=float(row["lat"]), lon=float(row["lon"]),
            heading=float(row["heading"]) if row["heading"] is not None else None,
            fov=float(row["fov"]) if row["fov"] is not None else None,
            mast_height=float(row["mast_height"] or default_mast),
            range_m=range_m,
        ))
    return out


def compute(config, cameras: Iterable[CameraGeometry] | None = None) -> ViewshedResult:
    polygon = config.get("blind_spot.area_of_interest.polygon", []) or []
    spacing = float(config.get("blind_spot.grid_spacing_m", 80))
    cells = build_grid(polygon, spacing)
    camera_list = list(cameras) if cameras is not None else cameras_from_db(config)

    min_lon, min_lat, max_lon, max_lat = polygon_bounds(polygon)
    # Widen the DEM window so terrain between an outside camera and the corridor
    # is included.
    dem = DemSource(config).grid_for_bounds(min_lon - 0.05, min_lat - 0.05, max_lon + 0.05, max_lat + 0.05)

    for camera in camera_list:
        for cell in cells:
            if cell.seen_by and camera.key in cell.seen_by:
                continue
            if haversine_m(camera.lat, camera.lon, cell.lat, cell.lon) > camera.range_m:
                continue
            if not in_view_direction(camera, cell.lat, cell.lon):
                continue
            if line_of_sight(dem, camera, cell.lat, cell.lon):
                cell.seen_by.append(camera.key)

    result = ViewshedResult(cells, spacing, spacing * spacing, dem.source, camera_list)
    log.info("viewshed: %s", result.summary())
    return result
