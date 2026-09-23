"""Greedy sensor placement over the blind area.

Each Torch sensor covers about 10 acres (~113 m radius). We repeatedly place a
sensor at the blind cell that covers the most still-uncovered blind cells,
breaking ties by priority: closest to the river first, then closest to a road
(access matters for installation and service).

Greedy set-cover is within a ln(n) factor of optimal and is the right tool at
this scale — the answer only has to be good enough to size a proposal.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any, Sequence

import math

from .geom import EARTH_RADIUS_M, distance_to_polyline_m, haversine_m, m2_to_acres
from .viewshed import Cell


@dataclass(slots=True)
class Proposal:
    index: int
    lat: float
    lon: float
    covers_cells: int
    covers_acres: float
    distance_to_river_m: float
    distance_to_road_m: float
    radius_m: float


def priority_score(
    lat: float,
    lon: float,
    river: Sequence[Sequence[float]],
    roads: Sequence[Sequence[Sequence[float]]],
) -> tuple[float, float, float]:
    """``(score, river_distance_m, road_distance_m)`` — higher score is better."""
    river_distance = distance_to_polyline_m(lat, lon, river) if river else float("inf")
    road_distance = min(
        (distance_to_polyline_m(lat, lon, road) for road in roads),
        default=float("inf"),
    )
    # Normalised so both terms sit in 0..1; the river weighs double.
    river_term = 1.0 / (1.0 + (river_distance / 500.0)) if river_distance < float("inf") else 0.0
    road_term = 1.0 / (1.0 + (road_distance / 1000.0)) if road_distance < float("inf") else 0.0
    return 2.0 * river_term + road_term, river_distance, road_distance


def _bucket_key(lat: float, lon: float, lat_step: float, lon_step: float) -> tuple[int, int]:
    return (int(lat / lat_step), int(lon / lon_step))


def _neighbour_index(
    cells: list[Cell], radius_m: float
) -> dict[int, list[int]]:
    """For each cell, the indices of cells within ``radius_m``.

    Built with a spatial hash so placement stays near-linear: a naive all-pairs
    scan is O(n^2) per pick and does not finish on a corridor-sized grid.
    """
    if not cells:
        return {}
    lat_step = math.degrees(radius_m / EARTH_RADIUS_M)
    mean_lat = sum(c.lat for c in cells) / len(cells)
    lon_step = lat_step / max(math.cos(math.radians(mean_lat)), 1e-6)

    buckets: dict[tuple[int, int], list[int]] = {}
    for index, cell in enumerate(cells):
        buckets.setdefault(_bucket_key(cell.lat, cell.lon, lat_step, lon_step), []).append(index)

    neighbours: dict[int, list[int]] = {}
    for index, cell in enumerate(cells):
        bx, by = _bucket_key(cell.lat, cell.lon, lat_step, lon_step)
        found: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((bx + dx, by + dy), ()):
                    if haversine_m(cell.lat, cell.lon, cells[other].lat, cells[other].lon) <= radius_m:
                        found.append(other)
        neighbours[index] = found
    return neighbours


def propose(
    blind_cells: list[Cell],
    config,
    *,
    cell_area_m2: float,
) -> list[Proposal]:
    """Greedy set cover over the blind cells."""
    radius_m = float(config.get("blind_spot.sensor.radius_m", 113.0))
    max_sensors = int(config.get("blind_spot.max_proposed_sensors", 400))
    river = config.get("blind_spot.river_centerline", []) or []
    roads = config.get("blind_spot.roads", []) or []

    cells = list(blind_cells)
    if not cells:
        return []

    neighbours = _neighbour_index(cells, radius_m)
    priorities = [priority_score(cell.lat, cell.lon, river, roads) for cell in cells]
    covered = [False] * len(cells)
    remaining = [len(neighbours[i]) for i in range(len(cells))]
    uncovered_total = len(cells)

    proposals: list[Proposal] = []
    while uncovered_total > 0 and len(proposals) < max_sensors:
        best_index, best_key = -1, (0, -1.0)
        for index in range(len(cells)):
            if remaining[index] <= 0:
                continue
            key = (remaining[index], priorities[index][0])
            if key > best_key:
                best_key, best_index = key, index
        if best_index < 0:
            break

        newly_covered = [i for i in neighbours[best_index] if not covered[i]]
        for i in newly_covered:
            covered[i] = True
            uncovered_total -= 1
            # Every candidate that could have covered i now covers one fewer.
            for j in neighbours[i]:
                remaining[j] -= 1

        cell = cells[best_index]
        _, river_distance, road_distance = priorities[best_index]
        proposals.append(Proposal(
            index=len(proposals) + 1,
            lat=round(cell.lat, 6),
            lon=round(cell.lon, 6),
            covers_cells=len(newly_covered),
            covers_acres=round(m2_to_acres(len(newly_covered) * cell_area_m2), 2),
            distance_to_river_m=round(river_distance, 1) if river_distance < float("inf") else -1.0,
            distance_to_road_m=round(road_distance, 1) if road_distance < float("inf") else -1.0,
            radius_m=radius_m,
        ))

    return proposals


def proposals_csv(proposals: list[Proposal], unit_cost: float = 299.0) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "index", "lat", "lon", "covers_acres", "covers_cells",
        "distance_to_river_m", "distance_to_road_m", "radius_m", "unit_cost_usd",
    ])
    for proposal in proposals:
        writer.writerow([
            proposal.index, proposal.lat, proposal.lon, proposal.covers_acres,
            proposal.covers_cells, proposal.distance_to_river_m,
            proposal.distance_to_road_m, proposal.radius_m, unit_cost,
        ])
    return buffer.getvalue()


def as_dicts(proposals: list[Proposal]) -> list[dict[str, Any]]:
    return [
        {
            "index": p.index, "lat": p.lat, "lon": p.lon,
            "covers_acres": p.covers_acres, "covers_cells": p.covers_cells,
            "distance_to_river_m": p.distance_to_river_m,
            "distance_to_road_m": p.distance_to_road_m, "radius_m": p.radius_m,
        }
        for p in proposals
    ]
