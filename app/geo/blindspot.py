"""Blind-spot report: viewshed + placement + GeoJSON + the headline summary.

Cached because a full run takes a few seconds; ``refresh=True`` recomputes.
"""
from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from typing import Any

from .geom import EARTH_RADIUS_M, m2_to_acres
from .placement import as_dicts, propose, proposals_csv
from .viewshed import Cell, ViewshedResult, compute

_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


def _cell_polygon(cell: Cell, spacing_m: float) -> list[list[float]]:
    half_lat = math.degrees(spacing_m / 2 / EARTH_RADIUS_M)
    half_lon = half_lat / max(math.cos(math.radians(cell.lat)), 1e-6)
    return [
        [cell.lon - half_lon, cell.lat - half_lat],
        [cell.lon + half_lon, cell.lat - half_lat],
        [cell.lon + half_lon, cell.lat + half_lat],
        [cell.lon - half_lon, cell.lat + half_lat],
        [cell.lon - half_lon, cell.lat - half_lat],
    ]


def _multipolygon(cells: list[Cell], spacing_m: float) -> dict[str, Any]:
    return {
        "type": "MultiPolygon",
        "coordinates": [[_cell_polygon(cell, spacing_m)] for cell in cells],
    }


def _circle(lat: float, lon: float, radius_m: float, steps: int = 28) -> list[list[float]]:
    ring = []
    for i in range(steps + 1):
        angle = 2 * math.pi * i / steps
        dlat = math.degrees(radius_m * math.cos(angle) / EARTH_RADIUS_M)
        dlon = math.degrees(radius_m * math.sin(angle) / EARTH_RADIUS_M) / max(
            math.cos(math.radians(lat)), 1e-6
        )
        ring.append([lon + dlon, lat + dlat])
    return ring


def build(config, *, refresh: bool = False) -> dict[str, Any]:
    with _LOCK:
        if not refresh and _CACHE.get("report"):
            return _CACHE["report"]

        result: ViewshedResult = compute(config)
        summary = result.summary()
        proposals = propose(result.blind_cells, config, cell_area_m2=result.cell_area_m2)

        unit_cost = float(config.get("blind_spot.sensor.unit_cost_usd", 299))
        coverage_acres = float(config.get("blind_spot.sensor.coverage_acres", 10.0))
        max_sensors = int(config.get("blind_spot.max_proposed_sensors", 400))
        hardware_cost = len(proposals) * unit_cost

        # Report the acreage the proposals ACTUALLY cover, not the whole blind
        # area: the placement run stops at max_proposed_sensors, and claiming
        # the full blind area at that point would overstate coverage.
        proposed_acres = round(sum(p.covers_acres for p in proposals), 1)
        still_blind_acres = round(max(0.0, summary["blind_acres"] - proposed_acres), 1)
        capped = len(proposals) >= max_sensors and still_blind_acres > 0.5

        summary.update({
            "proposed_sensors": len(proposals),
            "sensor_unit_cost_usd": unit_cost,
            "sensor_coverage_acres": coverage_acres,
            "hardware_cost_usd": hardware_cost,
            "proposed_coverage_acres": proposed_acres,
            "uncovered_after_proposal_acres": still_blind_acres,
            "placement_capped": capped,
            "max_proposed_sensors": max_sensors,
            "area_of_interest": str(config.get("blind_spot.area_of_interest.name", "Area of interest")),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            # The exact sentence the dashboard and the docs quote.
            "headline": (
                f"Cameras see {summary['coverage_percent']}% of the corridor. "
                f"{len(proposals)} sensors cover {proposed_acres:.0f} of the "
                f"{summary['blind_acres']:.0f} blind acres. "
                f"Hardware cost {len(proposals)} x ${unit_cost:.0f} = ${hardware_cost:,.0f}."
                + (f" Placement stopped at the {max_sensors}-sensor cap; "
                   f"{still_blind_acres:.0f} acres remain uncovered."
                   if capped else "")
            ),
        })

        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [list(config.get("blind_spot.area_of_interest.polygon", []))],
                    },
                    "properties": {"layer": "area_of_interest", "name": summary["area_of_interest"]},
                },
                {
                    "type": "Feature",
                    "geometry": _multipolygon(result.seen_cells, result.spacing_m),
                    "properties": {
                        "layer": "camera_coverage",
                        "acres": summary["seen_acres"],
                        "description": "Ground at least one camera can see",
                    },
                },
                {
                    "type": "Feature",
                    "geometry": _multipolygon(result.blind_cells, result.spacing_m),
                    "properties": {
                        "layer": "blind_spot",
                        "acres": summary["blind_acres"],
                        "description": "Ground no camera can see — the sensor placement proposal",
                    },
                },
                *[
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [
                            _circle(p.lat, p.lon, p.radius_m)
                        ]},
                        "properties": {
                            "layer": "proposed_sensor",
                            "index": p.index,
                            "lat": p.lat,
                            "lon": p.lon,
                            "covers_acres": p.covers_acres,
                            "distance_to_river_m": p.distance_to_river_m,
                            "unit_cost_usd": unit_cost,
                        },
                    }
                    for p in proposals
                ],
            ],
        }

        report = {
            "summary": summary,
            "geojson": geojson,
            "proposals": as_dicts(proposals),
            "csv": proposals_csv(proposals, unit_cost),
            "accuracy_note": (
                "Bare-earth viewshed from a public DEM. Canopy, buildings, camera optics "
                "and real resolution limits are NOT modelled, and headings/fields of view "
                "come from config rather than a survey. Treat coverage as an estimate."
                + (" DEM is SYNTHETIC (no network) — numbers are illustrative only."
                   if summary.get("dem_is_synthetic") else "")
            ),
        }
        _CACHE["report"] = report
        return report


def cached_summary(config) -> dict[str, Any]:
    report = _CACHE.get("report")
    return report["summary"] if report else build(config)["summary"]


def invalidate() -> None:
    with _LOCK:
        _CACHE.pop("report", None)
