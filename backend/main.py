"""FastAPI entry point for the JalNetra prototype API."""

import asyncio
from datetime import UTC, datetime
import math

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.language import normalize_language
from app.services.gemini_service import GeminiServiceError, answer_query, translate_from_english, translate_to_english
from services.sarvam_service import SarvamServiceError, speech_to_text, text_to_speech
from app.api.v1.endpoints import routes, trace


app = FastAPI(title="JalNetra API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(routes.router, prefix="/api/v1")
app.include_router(trace.router, prefix="/api/v1")


def _distance_and_bearing(latitude: float, longitude: float, destination_latitude: float, destination_longitude: float) -> tuple[float, int]:
    latitude_radians, destination_latitude_radians = math.radians(latitude), math.radians(destination_latitude)
    delta_latitude = math.radians(destination_latitude - latitude)
    delta_longitude = math.radians(destination_longitude - longitude)
    haversine = math.sin(delta_latitude / 2) ** 2 + math.cos(latitude_radians) * math.cos(destination_latitude_radians) * math.sin(delta_longitude / 2) ** 2
    distance_km = 6371 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))
    bearing = math.degrees(math.atan2(math.sin(delta_longitude) * math.cos(destination_latitude_radians), math.cos(latitude_radians) * math.sin(destination_latitude_radians) - math.sin(latitude_radians) * math.cos(destination_latitude_radians) * math.cos(delta_longitude)))
    return round(distance_km, 1), round((bearing + 360) % 360)


@app.get("/api/v1/trip-decision")
async def get_trip_decision(latitude: float, longitude: float) -> dict:
    """Summarize live weather and PFZ evidence into the dashboard's trip card."""
    from app.agents.ocean_analytics import computed_pfz
    from app.agents.weather_safety import check_hazard_thresholds, fetch_weather

    weather, pfz = await asyncio.gather(fetch_weather(latitude, longitude), computed_pfz(latitude, longitude))
    marine = weather.get("marine", {}).get("hourly", {})
    forecast = weather.get("forecast", {}).get("hourly", {})
    values = {
        "wave_height_m": (marine.get("wave_height") or [0])[0],
        "wind_speed_kmph": (forecast.get("wind_speed_10m") or [0])[0],
        "lightning_probability_pct": (forecast.get("precipitation_probability") or [0])[0],
    }
    hazards = check_hazard_thresholds(values) if weather.get("available", True) else {"safe": False, "reasons": ["Live weather is unavailable."], "raw_values": values}
    best_zone = max(pfz.get("features", []), key=lambda feature: feature["properties"].get("confidence_score", 0), default=None)
    best_fishing_direction = None
    if best_zone:
        points = best_zone["geometry"]["coordinates"][0][:-1]
        destination_longitude = sum(point[0] for point in points) / len(points)
        destination_latitude = sum(point[1] for point in points) / len(points)
        distance_km, bearing_deg = _distance_and_bearing(latitude, longitude, destination_latitude, destination_longitude)
        best_fishing_direction = {
            "distance_km": distance_km,
            "bearing_deg": bearing_deg,
            "confidence": best_zone["properties"].get("confidence_score", 0),
            "latitude": destination_latitude,
            "longitude": destination_longitude,
        }
    status = "Safe to sail" if hazards["safe"] else "Do not sail"
    if not weather.get("available", True):
        status = "Caution"
    raw = hazards["raw_values"]
    return {
        "status": status,
        "reasons": hazards["reasons"],
        "drivers": [
            {"label": "Waves", "value": f"{raw['wave_height_m']:.1f} m", "safe": raw["wave_height_m"] <= 2.5},
            {"label": "Wind", "value": f"{raw['wind_speed_kmph']:.0f} km/h", "safe": raw["wind_speed_kmph"] <= 45},
            {"label": "Lightning", "value": f"{raw['lightning_probability_pct']:.0f}%", "safe": raw["lightning_probability_pct"] <= 60},
            {"label": "Boundary", "value": "No active advisory", "safe": True},
            {"label": "PFZ", "value": f"{best_fishing_direction['confidence']:.0%} confidence" if best_fishing_direction else "No current zone", "safe": bool(best_fishing_direction)},
        ],
        "best_fishing_direction": best_fishing_direction,
        "fresh_at": datetime.now(UTC).isoformat(),
        "sources": [source for source in (weather.get("source"), pfz.get("source")) if source and source != "None"],
    }


