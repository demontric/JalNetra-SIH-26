"""Open-Meteo weather data and pure marine hazard threshold logic."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.cache import cache_key, fetch_with_cache_and_fallback

OPEN_METEO_MARINE = "https://marine-api.open-meteo.com/v1/marine"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"


async def _open_meteo(latitude: float, longitude: float) -> dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "wave_height,wind_speed_10m,wind_gusts_10m,precipitation_probability,weather_code",
        "forecast_days": 2,
        "timezone": "UTC",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        marine_response, forecast_response = await asyncio.gather(
            client.get(OPEN_METEO_MARINE, params=params),
            client.get(OPEN_METEO_FORECAST, params=params),
        )
        marine_response.raise_for_status()
        forecast_response.raise_for_status()
        return {"marine": marine_response.json(), "forecast": forecast_response.json(), "source": "Open-Meteo"}


async def fetch_weather(latitude: float, longitude: float) -> dict[str, Any]:
    key = cache_key("open-meteo", "weather", latitude, longitude)
    return await fetch_with_cache_and_fallback(lambda: _open_meteo(latitude, longitude), None, key)


def check_hazard_thresholds(values: dict[str, Any]) -> dict[str, Any]:
    wave = float(values.get("wave_height_m", 0) or 0)
    wind = float(values.get("wind_speed_kmph", 0) or 0)
    lightning = float(values.get("lightning_probability_pct", 0) or 0)
    reasons = []
    if wave > 2.5:
        reasons.append(f"Wave height is {wave:.1f} m, above the 2.5 m limit.")
    if wind > 45:
        reasons.append(f"Wind speed is {wind:.1f} km/h, above the 45 km/h limit.")
    if lightning > 60:
        reasons.append(f"Lightning probability is {lightning:.0f}%, above the 60% limit.")
    return {"safe": not reasons, "reasons": reasons, "raw_values": {"wave_height_m": wave, "wind_speed_kmph": wind, "lightning_probability_pct": lightning}}