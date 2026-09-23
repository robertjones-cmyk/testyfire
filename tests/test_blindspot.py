"""Viewshed, placement and the summary arithmetic."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import math  # noqa: E402

import numpy as np  # noqa: E402

from app.geo.dem import TILE_PX, DemGrid, lonlat_to_tile, synthetic_grid  # noqa: E402
from app.geo.geom import m2_to_acres, polygon_area_m2, view_cone  # noqa: E402
from app.geo.placement import priority_score, propose, proposals_csv  # noqa: E402
from app.geo.viewshed import (  # noqa: E402
    Cell,
    CameraGeometry,
    build_grid,
    in_view_direction,
    line_of_sight,
)

SQUARE = [[-106.70, 35.08], [-106.66, 35.08], [-106.66, 35.11], [-106.70, 35.11], [-106.70, 35.08]]


def _flat_dem() -> DemGrid:
    grid = synthetic_grid(0, 0, 1, 1, 12)
    grid.elevation[:] = 1500.0      # perfectly flat
    return grid


def _dem_covering(points, zoom: int = 12, elevation_m: float = 1500.0) -> DemGrid:
    """A flat DEM whose raster actually covers ``points`` [(lat, lon), ...].

    Building it at the right tile origin matters: `DemGrid.sample` clamps to the
    raster, so a grid that does not cover the coordinates silently reports one
    corner pixel everywhere and every line of sight looks clear.
    """
    tiles = [lonlat_to_tile(lon, lat, zoom) for lat, lon in points]
    x0 = math.floor(min(t[0] for t in tiles))
    y0 = math.floor(min(t[1] for t in tiles))
    cols = math.floor(max(t[0] for t in tiles)) - x0 + 1
    rows = math.floor(max(t[1] for t in tiles)) - y0 + 1
    elevation = np.full((rows * TILE_PX, cols * TILE_PX), elevation_m, dtype=np.float32)
    return DemGrid(elevation, float(x0), float(y0), zoom, "synthetic")


def _row_for(dem: DemGrid, lat: float, lon: float) -> int:
    _, ty = lonlat_to_tile(lon, lat, dem.zoom)
    return int((ty - dem.y0) * TILE_PX)


def test_grid_covers_the_polygon():
    cells = build_grid(SQUARE, 200)
    assert len(cells) > 50
    assert all(-106.70 <= c.lon <= -106.66 for c in cells)
    assert all(35.08 <= c.lat <= 35.11 for c in cells)


def test_finer_spacing_makes_more_cells():
    assert len(build_grid(SQUARE, 100)) > len(build_grid(SQUARE, 300))


def test_view_direction_respects_the_cone():
    camera = CameraGeometry("k", "cam", 35.10, -106.68, 180.0, 60.0, 10.0, 1500.0)
    assert in_view_direction(camera, 35.09, -106.68) is True       # due south
    assert in_view_direction(camera, 35.11, -106.68) is False      # due north


def test_unknown_heading_sees_every_direction():
    camera = CameraGeometry("k", "cam", 35.10, -106.68, None, None, 10.0, 1500.0)
    assert in_view_direction(camera, 35.11, -106.68) is True
    assert in_view_direction(camera, 35.09, -106.69) is True


def test_flat_terrain_is_visible_within_range():
    camera = CameraGeometry("k", "cam", 35.10, -106.68, None, None, 10.0, 1500.0)
    assert line_of_sight(_flat_dem(), camera, 35.105, -106.68) is True


def test_beyond_range_is_not_visible():
    camera = CameraGeometry("k", "cam", 35.10, -106.68, None, None, 10.0, 500.0)
    assert line_of_sight(_flat_dem(), camera, 35.13, -106.68) is False


def test_a_ridge_blocks_the_view():
    """A wall of terrain between camera and target hides it."""
    camera_at, target_at = (35.30, -106.68), (34.90, -106.68)
    dem = _dem_covering([camera_at, target_at])

    # Put a 400 m ridge squarely between the two, halfway along.
    midpoint = ((camera_at[0] + target_at[0]) / 2, -106.68)
    ridge_row = _row_for(dem, *midpoint)
    dem.elevation[ridge_row - 8:ridge_row + 8, :] = 1900.0

    camera = CameraGeometry("k", "cam", *camera_at, None, None, 10.0, 60000.0)
    assert line_of_sight(dem, camera, *target_at, step_m=200) is False


def test_a_taller_mast_sees_further_over_a_ridge():
    """Mast height is what buys coverage — the reason mast_height is configurable.

    Scale matters here. Over tens of kilometres Earth curvature (38 m at 22 km)
    dominates any small rise, so the comparison is done at a realistic ~3 km
    with a 15 m bank between camera and target.
    """
    camera_at, target_at = (35.100, -106.68), (35.073, -106.68)   # ~3 km apart
    dem = _dem_covering([camera_at, target_at])

    midpoint = ((camera_at[0] + target_at[0]) / 2, -106.68)
    ridge_row = _row_for(dem, *midpoint)
    dem.elevation[ridge_row - 4:ridge_row + 4, :] = 1515.0        # a 15 m bank

    on_a_pole = CameraGeometry("k", "pole", *camera_at, None, None, 3.0, 5000.0)
    on_a_tower = CameraGeometry("k", "tower", *camera_at, None, None, 60.0, 5000.0)
    assert line_of_sight(dem, on_a_pole, *target_at, step_m=50) is False
    assert line_of_sight(dem, on_a_tower, *target_at, step_m=50) is True


# --- placement -------------------------------------------------------------
def test_placement_covers_every_blind_cell_when_uncapped(config):
    config.raw["blind_spot"]["max_proposed_sensors"] = 1000
    cells = build_grid(SQUARE, 100)[:60]
    proposals = propose(cells, config, cell_area_m2=100 * 100)

    assert proposals, "blind cells must produce proposals"
    covered = sum(p.covers_cells for p in proposals)
    assert covered == len(cells), "greedy cover must account for every blind cell exactly once"


def test_placement_respects_the_cap(config):
    config.raw["blind_spot"]["max_proposed_sensors"] = 3
    cells = build_grid(SQUARE, 100)[:60]
    assert len(propose(cells, config, cell_area_m2=10_000)) == 3


def test_no_blind_cells_means_no_sensors(config):
    assert propose([], config, cell_area_m2=10_000) == []


def test_priority_prefers_the_river(config):
    river = config.get("blind_spot.river_centerline")
    roads = config.get("blind_spot.roads")
    near_river, near_distance, _ = priority_score(35.10, -106.6770, river, roads)
    far_river, far_distance, _ = priority_score(35.10, -106.6000, river, roads)
    assert near_distance < far_distance
    assert near_river > far_river


def test_csv_has_a_header_and_one_row_per_sensor(config):
    cells = build_grid(SQUARE, 150)[:20]
    proposals = propose(cells, config, cell_area_m2=22_500)
    csv_text = proposals_csv(proposals, unit_cost=299.0)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("index,lat,lon")
    assert len(lines) == len(proposals) + 1
    assert all(",299.0" in line for line in lines[1:])


# --- end to end ------------------------------------------------------------
def test_report_arithmetic_is_internally_consistent(database, config, monkeypatch):
    """The headline must never claim more coverage than the proposals deliver."""
    from app.geo import blindspot
    from app.geo import dem as dem_module

    # Small area + synthetic DEM: no network, fast.
    monkeypatch.setattr(
        dem_module.DemSource, "grid_for_bounds",
        lambda self, *a, **k: synthetic_grid(0, 0, 1, 1, 12),
    )
    config.raw["blind_spot"]["area_of_interest"]["polygon"] = SQUARE
    config.raw["blind_spot"]["grid_spacing_m"] = 250
    config.raw["blind_spot"]["max_proposed_sensors"] = 20

    database.execute(
        "INSERT INTO cameras (key, feed_id, camera_id, name, lat, lon, heading, fov,"
        " mast_height, is_ptz, source, first_seen, last_seen)"
        " VALUES ('f__c','f','c','Cam',35.095,-106.68,0,60,12,0,'test','2026-01-01','2026-01-01')"
    )
    blindspot.invalidate()
    report = blindspot.build(config, refresh=True)
    summary = report["summary"]

    assert summary["seen_cells"] + summary["blind_cells"] == summary["total_cells"]
    assert 0 <= summary["coverage_percent"] <= 100
    assert summary["proposed_coverage_acres"] <= summary["blind_acres"] + 0.5
    assert summary["hardware_cost_usd"] == summary["proposed_sensors"] * 299
    if summary["placement_capped"]:
        assert "remain uncovered" in summary["headline"]
    assert summary["dem_is_synthetic"] is True
    assert "SYNTHETIC" in report["accuracy_note"]

    layers = {f["properties"]["layer"] for f in report["geojson"]["features"]}
    assert {"area_of_interest", "camera_coverage", "blind_spot"} <= layers
