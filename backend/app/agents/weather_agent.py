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

    # Today = index 0, tomorrow = index 24 (next day noon = ~36 for mid-day tomorrow)
    wave_series = hourly.get("wave_height") or [0]
    wind_series = forecast.get("wind_speed_10m") or [0]
    lightning_series = forecast.get("precipitation_probability") or [0]

    today_values = {
        "wave_height_m": wave_series[0],
        "wind_speed_kmph": wind_series[0],
        "lightning_probability_pct": lightning_series[0],
    }

    # Tomorrow: use index 24 if available, else last available
    tomorrow_idx = min(24, len(wave_series) - 1)
    tomorrow_values = {
        "wave_height_m": wave_series[tomorrow_idx] if len(wave_series) > tomorrow_idx else wave_series[-1],
        "wind_speed_kmph": wind_series[tomorrow_idx] if len(wind_series) > tomorrow_idx else wind_series[-1],
        "lightning_probability_pct": lightning_series[tomorrow_idx] if len(lightning_series) > tomorrow_idx else lightning_series[-1],
    }

    hazards = check_hazard_thresholds(today_values)
    tomorrow_hazards = check_hazard_thresholds(tomorrow_values)

    return {
        "weather_result": {
            "available": True,
            **hazards,
            "tomorrow": {**tomorrow_hazards},
            "stale": source.get("stale", False),
            "source": source.get("source", "Open-Meteo"),
        }
    }
