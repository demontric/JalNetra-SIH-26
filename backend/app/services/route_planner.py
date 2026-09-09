"""Safe-route planning for the marine navigation feature.

Given an origin and destination, this module returns a distance/time
estimate and a path that steers around known maritime hazard and
regulatory-exclusion zones (cyclone watches, protected coastal geofences)
instead of always drawing a straight line between the two points.

The math is intentionally dependency-free (no shapely/geopandas) so it
runs with the packages already pinned in requirements.txt:

- Great-circle (haversine) distance/bearing for real-world km and ETA.
- A local equirectangular projection (accurate for the ~tens-of-km trips
  fishing vessels make) so hazard geometry can be handled with simple
  planar vector math.
- Each hazard polygon is approximated by its bounding circle. If the
  straight leg of the trip passes inside a hazard's circle, a single
  detour waypoint is inserted that clears the circle (plus a safety
  margin), and the two resulting legs are what gets returned.
"""

from __future__ import annotations

import heapq
import math
import uuid
from typing import Any

EARTH_RADIUS_KM = 6371.0

# Average cruising speed by vessel type. Used only for the ETA estimate.
VESSEL_SPEEDS_KMH: dict[str, float] = {
    "motorized_boat": 18.0,
    "trawler": 14.0,
    "sailboat": 9.0,
    "canoe": 6.0,
}
DEFAULT_SPEED_KMH = 15.0

# Extra clearance (km) kept beyond a hazard's outer edge when routing around it.
SAFETY_MARGIN_KM = 2.0

# Known hazard / regulatory-exclusion zones. Coordinates mirror the demo
# alert overlays shown on the dashboard map (frontend/src/components/LeafletMapInner.jsx)
# so the "why did my route bend here" story matches what the user sees.
HazardZone = dict[str, Any]
HAZARD_ZONES: list[HazardZone] = [
    {
        "id": "cyclone_watch_bay",
        "name": "Cyclone watch zone",
        "kind": "weather_alert",
        # (lon, lat) pairs, matches ALERT_ZONES.cyclone on the frontend.
        "polygon": [(86.7, 19.1), (88.9, 19.1), (88.9, 21.1), (86.7, 21.1)],
    },
    {
        "id": "protected_coastal_geofence",
        "name": "Protected coastal restriction",
        "kind": "regulatory_geofence",
        # matches ALERT_ZONES.geofence on the frontend.
        "polygon": [(87.8, 19.6), (88.6, 19.6), (88.6, 20.2), (87.8, 20.2)],
    },
]


class RoutePlanningError(ValueError):
    """Raised when the requested origin/destination cannot be routed."""


def _validate(point: dict[str, float], label: str) -> tuple[float, float]:
    try:
        lat = float(point["lat"])
        lon = float(point["lon"])
    except (KeyError, TypeError, ValueError) as error:
        raise RoutePlanningError(f"{label} must include numeric 'lat' and 'lon'.") from error
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise RoutePlanningError(f"{label} coordinates are out of range.")
    return lat, lon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


class _LocalProjection:
    """Flat-earth projection (km) centered on the trip, valid for short hops."""

    def __init__(self, ref_lat: float, ref_lon: float) -> None:
        self.ref_lat = ref_lat
        self.ref_lon = ref_lon
        self.km_per_deg_lat = 111.32
        self.km_per_deg_lon = 111.32 * math.cos(math.radians(ref_lat)) or 1e-6

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.ref_lon) * self.km_per_deg_lon, (lat - self.ref_lat) * self.km_per_deg_lat

    def to_lat_lon(self, x: float, y: float) -> tuple[float, float]:
        return self.ref_lat + y / self.km_per_deg_lat, self.ref_lon + x / self.km_per_deg_lon


