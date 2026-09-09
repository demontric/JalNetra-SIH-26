"""Turn specialist outputs into a plain, traceable response."""

from app.agents.state import AgentState
from app.language import translate_answer


def synthesizing_agent(state: AgentState) -> AgentState:
    intent = state.get("intent", "Weather")
    logs = [
        {"level": "info", "stage": "input", "message": f"Received {state.get('detected_language', 'en-IN')} input."},
        {"level": "info", "stage": "translation", "message": f"English context: {state.get('translated_query') or state.get('query', '')}"},
        {"level": "info", "stage": "intent", "message": f"Selected {intent} specialist."},
    ]
    evidence, nodes = [], [{"id": "input", "label": state.get("query", ""), "type": "input"}, {"id": "intent", "label": intent, "type": "agent"}]
    geojson = None
    ocean = state.get("ocean_result")
    if ocean:
        if ocean.get("available"):
            candidate = ocean["candidates"][0]
            confidence_pct = round(candidate['confidence_score'] * 100)
            sst_val = f"{candidate['sst_celsius']:.2f}"
            chlo_val = f"{candidate['chlorophyll_mg_m3']:.3f}"
            evidence.append(f"The potential fishing zone model confidence is {confidence_pct} percent.")
            evidence.append(f"The sea surface temperature is {sst_val} degrees Celsius.")
            evidence.append(f"The chlorophyll concentration is {chlo_val} milligrams per cubic meter.")
            logs.append({"level": "success", "stage": "pfz", "message": "Live sea surface temperature and chlorophyll values passed the potential fishing zone scoring contract."})
            geojson = ocean.get("geojson")
        else:
            evidence.append(ocean["error"])
            for error in ocean.get("errors", []):
                logs.append({"level": "error", "stage": "ocean", "message": error})
            for warning in ocean.get("warnings", []):
                logs.append({"level": "warning", "stage": "ocean", "message": warning})
            logs.append({"level": "warning", "stage": "pfz", "message": ocean["error"]})
    weather = state.get("weather_result")
    if weather:
        if weather.get("available"):
            raw_values = weather.get("raw_values", {})
            evidence.append(f"The wave height is {float(raw_values.get('wave_height_m', 0)):.1f} meters.")
            evidence.append(f"The wind speed is {float(raw_values.get('wind_speed_kmph', 0)):.1f} kilometers per hour.")
            evidence.append(f"The lightning probability is {float(raw_values.get('lightning_probability_pct', 0)):.0f} percent.")
            evidence.extend(weather.get("reasons", []))
            evidence.append("Current marine conditions are within safe thresholds." if weather.get("safe") else "Current marine conditions exceed safe thresholds.")
            logs.append({"level": "success", "stage": "open-meteo", "message": "Retrieved current marine weather and forecast data."})
        else:
            evidence.append(weather["error"])
            logs.append({"level": "warning", "stage": "weather", "message": weather["error"]})
    route = state.get("route_result")
    if route and route.get("available"):
        evidence.append(
            f"A safe route to the destination is {route['distance_km']} kilometers, "
            f"about {route['estimated_time_mins']} minutes away."
        )
        evidence.append(route["hazard_notes"][0])
        logs.append({"level": "success", "stage": "route", "message": "Computed a hazard-aware safe route."})
        route_feature = {
            **route["path_geojson"],
            "properties": {**route["path_geojson"].get("properties", {}), "zone_type": "safe_route", "name": "Planned route"},
        }
        geojson = geojson or {"type": "FeatureCollection", "features": [route_feature]}
    for name, result in (("geofence", state.get("geofence_result")), ("route", route)):
        if result and not result.get("available", True):
            if name != "geofence" or intent == "Regulation":
                evidence.append(result["error"])
            logs.append({"level": "warning", "stage": name, "message": result["error"]})
    english = " ".join(item.rstrip(".") + "." for item in evidence) if evidence else "No marine evidence was available for this request."
    candidate = ocean.get("candidates", [{}])[0] if ocean else {}
    raw_weather = (weather or {}).get("raw_values", {})
    restrictions = (state.get("geofence_result") or {}).get("active_restrictions", [])
    restriction = ", ".join(item.get("name", str(item)) for item in restrictions) or "no active restriction"
    route_hazards = "; ".join((route or {}).get("hazard_notes", [])) or "; ".join((weather or {}).get("reasons", [])) or "known hazards"
    available = bool((ocean or {}).get("available") or (weather or {}).get("available") or (route or {}).get("available"))
    answer = translate_answer(intent, state.get("requested_language", "en-IN"), {
        "english": english,
        "available": available,
        "location": "the selected map location",
        "confidence": f"{candidate.get('confidence_score', 0):.0%}",
        "wave": f"{float(raw_weather.get('wave_height_m', 0)):.1f}",
        "threshold": "2.5",
        "zone": (state.get("geofence_result") or {}).get("zone", "the selected map location"),
        "restriction": restriction,
        "hazards": route_hazards,
        "requested_language": state.get("requested_language", "en-IN"),
    })
    logs.append({"level": "success", "stage": "response", "message": f"Prepared simple {state.get('requested_language', 'en-IN')} response."})
    nodes.append({"id": "response", "label": "Evidence-based response", "type": "agent"})
    return {"response": answer, "execution_log": logs, "geojson": geojson, "visual_trace": {"nodes": nodes, "edges": [{"source": "input", "target": "intent", "label": "classified"}, {"source": "intent", "target": "response", "label": "answered"}]}}