class QueryRequest(BaseModel):
    """Natural-language query submitted to the prototype assistant."""

    query: str
    language: str = "en-IN"
    user_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_to_coast_km: float | None = None


class SpeechRequest(BaseModel):
    text: str
    language: str = "en-IN"


@app.get("/api/v1/pfz")
async def get_pfz(latitude: float | None = None, longitude: float | None = None, distance_to_coast_km: float | None = None) -> dict:
    """Return a computed PFZ GeoJSON layer around the resolved location."""
    if latitude is None or longitude is None:
        return {"type": "FeatureCollection", "features": [], "stale": False, "error": "A resolved location is required."}
    from app.agents.ocean_analytics import computed_pfz
    return await computed_pfz(latitude, longitude)


@app.get("/api/v1/alerts")
def get_alerts() -> list[dict]:
    """Return live alerts when an ingestion service is configured."""
    return []


async def run_query(query: str, language: str = "en-IN", latitude: float | None = None, longitude: float | None = None, distance_to_coast_km: float | None = None) -> dict:
    """Run the canonical specialist graph for a location-aware answer."""
    requested_language = normalize_language(language)
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    from app.graph import graph

    result = await graph.ainvoke({
        "query": query,
        "original_query": query,
        "requested_language": requested_language,
        "location": ({
            "latitude": latitude,
            "longitude": longitude,
            "distance_to_coast_km": distance_to_coast_km,
        } if latitude is not None and longitude is not None else {}),
    })
    return {
        "query": query,
        "original_query": result.get("original_query", query),
        "translated_query": result.get("translated_query", query),
        "language": result.get("requested_language", requested_language),
        "intent": result.get("intent", "Weather"),
        "answer": result.get("response", "No answer could be prepared."),
        "visual_trace": result.get("visual_trace"),
        "geojson": result.get("geojson"),
        "execution_log": result.get("execution_log", []),
    }


@app.post("/api/v1/query")
async def submit_query(request: QueryRequest) -> dict:
    try:
        return await run_query(request.query, request.language, request.latitude, request.longitude, request.distance_to_coast_km)
    except GeminiServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/v1/speech")
def synthesize_speech(request: SpeechRequest) -> dict:
    """Synthesize any displayed answer with Sarvam for replay controls."""
    try:
        audio_base64 = text_to_speech(request.text, normalize_language(request.language))
    except SarvamServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return {"audio_base64": audio_base64, "audio_mime_type": "audio/wav"}


@app.post("/api/v1/voice-query")
async def submit_voice_query(
    audio: UploadFile = File(...),
    language: str = Form("hi-IN"),
) -> dict:
    """Transcribe regional speech, answer in the selected language, and synthesize it."""
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Upload an audio file (WebM, WAV, or MP3).")

    try:
        transcribed_text = speech_to_text(
            audio.file.read(),
            language,
            filename=audio.filename or "recording.webm",
            content_type=audio.content_type,
        )
    except SarvamServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    try:
        query_result = await run_query(transcribed_text, language)
    except GeminiServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    audio_base64 = None
    voice_error = None
    try:
        audio_base64 = text_to_speech(query_result["answer"], language)
    except SarvamServiceError as error:
        # The text response remains useful if a quota/service error affects TTS.
        voice_error = str(error)
        query_result.setdefault("execution_log", []).append({
            "level": "error",
            "stage": "voice",
            "message": voice_error,
        })

    return {
        "transcribed_text": transcribed_text,
        "answer": query_result["answer"],
        "audio_base64": audio_base64,
        "audio_mime_type": "audio/wav" if audio_base64 else None,
        "visual_trace": query_result["visual_trace"],
        "execution_log": query_result.get("execution_log", []),
        "original_query": query_result.get("original_query", transcribed_text),
        "translated_query": query_result.get("translated_query", transcribed_text),
        "language": language,
        "voice_error": voice_error,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
