import os
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
api_key = os.getenv("GEMINI_API_KEY", "").strip()

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
response = requests.get(url)
print(response.status_code)
if response.ok:
    for model in response.json().get("models", []):
        print(model["name"])
else:
    print(response.text)
