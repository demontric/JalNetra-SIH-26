const API_BASE = "";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function requestJson(path, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new ApiError(payload.detail || `Backend returned ${response.status}`, response.status);
    }

    return response.json();
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError("Backend is unavailable. Start FastAPI on port 8000.");
  }
}

function withParams(path, params = {}) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value) {
      query.set(key, value);
    }
  });

  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export function fetchPFZ(params) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 40_000);
  return requestJson(withParams("/api/v1/pfz", params), { signal: controller.signal }).finally(
    () => clearTimeout(timer)
  );
}

export function fetchAlerts(params) {
  return requestJson(withParams("/api/v1/alerts", params));
}

export function fetchTripDecision(params) {
  return requestJson(withParams("/api/v1/trip-decision", params));
}

export function postQuery(query, { language = "en-IN", userId = "dashboard-user", latitude, longitude, history = [] } = {}) {
  return requestJson("/api/v1/query", {
    method: "POST",
    body: JSON.stringify({ query, language, user_id: userId, latitude, longitude, history }),
  });
}

export function postRoute(origin, destination, vesselType = "motorized_boat") {
  return requestJson("/api/v1/route", {
    method: "POST",
    body: JSON.stringify({ origin, destination, vessel_type: vesselType }),
  });
}

export function synthesizeSpeech(text, language) {
  return requestJson("/api/v1/speech", {
    method: "POST",
    body: JSON.stringify({ text, language }),
  });
}

export async function postVoiceQuery(audio, inputLanguage, outputLanguage, { latitude, longitude, history = [] } = {}) {
  const formData = new FormData();
  formData.append("audio", audio, audio.name || "recording.webm");
  formData.append("language", inputLanguage);
  formData.append("reply_language", outputLanguage);
  if (latitude != null && longitude != null) {
    formData.append("latitude", String(latitude));
    formData.append("longitude", String(longitude));
  }
  formData.append("history", JSON.stringify(history));

  try {
    const response = await fetch(`${API_BASE}/api/v1/voice-query`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new ApiError(payload.detail || `Voice service returned ${response.status}`, response.status);
    }
    return response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("Voice service is unavailable. You can still type your question.");
  }
}
