"""Shared state passed between JalNetra LangGraph nodes."""

from typing import TypedDict


class AgentState(TypedDict, total=False):
    query: str
    original_query: str
    translated_query: str
    requested_language: str
    input_language: str
    detected_language: str
    intent: str
    entities: dict
    location: dict
    sub_tasks: list[dict]
    chat_history: list[dict]
    ocean_result: dict
    weather_result: dict
    geofence_result: dict
    route_result: dict
    report_result: dict
    response: str
    execution_log: list[dict]
    geojson: dict | None
    visual_trace: dict
