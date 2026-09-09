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
            confidence_pct = round(candidate["confidence_score"] * 100)
            evidence.append(f"PFZ confidence: {confidence_pct}%")
            evidence.append(f"Sea surface temperature: {candidate['sst_celsius']:.1f}°C")
            evidence.append(f"Chlorophyll: {candidate['chlorophyll_mg_m3']:.3f} mg/m³")
            logs.append({"level": "success", "stage": "pfz", "message": "Live SST and chlorophyll values retrieved."})
            geojson = ocean.get("geojson")
        else:
            evidence.append(f"Ocean data unavailable: {ocean['error']}")
            for error in ocean.get("errors", []):
                logs.append({"level": "error", "stage": "ocean", "message": error})
            for warning in ocean.get("warnings", []):
                logs.append({"level": "warning", "stage": "ocean", "message": warning})

    weather = state.get("weather_result")
    tomorrow_section = ""
    if weather:
        if weather.get("available"):
            raw = weather.get("raw_values", {})
            wave = float(raw.get("wave_height_m", 0))
            wind = float(raw.get("wind_speed_kmph", 0))
            lightning = float(raw.get("lightning_probability_pct", 0))
            safe = weather.get("safe", True)
            reasons = weather.get("reasons", [])

            evidence.append(f"Today — Wave height: {wave:.1f} m (limit 2.5 m), Wind: {wind:.0f} km/h (limit 45), Lightning chance: {lightning:.0f}% (limit 60%)")
            evidence.append(f"Today's overall safety: {'SAFE to go out' if safe else 'UNSAFE — ' + '; '.join(reasons)}")

            # Tomorrow's data
            tmrw = weather.get("tomorrow", {})
            if tmrw.get("raw_values"):
                tr = tmrw["raw_values"]
                tw = float(tr.get("wave_height_m", 0))
                twi = float(tr.get("wind_speed_kmph", 0))
                tl = float(tr.get("lightning_probability_pct", 0))
                ts = tmrw.get("safe", True)
                tr_reasons = tmrw.get("reasons", [])
                tomorrow_section = (
                    f"Tomorrow — Wave height: {tw:.1f} m, Wind: {twi:.0f} km/h, Lightning: {tl:.0f}%. "
                    f"Safety: {'SAFE' if ts else 'UNSAFE — ' + '; '.join(tr_reasons)}"
                )
                evidence.append(tomorrow_section)

            logs.append({"level": "success", "stage": "open-meteo", "message": "Retrieved marine weather for today and tomorrow."})
        else:
            evidence.append(f"Weather unavailable: {weather['error']}")
            logs.append({"level": "warning", "stage": "weather", "message": weather["error"]})

    route = state.get("route_result")
    if route and route.get("available"):
        evidence.append(f"Safe route: {route['distance_km']} km, ~{route['estimated_time_mins']} min. {route['hazard_notes'][0]}")
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

    available = bool(
        (ocean or {}).get("available") or
        (weather or {}).get("available") or
        (route or {}).get("available")
    )

    # Build conversation history context for Gemini (without polluting intent detection)
    chat_history = state.get("chat_history", [])
    history_block = ""
    if chat_history:
        turns = []
        for msg in chat_history[-6:]:  # last 3 exchanges
            role = "User" if msg.get("role") == "user" else "JalNetra"
            turns.append(f"{role}: {msg.get('text', '')}")
        if turns:
            history_block = "Previous conversation:\n" + "\n".join(turns) + "\n\n"

    # The original user question (translated to English for Gemini)
    user_query = state.get("translated_query") or state.get("original_query") or state.get("query", "")


    # Build a rich, structured prompt so Gemini gives a specific, useful answer
    data_block = "\n".join(f"- {e}" for e in evidence) if evidence else "- No live marine data available right now."

    gemini_prompt = (
        f"{history_block}"
        f"User's current question: \"{user_query}\"\n\n"
        f"Intent category detected: {intent}\n\n"
        f"Live marine data collected for this query:\n{data_block}\n\n"
        "Instructions:\n"
        "1. Directly answer the user's SPECIFIC question — not a generic weather summary.\n"
        "2. If they ask about TODAY, use today's data. If they ask about TOMORROW, use tomorrow's data.\n"
        "3. Give a clear YES or NO when asked about safety (e.g. 'can I go out'), then explain briefly.\n"
        "4. If the question is completely unrelated to marine/fishing (e.g. greetings, random text), "
        "respond naturally but briefly redirect to marine assistance.\n"
        "5. Keep response to 1-3 sentences. No bullet points. No asterisks. No generic summaries.\n"
        "6. Respond in English; the caller translates the completed answer for the user."
    )

    forced_answer = route["error"] if intent == "Route" and route and not route.get("available") else None
    if intent == "Weather" and weather and weather.get("available"):
        period = "tomorrow" if "tomorrow" in user_query.lower() else "today"
        conditions = weather.get("tomorrow", {}) if period == "tomorrow" else weather
        values = conditions.get("raw_values", {})
        wave = float(values.get("wave_height_m", 0))
        wind = float(values.get("wind_speed_kmph", 0))
        lightning = float(values.get("lightning_probability_pct", 0))
        if conditions.get("safe", True):
            forced_answer = f"Yes, it is safe to go out {period}. Waves are {wave:.1f} m, wind is {wind:.0f} km/h, and lightning chance is {lightning:.0f}%."
        else:
            forced_answer = f"No, do not go out {period}. " + " ".join(conditions.get("reasons", []))
    try:
        from app.services.gemini_service import answer_query as gemini_answer
        english = forced_answer or gemini_answer(gemini_prompt)
    except Exception:
        # Dynamic fallback response when Gemini is unavailable
        if not evidence:
            english = "I couldn't fetch any live marine data for your request right now. Please check your connection and try again."
        elif intent == "Weather":
            if weather and weather.get("available"):
                raw = weather.get("raw_values", {})
                w = float(raw.get("wave_height_m", 0))
                wi = float(raw.get("wind_speed_kmph", 0))
                li = float(raw.get("lightning_probability_pct", 0))
                s = weather.get("safe", True)
                
                if "cyclone" in user_query.lower() or "storm" in user_query.lower():
                    english = "Based on current data, there are no immediate cyclone or storm alerts active. " if s else "WARNING: Conditions are unsafe, which may indicate cyclonic or storm activity. "
                    english += f"Winds are at {wi:.0f} km/h and waves are {w:.1f}m. Please monitor official INCOIS cyclone bulletins."
                else:
                    english = f"Yes, it is safe to head out today." if s else f"No, it is currently UNSAFE to sail."
                    english += f" Today's waves are at {w:.1f}m with {wi:.0f} km/h winds and a {li:.0f}% chance of lightning."
                    
                    if tomorrow_section:
                        english += f" For tomorrow, the forecast shows {tomorrow_section.replace('Tomorrow — ', '').lower()}"
            else:
                english = " ".join(evidence)
        elif intent == "PFZ":
            if "why" in user_query.lower() or "what" in user_query.lower() or "how" in user_query.lower():
                # General knowledge question
                english = "I am currently running in offline mode and can only provide live marine data. "
                if ocean and ocean.get("available"):
                    c = ocean["candidates"][0]
                    english += f"However, the current potential fishing zone has {round(c['confidence_score']*100)}% confidence, with SST at {c['sst_celsius']:.1f}°C."
            elif ocean and ocean.get("available"):
                c = ocean["candidates"][0]
                conf = round(c["confidence_score"] * 100)
                english = f"I found a potential fishing zone with {conf}% confidence in this area. The sea surface temperature is {c['sst_celsius']:.1f}°C and chlorophyll levels are {c['chlorophyll_mg_m3']:.3f} mg/m³."
            else:
                english = " ".join(evidence)
        elif intent == "Regulation":
            english = "I don't have access to live regulatory boundary data right now, so I can't check for specific geofence warnings. Please verify with local port authorities before sailing near restricted zones."
        elif intent == "Route" and route and route.get("available"):
            english = f"I can plan a safe route for you. It's about {route['distance_km']} km away and will take {route['estimated_time_mins']} minutes. {route['hazard_notes'][0]}"
        else:
            english = " ".join(evidence)

    candidate = ocean.get("candidates", [{}])[0] if ocean else {}
    raw_weather = (weather or {}).get("raw_values", {})
    restrictions = (state.get("geofence_result") or {}).get("active_restrictions", [])
    restriction = ", ".join(item.get("name", str(item)) for item in restrictions) or "no active restriction"
    route_hazards = "; ".join((route or {}).get("hazard_notes", [])) or "; ".join((weather or {}).get("reasons", [])) or "known hazards"
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
    logs.append({"level": "success", "stage": "response", "message": f"Prepared {state.get('requested_language', 'en-IN')} response."})
    nodes.append({"id": "response", "label": "Evidence-based response", "type": "agent"})
    return {
        "response": answer,
        "execution_log": logs,
        "geojson": geojson,
        "visual_trace": {
            "nodes": nodes,
            "edges": [
                {"source": "input", "target": "intent", "label": "classified"},
                {"source": "intent", "target": "response", "label": "answered"},
            ],
        },
    }
