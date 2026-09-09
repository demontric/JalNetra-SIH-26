"""Gemini-backed conversational responses for the model-free workflow."""

from __future__ import annotations

import os
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

from app.language import LANGUAGE_NAMES

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


class GeminiServiceError(RuntimeError):
    """Raised when Gemini cannot produce a response."""


_TEXT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def _response_text(payload: dict) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        if payload.get("promptFeedback", {}).get("blockReason"):
            raise GeminiServiceError("Gemini blocked this request due to safety settings.")
        raise GeminiServiceError("Gemini returned no response candidates.")

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    content = "".join(part.get("text", "") for part in parts)
    if not content:
        if candidate.get("finishReason") in {"SAFETY", "RECITATION", "BLOCKLIST"}:
            raise GeminiServiceError("Gemini blocked this response due to safety settings.")
        raise GeminiServiceError("Gemini returned an empty response.")

    try:
        answer = json.loads(content)["text"].strip()
    except (KeyError, TypeError, ValueError) as error:
        raise GeminiServiceError("Gemini returned an invalid structured response.") from error
    if not answer:
        raise GeminiServiceError("Gemini returned an empty response.")
    return answer


def _generate(system_prompt: str, user_prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiServiceError("Gemini is not configured. Set GEMINI_API_KEY.")

    try:
        response = requests.post(
            GEMINI_URL,
            params={"key": api_key},
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": _TEXT_RESPONSE_SCHEMA,
                },
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        status = getattr(error.response, "status_code", None)
        if status in (401, 403):
            raise GeminiServiceError("Gemini rejected the API key. Check GEMINI_API_KEY.") from error
        if status == 429:
            raise GeminiServiceError("Gemini is currently rate limited. Please try again shortly.") from error
        raise GeminiServiceError("Gemini is temporarily unavailable.") from error
    except ValueError as error:
        raise GeminiServiceError("Gemini returned an invalid response.") from error

    return _response_text(payload)


def translate_to_english(text: str, language: str) -> str:
    if language == "en-IN":
        return text.strip()
    return _generate(
        "Translate the user's message to concise natural English. Return only the translation. "
        "Preserve names, coordinates, quantities, and the user's intent.",
        f"Language: {LANGUAGE_NAMES.get(language, language)}\nMessage: {text}",
    )


def translate_from_english(text: str, language: str) -> str:
    if language == "en-IN":
        return text.strip()
    return _generate(
        f"Requested language locale: {language}. Translate the answer into natural {LANGUAGE_NAMES.get(language, language)}. Return only the translation. "
        "Keep marine terms, numbers, coordinates, caveats, and paragraph breaks accurate.",
        text,
    )


def answer_query(query: str) -> str:
    return _generate(
        "You are JalNetra, a concise marine information assistant for fishers and coastal authorities. "
        "Answer using reasonable general knowledge and estimation. Do not claim a trained PFZ, cyclone, "
        "or other prediction model was used. Do not invent live values. Clearly label estimates and say "
        "when information is unavailable. Do not give time constraints, ETAs, deadlines, or promises about "
        "when something will happen. Give practical, generic guidance in plain text, donot use * to bold, donot give large replies, give small replies in 1-2 sentences.",
        query,
    )
