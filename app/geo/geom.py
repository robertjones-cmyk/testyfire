"""Small geodesy helpers.

Coordinates are (lat, lon) in degrees; GeoJSON positions are ``[lon, lat]``.
Distances are metres. Everything here is plain trigonometry — no GIS
dependency — which is accurate enough over a ~25 km corridor.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

EARTH_RADIUS_M = 6_371_008.8

Position = Sequence[float]          # [lon, lat]
Polygon = Sequence[Position]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination(lat: float, lon: float, bearing: float, distance_m: float) -> tuple[float, float]:
    """Point ``distance_m`` from (lat, lon) along ``bearing``."""
    delta = distance_m / EARTH_RADIUS_M
    theta = math.radians(bearing)
    phi1, lambda1 = math.radians(lat), math.radians(lon)
    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), (math.degrees(lambda2) + 540.0) % 360.0 - 180.0


def angle_difference(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, 0..180."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def view_cone(
    lat: float,
    lon: float,
    heading: float | None,
    fov: float | None,
    range_m: float,
    *,
    steps: int = 24,
) -> list[list[float]]:
    """GeoJSON ring for a camera's approximate view.

    With no heading, the camera gets a full 360° disc — the UI says so
    explicitly rather than pretending to a precision we do not have.
    """
    if heading is None or fov is None or fov >= 359.0:
        ring = [list(reversed(destination(lat, lon, b * 360.0 / steps, range_m))) for b in range(steps)]
        ring.append(ring[0])
        return ring

    half = max(1.0, float(fov)) / 2.0
    ring: list[list[float]] = [[lon, lat]]
    for i in range(steps + 1):
        bearing = float(heading) - half + (2 * half) * i / steps
        plat, plon = destination(lat, lon, bearing, range_m)
        ring.append([plon, plat])
    ring.append([lon, lat])
    return ring


def point_in_polygon(lat: float, lon: float, polygon: Polygon) -> bool:
    """Ray-casting test. ``polygon`` is a ring of ``[lon, lat]`` positions."""
    inside = False
    count = len(polygon)
    if count < 3:
        return False
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def polygon_bounds(polygon: Polygon) -> tuple[float, float, float, float]:
    """``(min_lon, min_lat, max_lon, max_lat)``."""
    lons = [p[0] for p in polygon]
    lats = [p[1] for p in polygon]
    return min(lons), min(lats), max(lons), max(lats)


def distance_to_polyline_m(lat: float, lon: float, line: Iterable[Position]) -> float:
    """Shortest distance from a point to a polyline of ``[lon, lat]`` positions."""
    points = list(line)
    if not points:
        return float("inf")
    if len(points) == 1:
        return haversine_m(lat, lon, points[0][1], points[0][0])

    best = float("inf")
    # Local equirectangular projection — fine at this scale and much cheaper.
    lat0 = math.radians(lat)
    def to_xy(position: Position) -> tuple[float, float]:
        return (
            math.radians(position[0] - lon) * math.cos(lat0) * EARTH_RADIUS_M,
            math.radians(position[1] - lat) * EARTH_RADIUS_M,
        )

    for start, end in zip(points, points[1:]):
        x1, y1 = to_xy(start)
        x2, y2 = to_xy(end)
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-9:
            best = min(best, math.hypot(x1, y1))
            continue
        t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length_sq))
        best = min(best, math.hypot(x1 + t * dx, y1 + t * dy))
    return best


def polygon_area_m2(polygon: Polygon) -> float:
    """Spherical-excess-free planar area via an equirectangular projection."""
    points = list(polygon)
    if len(points) < 3:
        return 0.0
    lat0 = math.radians(sum(p[1] for p in points) / len(points))
    coords = [
        (
            math.radians(p[0]) * math.cos(lat0) * EARTH_RADIUS_M,
            math.radians(p[1]) * EARTH_RADIUS_M,
        )
        for p in points
    ]
    total = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:] + coords[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


M2_PER_ACRE = 4046.8564224


def m2_to_acres(area_m2: float) -> float:
    return area_m2 / M2_PER_ACRE
