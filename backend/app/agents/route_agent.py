"""Route specialist.

Plans a hazard-aware safe route from the caller's resolved location to a
destination extracted from the query (currently explicit "lat, lon" pairs
picked up by the intent agent's entity extraction -- there is no place-name
geocoder in this prototype yet).
"""

from app.agents.state import AgentState
from app.services.route_planner import RoutePlanningError, plan_route


def route_optimization_agent(state: AgentState) -> AgentState:
    location = state.get("location") or {}
    entities = state.get("entities") or {}
    origin_lat = location.get("latitude")
    origin_lon = location.get("longitude")
    destination_coords = entities.get("coordinates")

    if origin_lat is None or origin_lon is None:
        return {"route_result": {"available": False, "error": "Share your current location to plan a route."}}
    if not destination_coords or len(destination_coords) != 2:
        return {
            "route_result": {
                "available": False,
                "error": "Please provide a destination—for example, coordinates such as 9.5, 88.9—so I can plan a safe route.",
            }
        }

    try:
        weather = state.get("weather_result") or {}
        geofence = state.get("geofence_result") or {}
        ocean = state.get("ocean_result") or {}
        route = plan_route(
            {"lat": origin_lat, "lon": origin_lon},
            {"lat": destination_coords[0], "lon": destination_coords[1]},
            state.get("vessel_type", "motorized_boat"),
            float(weather.get("raw_values", {}).get("wave_height_m", 0) or 0),
            [item for item in geofence.get("active_restrictions", []) if isinstance(item, dict) and item.get("polygon")],
            ocean.get("geojson", {}).get("features", []),
        )
    except RoutePlanningError as error:
        return {"route_result": {"available": False, "error": str(error)}}

    return {"route_result": {"available": True, **route}}
