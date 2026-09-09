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
    if any(word in query for word in ("weather", "wind", "wave", "cyclone", "storm", "safe")):
        return "Weather"
    return "PFZ" if "fish" in query or "where" in query else "Weather"


def _entities(query: str, location: dict | None) -> dict:
    entities: dict[str, Any] = {}
    match = re.search(r"\b(?:near|at|to|towards|destination)\b[^\d-]{0,24}(-?\d+(?:\.\d+)?)\s*[,/]\s*(-?\d+(?:\.\d+)?)", query, re.I)
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
    detected = detect_language(original, language)
    translated = translate_to_english(original, detected)
    intent = _intent(translated)
    agents: list[str] = {"PFZ": ["ocean"], "Weather": ["weather"], "Regulation": ["geofence"], "Route": ["weather", "geofence", "route"]}[intent]
    sub_tasks: list[dict] = [{"intent": intent, "agents": agents}]
    return {
        "original_query": original,
        "translated_query": translated,
        "requested_language": language,
        "detected_language": detected,
        "intent": intent,
        "entities": _entities(translated, state.get("location")),
        "sub_tasks": sub_tasks,
    }
