"""Gemini-backed conversational responses, adapted to run on Groq."""

from __future__ import annotations

import os
import json
from pathlib import Path
import requests
from dotenv import load_dotenv
from app.language import LANGUAGE_NAMES

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

class GeminiServiceError(RuntimeError):
    """Raised when the LLM cannot produce a response."""

def _generate(system_prompt: str, user_prompt: str) -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise GeminiServiceError("Groq is not configured. Set GROQ_API_KEY.")

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.4,
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        raise GeminiServiceError("LLM API is temporarily unavailable.") from error

    try:
        answer = payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as error:
        raise GeminiServiceError("LLM returned an invalid response.") from error
    
    if not answer:
        raise GeminiServiceError("LLM returned an empty response.")
        
    return answer

def translate_to_english(text: str, language: str) -> str:
    if language == "en-IN":
        return text.strip()
    return _generate(
        "Translate the user's message to concise natural English. Return only the translation. "
        "Do not answer, summarize, add context, or change the user's intent. Preserve names, coordinates, quantities, dates, and safety questions exactly.",
        f"Language: {LANGUAGE_NAMES.get(language, language)}\nMessage: {text}",
    )

def translate_from_english(text: str, language: str) -> str:
    if language == "en-IN":
        return text.strip()
    return _generate(
        f"Translate this English answer into natural {LANGUAGE_NAMES.get(language, language)}. Return only the translation. "
        "Do not answer the question again or change its meaning. Preserve the YES/NO safety decision, marine terms, numbers, units, coordinates, caveats, and paragraph breaks exactly.",
        text,
    )

def answer_query(query: str) -> str:
    return _generate(
        "You are JalNetra, a friendly and direct marine assistant for Indian fishers and coastal workers. "
        "Your personality: helpful, honest, concise — like a knowledgeable local coast guard officer.\n"
        "Rules you MUST follow:\n"
        "- Answer the EXACT question asked. Never give a generic weather summary if the question is specific.\n"
        "- For safety questions ('can I go?', 'is it safe?'): start with a clear YES or NO, then give 1 short reason.\n"
        "- For tomorrow/forecast questions: use the tomorrow data provided in the context, not today's.\n"
        "- For off-topic messages (greetings, jokes, random text, gibberish): respond warmly in 1 sentence and offer marine help.\n"
        "- For fishing zone questions: mention confidence level and direction if available.\n"
        "- Respond in English; the caller handles the final regional-language translation.\n"
        "- NEVER use bullet points, asterisks (*), or markdown formatting.\n"
        "- Keep responses to 1-3 sentences maximum. Be direct and specific.",
        query,
    )