def _hazard_circle(zone: HazardZone, projection: _LocalProjection) -> tuple[tuple[float, float], float]:
    """Bounding circle (center_xy, radius_km incl. safety margin) for a hazard polygon."""
    vertices_xy = [projection.to_xy(lat, lon) for lon, lat in zone["polygon"]]
    center_x = sum(x for x, _ in vertices_xy) / len(vertices_xy)
    center_y = sum(y for _, y in vertices_xy) / len(vertices_xy)
    radius = max(math.hypot(x - center_x, y - center_y) for x, y in vertices_xy)
    return (center_x, center_y), radius + SAFETY_MARGIN_KM


def _closest_point_on_segment(
    start: tuple[float, float], end: tuple[float, float], point: tuple[float, float]
) -> tuple[tuple[float, float], float]:
    """Returns (closest_xy, t) where t in [0, 1] is the position along the segment."""
    sx, sy = start
    ex, ey = end
    px, py = point
    dx, dy = ex - sx, ey - sy
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return start, 0.0
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / length_sq))
    return (sx + t * dx, sy + t * dy), t


def _plan_waypoints(
    origin_xy: tuple[float, float], dest_xy: tuple[float, float], projection: _LocalProjection
) -> tuple[list[tuple[float, float]], list[HazardZone]]:
    """Returns extra (x, y) waypoints (ordered along the trip) plus the hazards they avoid."""
    detours: list[tuple[float, tuple[float, float]]] = []  # (t, waypoint_xy)
    avoided: list[HazardZone] = []

    for zone in HAZARD_ZONES:
        center, radius = _hazard_circle(zone, projection)
        closest, t = _closest_point_on_segment(origin_xy, dest_xy, center)
        dist_to_center = math.hypot(closest[0] - center[0], closest[1] - center[1])
        if dist_to_center >= radius:
            continue  # straight leg already clears this hazard

        if dist_to_center < 1e-6:
            # Path runs through the hazard center; push out perpendicular to travel direction.
            dx, dy = dest_xy[0] - origin_xy[0], dest_xy[1] - origin_xy[1]
            length = math.hypot(dx, dy) or 1.0
            direction = (-dy / length, dx / length)
        else:
            direction = ((closest[0] - center[0]) / dist_to_center, (closest[1] - center[1]) / dist_to_center)

        waypoint = (center[0] + direction[0] * radius, center[1] + direction[1] * radius)
        detours.append((t, waypoint))
        avoided.append(zone)

    detours.sort(key=lambda item: item[0])
    return [waypoint for _, waypoint in detours], avoided


