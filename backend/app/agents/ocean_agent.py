"""PFZ specialist backed by the globally loaded model and live providers."""

from app.agents.state import AgentState
from app.agents.ocean_analytics import computed_pfz


async def ocean_analytics_agent(state: AgentState) -> AgentState:
    location = state.get("location") or {}
    lat, lon = location.get("latitude"), location.get("longitude")
    if lat is None or lon is None:
        return {"ocean_result": {"available": False, "error": "No resolved location available"}}
    geojson = await computed_pfz(lat, lon)
    candidates = [
        {
            "confidence_score": feature["properties"]["confidence_score"],
            "sst_celsius": feature["properties"]["sst_value"],
            "chlorophyll_mg_m3": feature["properties"]["chlorophyll_value"],
        }
        for feature in geojson.get("features", [])
    ]
    if not candidates:
        return {"ocean_result": {"available": False, "error": "No high-confidence potential fishing zones were found near this coastal location.", "geojson": geojson, "stale": geojson.get("stale", False)}}
    return {"ocean_result": {"available": True, "prediction": {"confidence_score": max(item["confidence_score"] for item in candidates)}, "candidates": candidates, "geojson": geojson, "stale": geojson.get("stale", False)}}
