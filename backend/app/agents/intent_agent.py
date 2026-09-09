"""Intent, language, and location extraction."""

import re
from datetime import date, timedelta
from typing import Any

from app.language import detect_language, translate_to_english
from app.agents.state import AgentState


def _intent(query: str) -> str:
    query = query.lower()
    if any(word in query for word in ("route", "navigate", "waypoint")):
        return "Route"
    if any(word in query for word in ("boundary", "restricted", "regulation", "geofence")):
        return "Regulation"
    if any(word in query for word in ("fish", "pfz", "catch", "chlorophyll", "sst", "low catch", "where", "go to fish", "catching fish", "fishing")):
        return "PFZ"
    if any(word in query for word in ("weather", "wind", "wave", "cyclone", "storm", "safe", "sail", "go out", "tomorrow")):
        return "Weather"
    return "PFZ" if "fish" in query or "where" in query else "General"


def _entities(query: str, location: dict | None, allow_bare_coordinates: bool = False) -> dict:
    entities: dict[str, Any] = {}
    match = re.search(r"\b(?:near|at|to|towards|destination)\b[^\d-]{0,24}(-?\d+(?:\.\d+)?)\s*[,/]\s*(-?\d+(?:\.\d+)?)", query, re.I)
    if not match and allow_bare_coordinates:
        match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*[,/]\s*(-?\d+(?:\.\d+)?)\s*", query)
    if match:
        latitude, longitude = float(match.group(1)), float(match.group(2))
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            entities["coordinates"] = [latitude, longitude]
    if "tomorrow" in query.lower():
        entities["date"] = str(date.today() + timedelta(days=1))
    return entities


def intent_translation_agent(state: AgentState) -> AgentState:
    original = state.get("original_query") or state.get("query", "")
    language = state.get("requested_language", "en-IN")
    detected = detect_language(original, state.get("input_language"))
    translated = translate_to_english(original, detected)
    intent = _intent(translated)
    bare_coordinates = bool(re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*[,/]\s*-?\d+(?:\.\d+)?\s*", translated))
    previous_user_query = next((item.get("text", "") for item in reversed(state.get("chat_history", [])) if item.get("role") == "user"), "")
    if bare_coordinates and _intent(previous_user_query) == "Route":
        intent = "Route"
    latest_query = translate_to_english(original.rsplit("\n", 1)[-1], detected)
    agents: list[str] = {"PFZ": ["ocean"], "Weather": ["weather"], "Regulation": ["geofence"], "Route": ["weather", "geofence", "route"], "General": []}[intent]
    sub_tasks: list[dict] = [{"intent": intent, "agents": agents}]
    return {
        "original_query": original,
        "translated_query": translated,
        "requested_language": language,
        "detected_language": detected,
        "intent": intent,
        "entities": _entities(latest_query, state.get("location"), intent == "Route"),
        "sub_tasks": sub_tasks,
    }
