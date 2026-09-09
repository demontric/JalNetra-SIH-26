"""Weather and marine hazard specialist."""

from app.agents.state import AgentState
from app.agents.weather_safety import check_hazard_thresholds, fetch_weather


async def weather_safety_agent(state: AgentState) -> AgentState:
    location = state.get("location") or {}
    lat, lon = location.get("latitude"), location.get("longitude")
    if lat is None or lon is None:
        return {"weather_result": {"available": False, "error": "No resolved location available"}}
    source = await fetch_weather(lat, lon)
    if not source.get("available", True):
        return {"weather_result": {"available": False, "error": source.get("error", "Weather is unavailable."), "stale": source.get("stale", False)}}
    hourly = source.get("marine", {}).get("hourly", {})
    forecast = source.get("forecast", {}).get("hourly", {})
    values = {
        "wave_height_m": (hourly.get("wave_height") or [0])[0],
        "wind_speed_kmph": (forecast.get("wind_speed_10m") or [0])[0],
        "lightning_probability_pct": (forecast.get("precipitation_probability") or [0])[0],
    }
    hazards = check_hazard_thresholds(values)
    return {"weather_result": {"available": True, **hazards, "stale": source.get("stale", False), "source": source.get("source", "Open-Meteo")}}