def _point_in_polygon(latitude: float, longitude: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[index - 1]
        if (y1 > latitude) != (y2 > latitude) and longitude < (x2 - x1) * (latitude - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _astar_path(
    origin: tuple[float, float], destination: tuple[float, float], wave_height_m: float = 0.0,
    geofences: list[HazardZone] | None = None, pfz_features: list[dict[str, Any]] | None = None,
) -> list[tuple[float, float]]:
    """Find a short navigable grid path, penalizing hazards and favoring PFZ cells."""
    origin_lat, origin_lon = origin
    dest_lat, dest_lon = destination
    span = max(abs(dest_lat - origin_lat), abs(dest_lon - origin_lon), 0.05)
    margin = min(0.5, max(0.08, span * 0.25))
    min_lat, max_lat = min(origin_lat, dest_lat) - margin, max(origin_lat, dest_lat) + margin
    min_lon, max_lon = min(origin_lon, dest_lon) - margin, max(origin_lon, dest_lon) + margin
    size = 25
    step_lat, step_lon = (max_lat - min_lat) / (size - 1), (max_lon - min_lon) / (size - 1)
    start = (round((origin_lat - min_lat) / step_lat), round((origin_lon - min_lon) / step_lon))
    goal = (round((dest_lat - min_lat) / step_lat), round((dest_lon - min_lon) / step_lon))
    def point(node: tuple[int, int]) -> tuple[float, float]:
        return min_lat + node[0] * step_lat, min_lon + node[1] * step_lon
    def cost(node: tuple[int, int], neighbor: tuple[int, int]) -> float:
        lat, lon = point(neighbor)
        base = haversine_km(*point(node), lat, lon) * (1 + max(0.0, wave_height_m - 2.5) * 5)
        if any(_point_in_polygon(lat, lon, zone["polygon"]) for zone in geofences or HAZARD_ZONES):
            return base * 1_000
        for feature in pfz_features or []:
            polygon = feature.get("geometry", {}).get("coordinates", [[]])[0]
            if polygon and _point_in_polygon(lat, lon, [tuple(p) for p in polygon]):
                return base * 0.9
        return base
    frontier = [(0.0, start)]
    scores = {start: 0.0}
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    while frontier:
        _, node = heapq.heappop(frontier)
        if node == goal:
            path = [node]
            while node in previous:
                node = previous[node]
                path.append(node)
            points = [point(item) for item in reversed(path)]
            points[0], points[-1] = origin, destination
            return points
        for row in range(max(0, node[0] - 1), min(size, node[0] + 2)):
            for col in range(max(0, node[1] - 1), min(size, node[1] + 2)):
                neighbor = (row, col)
                if neighbor == node:
                    continue
                tentative = scores[node] + cost(node, neighbor)
                if tentative < scores.get(neighbor, float("inf")):
                    scores[neighbor] = tentative
                    previous[neighbor] = node
                    heuristic = haversine_km(*point(neighbor), dest_lat, dest_lon)
                    heapq.heappush(frontier, (tentative + heuristic, neighbor))
    raise RoutePlanningError("No safe grid route is available.")


def plan_route(
    origin: dict[str, float], destination: dict[str, float], vessel_type: str = "motorized_boat",
    wave_height_m: float = 0.0, geofences: list[HazardZone] | None = None, pfz_features: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    origin_lat, origin_lon = _validate(origin, "origin")
    dest_lat, dest_lon = _validate(destination, "destination")

    speed_kmh = VESSEL_SPEEDS_KMH.get(vessel_type, DEFAULT_SPEED_KMH)
    straight_km = haversine_km(origin_lat, origin_lon, dest_lat, dest_lon)

    hazard_notes: list[str] = []
    lat_lon_path: list[tuple[float, float]] = [(origin_lat, origin_lon)]

    if straight_km < 0.05:
        lat_lon_path.append((dest_lat, dest_lon))
    else:
        lat_lon_path = _astar_path((origin_lat, origin_lon), (dest_lat, dest_lon), wave_height_m, geofences, pfz_features)
        if wave_height_m > 2.5:
            hazard_notes.append(f"High waves ({wave_height_m:.1f} m) were heavily penalized in route selection.")
        if geofences or HAZARD_ZONES:
            hazard_notes.append("Active regulatory and weather hazard cells were heavily penalized.")
        if pfz_features:
            hazard_notes.append("High-confidence potential fishing zones received a small route preference.")

    if not hazard_notes:
        hazard_notes.append("Direct path is clear of known cyclone watches and protected/regulatory zones.")

    total_km = sum(
        haversine_km(lat_lon_path[i][0], lat_lon_path[i][1], lat_lon_path[i + 1][0], lat_lon_path[i + 1][1])
        for i in range(len(lat_lon_path) - 1)
    )
    estimated_minutes = max(1, round(total_km / speed_kmh * 60)) if total_km > 0 else 0
    hazard_notes.append(
        f"Estimated using a {vessel_type.replace('_', ' ')} cruising at {speed_kmh:g} km/h."
    )

    return {
        "route_id": f"route_{uuid.uuid4().hex[:10]}",
        "distance_km": round(total_km, 1),
        "estimated_time_mins": estimated_minutes,
        "hazard_notes": hazard_notes,
        "path_geojson": {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat] for lat, lon in lat_lon_path],
            },
            "properties": {
                "status": "optimized",
                "vessel_type": vessel_type,
                "waypoint_count": len(lat_lon_path),
                "bearing_deg": round(bearing_deg(origin_lat, origin_lon, dest_lat, dest_lon)),
            },
        },
    }
