"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import GeospatialMap from "@/components/GeospatialMap";
import ReasoningTracePanel from "@/components/ReasoningTracePanel";
import VoiceInterface from "@/components/VoiceInterface";
import { ApiError, fetchAlerts, fetchPFZ, fetchTripDecision, postQuery, postRoute, synthesizeSpeech } from "@/lib/api";
import { clearChatHistory, loadLastChatMessage, loadMapState, loadOfflineSnapshot, loadRecentChatMessages, saveCachedData, saveChatMessage, saveMapState } from "@/lib/db";
import { LOCALES, message, setAppLocale } from "@/lib/i18n";
import { useResolvedLocation } from "@/lib/location-context";
import { usePhoneAuth } from "@/components/PhoneAuthProvider";
import { Languages, Settings, Trash2 } from "lucide-react";

const QUICK_QUERIES = [
  ["Where are the better fishing areas?", "Fishing areas"],
  ["Are there any boundary warnings?", "Boundary check"],
  ["What should I check before going to sea?", "Safety check"],
];
const DEFAULT_MAP_STATE = { center: [20.25, 88.45], zoom: 5 };
const TRIP_LABELS = {
  "en-IN": { title: "Trip decision", safe: "Safe to sail", caution: "Caution", unsafe: "Do not sail" },
  "hi-IN": { title: "यात्रा निर्णय", safe: "समुद्र में जाना सुरक्षित है", caution: "सावधानी", unsafe: "समुद्र में न जाएं" },
  "ta-IN": { title: "பயண முடிவு", safe: "கடலுக்குச் செல்ல பாதுகாப்பானது", caution: "எச்சரிக்கை", unsafe: "கடலுக்குச் செல்ல வேண்டாம்" },
  "te-IN": { title: "ప్రయాణ నిర్ణయం", safe: "సముద్రానికి వెళ్లడం సురక్షితం", caution: "జాగ్రత్త", unsafe: "సముద్రానికి వెళ్లవద్దు" },
  "bn-IN": { title: "যাত্রার সিদ্ধান্ত", safe: "সমুদ্রে যাওয়া নিরাপদ", caution: "সতর্কতা", unsafe: "সমুদ্রে যাবেন না" },
  "od-IN": { title: "ଯାତ୍ରା ନିଷ୍ପତ୍ତି", safe: "ସମୁଦ୍ରକୁ ଯିବା ସୁରକ୍ଷିତ", caution: "ସତର୍କତା", unsafe: "ସମୁଦ୍ରକୁ ଯାଆନ୍ତୁ ନାହିଁ" },
  "ml-IN": { title: "യാത്രാ തീരുമാനം", safe: "കടലിൽ പോകുന്നത് സുരക്ഷിതമാണ്", caution: "ജാഗ്രത", unsafe: "കടലിൽ പോകരുത്" },
  "kn-IN": { title: "ಪ್ರಯಾಣ ನಿರ್ಧಾರ", safe: "ಸಮುದ್ರಕ್ಕೆ ಹೋಗುವುದು ಸುರಕ್ಷಿತ", caution: "ಎಚ್ಚರಿಕೆ", unsafe: "ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ" },
};

function tripLabel(locale, status) {
  const copy = TRIP_LABELS[locale] || TRIP_LABELS["en-IN"];
  return status === "Safe to sail" ? copy.safe : status === "Caution" ? copy.caution : copy.unsafe;
}

function formatAge(timestamp) {
  const hours = Math.max(0, Math.round((Date.now() - timestamp) / 3600000));
  if (hours < 1) return "less than 1 hour ago";
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
}

function Icon({ name, size = 18 }) {
  if (name === "settings") return <Settings aria-hidden="true" size={size} strokeWidth={1.8} />;
  if (name === "trash") return <Trash2 aria-hidden="true" size={size} strokeWidth={1.8} />;
  const paths = {
    arrow: <path d="M5 9l7 7 7-7M12 16V3" />,
    map: <><path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3V6Z" /><path d="M9 3v15M15 6v15" /></>,
    chat: <><path d="M20 11.5a7 7 0 0 1-7.5 7 8.5 8.5 0 0 1-3.5-.8L4 19l1.4-3.7A7 7 0 1 1 20 11.5Z" /><path d="M8 11h.01M12 11h.01M16 11h.01" /></>,
    send: <><path d="m21 3-7.5 18-3.2-7.3L3 10.5 21 3Z" /><path d="M10.3 13.7 21 3" /></>,
    volume: <><path d="M4 10v4h4l5 4V6l-5 4H4Z" /><path d="M16 9.5a4 4 0 0 1 0 5M18.5 7a7.5 7.5 0 0 1 0 10" /></>,
    spark: <><path d="m12 2 1.4 5.6L19 9l-5.6 1.4L12 16l-1.4-5.6L5 9l5.6-1.4L12 2Z" /><path d="m19 15 .6 2.4L22 18l-2.4.6L19 21l-.6-2.4L16 18l2.4-.6L19 15Z" /></>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function SpeakerButton({ text, language, disabled }) {
  const [playing, setPlaying] = useState(false);
  async function replay() {
    setPlaying(true);
    try {
      const result = await synthesizeSpeech(text, language);
      const audio = new Audio(`data:${result.audio_mime_type || "audio/wav"};base64,${result.audio_base64}`);
      audio.onended = () => setPlaying(false);
      await audio.play();
    } catch { setPlaying(false); }
  }

  return <button type="button" onClick={replay} disabled={playing || disabled} className="icon-button text-slate-400 hover:text-cyan-700" aria-label="Listen to this reply" title={disabled ? "Needs internet to play audio" : "Listen to reply"}><Icon name="volume" size={16} /></button>;
}

export default function DashboardPage() {
  const { user, signOut } = usePhoneAuth();
  const [mounted, setMounted] = useState(false);
  const [pfz, setPfz] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState([]);
  const [trace, setTrace] = useState(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [mapState, setMapState] = useState(DEFAULT_MAP_STATE);
  const [history, setHistory] = useState([]);
  const [intent, setIntent] = useState(null);
  const [language, setLanguage] = useState("en-IN");
  const [logs, setLogs] = useState([]);
  const [showMap, setShowMap] = useState(false);
  const [showReasoning, setShowReasoning] = useState(false);
  const [voiceLanguage, setVoiceLanguage] = useState("en-IN");
  const [appLanguage, setAppLanguage] = useState("en-IN");
  const [showSettings, setShowSettings] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [cachedAt, setCachedAt] = useState(null);
  const [showOffline, setShowOffline] = useState(false);
  const [offlineExpanded, setOfflineExpanded] = useState(false);
  const [route, setRoute] = useState(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [tripDecision, setTripDecision] = useState(null);
  const [selectedPfz, setSelectedPfz] = useState(null);
  const { location, status: locationStatus, error: locationError, toastMessage, regions, chooseManual, changeLocation } = useResolvedLocation();

  useEffect(() => {
    setMounted(true);
  }, []);

  const loadCachedMarineData = useCallback(async () => {
    const snapshot = await loadOfflineSnapshot();
    if (snapshot.pfz?.data) setPfz(snapshot.pfz.data);
    if (snapshot.alerts?.data) setAlerts(snapshot.alerts.data);
    const timestamps = [snapshot.pfz?.savedAt, snapshot.alerts?.savedAt].filter(Boolean);
    if (timestamps.length) setCachedAt(Math.max(...timestamps));
  }, []);

  const syncMarineData = useCallback(async (resolvedLocation) => {
    try {
      const [pfzData, alertData, decisionData] = await Promise.all([
        resolvedLocation ? fetchPFZ({ latitude: resolvedLocation.lat, longitude: resolvedLocation.lon }) : Promise.resolve(null),
        fetchAlerts(),
        resolvedLocation ? fetchTripDecision({ latitude: resolvedLocation.lat, longitude: resolvedLocation.lon }).catch(() => null) : Promise.resolve(null),
      ]);
      if (pfzData) {
        await saveCachedData("pfz", pfzData);
        setPfz(pfzData);
      }
      await saveCachedData("alerts", alertData);
      setAlerts(alertData);
      setTripDecision(decisionData);
      setCachedAt(Date.now());
      setIsOffline(false);
      setStatus("Live");
      return true;
    } catch (error) {
      setIsOffline(true);
      setTripDecision(null);
      await loadCachedMarineData();
      setStatus("Offline — showing cached marine data");
      setLogs((current) => [...current, { level: "error", stage: "offline", message: error.message }]);
      return false;
    }
  }, [loadCachedMarineData]);

  useEffect(() => {
    setIsOffline(!navigator.onLine);
    syncMarineData(location);
    const handleOnline = () => syncMarineData(location);
    const handleOffline = () => { setIsOffline(true); setStatus("Offline — showing cached marine data"); };
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => { window.removeEventListener("online", handleOnline); window.removeEventListener("offline", handleOffline); };
  }, [syncMarineData, location]);

  useEffect(() => {
    if (location) setMapState((current) => ({ ...current, center: [location.lat, location.lon], zoom: Math.max(current.zoom, 11) }));
  }, [location]);

  useEffect(() => {
    Promise.all([loadMapState(), loadLastChatMessage(), loadRecentChatMessages()]).then(([savedMap, savedChat, savedHistory]) => {
      if (savedMap) setMapState({ center: savedMap.center, zoom: savedMap.zoom });
      setHistory(savedHistory);
      if (savedChat) setMessages([{ role: "user", text: savedChat.query }, { role: "assistant", text: savedChat.answer }]);
    });
  }, []);

  useEffect(() => {
    if (selectedPfz && selectedPfz.destination) {
      if (isOffline || !navigator.onLine) return;
      const { lon, lat } = selectedPfz.destination;
      fetchTripDecision({ latitude: lat, longitude: lon })
        .then(setTripDecision)
        .catch(() => {});
    } else if (!selectedPfz && location && !isOffline) {
      fetchTripDecision({ latitude: location.lat, longitude: location.lon })
        .then(setTripDecision)
        .catch(() => {});
    }
  }, [selectedPfz, location, isOffline]);

  const layerSummary = useMemo(() => `${pfz?.features?.length || 0} zones · ${alerts.length} alerts`, [pfz, alerts]);

  async function submitQuery(rawQuery) {
    const submittedQuery = rawQuery.trim();
    if (!submittedQuery || loading) return;
    setQuery("");
    setMessages((current) => [...current, { role: "user", text: submittedQuery }]);
    setLoading(true);
    setStatus("Thinking");
    if (isOffline || !navigator.onLine) {
      const age = cachedAt ? ` (${formatAge(cachedAt)})` : "";
      const zoneCount = pfz?.features?.length || 0;
      const alertSummary = alerts.length ? `${alerts.length} active alert${alerts.length === 1 ? "" : "s"}` : "no active alerts";
      const answer = `Can't reach live data right now. Last known conditions${age}: ${zoneCount} potential fishing zone${zoneCount === 1 ? "" : "s"} near ${mapState.center[0].toFixed(2)}, ${mapState.center[1].toFixed(2)}, ${alertSummary}.`;
      setMessages((current) => [...current, { role: "assistant", text: answer }]);
      await saveChatMessage(submittedQuery, answer);
      setHistory(await loadRecentChatMessages());
      setStatus("Offline — showing cached marine data");
      setLoading(false);
      return;
    }
    try {
      // Send only the current question — previous messages confused intent detection
      // and caused every reply to be the same. History is passed separately as context.
      const recentHistory = messages.slice(-6).map((item) => ({ role: item.role, text: item.text }));
      const currentLat = location?.lat ?? mapState.center[0];
      const currentLon = location?.lon ?? mapState.center[1];
      const result = await postQuery(submittedQuery, { language, latitude: currentLat, longitude: currentLon, history: recentHistory });
      const answer = result.answer || "No answer returned.";
      setMessages((current) => [...current, { role: "assistant", text: answer }]);
      if (result.geojson && result.geojson.features) {
        setPfz(result.geojson);
      }
      setTrace(result.visual_trace);
      setLogs(result.execution_log || []);
      setIntent(result.intent || "Marine information");
      setLanguage(result.language || language);
      await saveChatMessage(submittedQuery, answer);
      setHistory(await loadRecentChatMessages());
      setStatus("");
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Query failed.";
      setMessages((current) => [...current, { role: "error", text: message }]);
      setStatus("Something went wrong");
      setLogs((current) => [...current, { level: "error", stage: "api", message }]);
    } finally {
      setLoading(false);
    }
  }

  async function handleVoiceResult(result) {
    setMessages((current) => [...current, { role: "user", text: result.transcribed_text }, { role: "assistant", text: result.answer }]);
    setTrace(result.visual_trace || null);
    setLogs(result.execution_log || []);
    setIntent(result.intent || "Marine information");
    setLanguage(result.language || language);
    await saveChatMessage(result.transcribed_text, result.answer);
    setHistory(await loadRecentChatMessages());
  }

  async function clearChat() {
    if (loading) return;
    await clearChatHistory();
    setMessages([]);
    setQuery("");
    setHistory([]);
    setTrace(null);
    setLogs([]);
    setIntent(null);
  }

  function changeAppLanguage(nextLanguage) {
    setAppLanguage(nextLanguage);
    setLanguage(nextLanguage);
    setVoiceLanguage(nextLanguage);
    setAppLocale(nextLanguage);
  }

  async function planRoute(destination) {
    const origin = location ? { lat: location.lat, lon: location.lon } : { lat: mapState.center[0], lon: mapState.center[1] };
    setRouteLoading(true);
    try {
      setRoute(await postRoute(origin, destination));
      setStatus("Safe route ready");
    } catch (error) {
      setStatus(error instanceof ApiError ? error.message : "Route could not be planned.");
    } finally { setRouteLoading(false); }
  }

  function planRouteToFishingZone() {
    const destination = tripDecision?.best_fishing_direction;
    if (destination) planRoute({ lat: destination.latitude, lon: destination.longitude });
  }

  return (
    <main className="app-shell">
      {isOffline && <div className="offline-banner" role="status">Offline — showing data from {cachedAt ? formatAge(cachedAt) : "the last successful sync"}</div>}
      {toastMessage && <div className="pfz-notice widened" role="status" style={{ margin: "8px 16px 0", borderRadius: "8px" }}><Icon name="spark" size={16} /><span>{toastMessage}</span></div>}
      <header className="app-header">
        <div className="brand-lockup"><div className="brand-mark"><span className="brand-dot" />JalNetra</div><h1>your marine assistant</h1></div>
        <div className="header-language"><Languages size={15} /><select aria-label="App language" value={appLanguage} onChange={(event) => changeAppLanguage(event.target.value)}>{LOCALES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></div>
        <button type="button" className="settings-button" onClick={() => setShowSettings(true)} aria-label={message(appLanguage, "settings")} title={message(appLanguage, "settings")}><Icon name="settings" size={17} /></button>
        <div className="mobile-view-tabs"><button type="button" className={!showMap && !showOffline ? "is-active" : ""} onClick={() => { setShowMap(false); setShowOffline(false); }}>Chat</button><button type="button" className={showMap ? "is-active" : ""} onClick={() => { setShowMap(true); setShowOffline(false); }}><Icon name="map" size={15} />Map</button><button type="button" className={showOffline ? "is-active" : ""} onClick={() => { setShowMap(false); setShowOffline(true); }}>Offline</button></div>
      </header>

      <section className="workspace">
        <aside className={`chat-column ${showMap || showOffline ? "mobile-hidden" : ""}`}>
          {locationStatus === "manual" && <div className="location-picker"><strong>Choose your coastal region</strong>{locationError && <p>{locationError}</p>}<button type="button" className="location-detect-button" onClick={changeLocation}>Use my current location</button><select defaultValue="" onChange={(event) => { const region = regions.find((item) => item.name === event.target.value); if (region) chooseManual(region); }}><option value="" disabled>Select a region or port</option>{regions.map((region) => <option key={region.name} value={region.name}>{region.name}</option>)}</select></div>}
          <div className="desktop-utility-row">
            <div className="reasoning-drawer">
            <button type="button" className="reasoning-trigger" onClick={() => setShowReasoning((current) => !current)} aria-expanded={showReasoning}>
              <span className="trigger-icon"><Icon name="arrow" size={15} /></span>
              <span><strong>{message(appLanguage, "agentReasoning")}</strong><small>{logs.length ? `${logs.length} ${message(appLanguage, "events")}` : ""}</small></span>
              <span className="drawer-chevron">{showReasoning ? "−" : "+"}</span>
            </button>
            {showReasoning && <div className="reasoning-content"><ReasoningTracePanel trace={trace} logs={logs} /></div>}
            </div>
            <div className="offline-column"><div className="offline-panel"><button type="button" className="offline-panel-trigger" onClick={() => setOfflineExpanded((current) => !current)} aria-expanded={offlineExpanded}><strong>{message(appLanguage, "offlineData")}</strong><span aria-hidden="true">{offlineExpanded ? "−" : "+"}</span></button>{offlineExpanded && <div className="offline-panel-content"><p>{message(appLanguage, isOffline ? "offlinePaused" : "offlineStored")}</p><div className="offline-stat"><strong>{cachedAt ? formatAge(cachedAt) : "No snapshot yet"}</strong><span>{message(appLanguage, "lastSync")}</span></div><div className="offline-stat"><strong>{pfz?.features?.length || 0}</strong><span>{message(appLanguage, "cachedZones")}</span></div><div className="offline-stat"><strong>{alerts.length}</strong><span>{message(appLanguage, "cachedAlerts")}</span></div><p className="offline-note">{message(appLanguage, "offlineLimit")}</p></div>}</div></div>
          </div>

          <div className="chat-heading"><div className="chat-heading-copy"><p className="eyebrow">{message(appLanguage, "marineAssistant")}</p></div><button type="button" suppressHydrationWarning className="clear-chat-button desktop-clear-chat-button" onClick={clearChat} disabled={!mounted || loading || !messages.length}><Icon name="trash" size={15} />Clear chat</button></div>

          <div className="messages" aria-live="polite">
            {!messages.length && <div className="welcome-block"><div className="welcome-icon"><Icon name="spark" size={25} /></div><p>{message(appLanguage, "prompt")}</p><div className="suggestion-grid">{QUICK_QUERIES.map(([text, label]) => <button key={text} type="button" disabled={loading} onClick={() => submitQuery(text)}><span>{label}</span><Icon name="arrow" size={14} /></button>)}</div></div>}
            {messages.map((item, index) => <div key={`${item.role}-${index}`} className={`message-row ${item.role}`}><div className="message-bubble">{item.role === "assistant" && <span className="message-label">JalNetra</span>}<p>{item.text}</p>{item.role === "assistant" && <SpeakerButton text={item.text} language={language} disabled={isOffline} />}</div></div>)}
            {loading && <div className="message-row assistant"><div className="message-bubble thinking-bubble"><span className="message-label">JalNetra</span><div className="thinking"><span /><span /><span /></div></div></div>}
          </div>

          <div className="composer-wrap">
            <form className="composer" onSubmit={(event) => { event.preventDefault(); submitQuery(query); }}>
              <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask a marine question..." rows={1} disabled={loading} aria-label="Your question" onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submitQuery(query); } }} />
              <VoiceInterface disabled={loading || isOffline} inputLanguage={voiceLanguage} outputLanguage={language} latitude={location?.lat ?? mapState.center[0]} longitude={location?.lon ?? mapState.center[1]} history={messages.slice(-6).map((item) => ({ role: item.role, text: item.text }))} onStatus={(statusMessage) => { setStatus(statusMessage); if (/transcribing/i.test(statusMessage)) setLoading(true); if (/voice answer ready|text answer ready|voice processing unavailable/i.test(statusMessage)) setLoading(false); if (/unavailable|error|failed|quota|configured/i.test(statusMessage)) setLogs((current) => [...current, { level: "error", stage: "voice", message: statusMessage }]); }} onResult={handleVoiceResult} />
              <button type="submit" className="send-button" disabled={loading || !query.trim()} aria-label="Send question" title="Send question"><Icon name="send" size={18} /></button>
            </form>
            <div className="composer-meta"><label htmlFor="query-language">{message(appLanguage, "replyIn")}</label><select id="query-language" value={language} onChange={(event) => setLanguage(event.target.value)} disabled={loading}>{LOCALES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></div>
          </div>
        </aside>

        <section className={`map-column ${!showMap ? "mobile-hidden" : ""}`}>
          <div className="map-heading"><div><p className="eyebrow">Live view</p><h2>{message(appLanguage, "marineMap")}</h2></div><span className="layer-summary">{layerSummary}</span></div>
          {tripDecision && <section className={`trip-decision ${tripDecision.status === "Safe to sail" ? "is-safe" : tripDecision.status === "Caution" ? "is-caution" : "is-unsafe"}`} aria-label={TRIP_LABELS[appLanguage]?.title || "Trip decision"}>
            <div className="trip-decision-heading"><div><p>{TRIP_LABELS[appLanguage]?.title || "Trip decision"}</p><h3>{tripLabel(appLanguage, tripDecision.status)}</h3></div><span>{formatAge(new Date(tripDecision.fresh_at).getTime())}</span></div>
            <p className="trip-reason">{tripDecision.reasons?.[0] || "Weather conditions are within the current safety thresholds."}</p>
            <div className="trip-drivers">{tripDecision.drivers.map((driver) => <div key={driver.label} className={driver.safe ? "is-ok" : "is-risk"}><span>{driver.label}</span><strong>{driver.value}</strong></div>)}</div>
            {tripDecision.best_fishing_direction && <div className="fishing-direction"><span>Best fishing direction</span><strong>{tripDecision.best_fishing_direction.bearing_deg}° · {tripDecision.best_fishing_direction.distance_km} km away</strong></div>}
            <div className="trip-actions"><button type="button" onClick={planRouteToFishingZone} disabled={!tripDecision.best_fishing_direction || routeLoading}>Show safe route</button><button type="button" className="secondary" onClick={() => submitQuery("When are conditions safer for fishing from my current location?")}>See safer time</button></div>
            <div className="trip-sources">Updated now · {tripDecision.sources.join(" · ") || "Live providers"}</div>
          </section>}
          {pfz && (pfz.data_availability === "no_data" || !pfz?.features?.length) && (
            <div className="pfz-notice no-data" role="status">
              <Icon name="spark" size={16} />
              <span>{message(appLanguage, "pfzNoData")}</span>
            </div>
          )}
          {pfz && pfz.data_availability === "widened" && (pfz?.features?.length || 0) > 0 && (
            <div className="pfz-notice widened" role="status">
              <Icon name="spark" size={16} />
              <span>{message(appLanguage, "pfzWidened")}</span>
            </div>
          )}
          <div className={`map-frame ${isOffline ? "is-cached" : ""}`}><GeospatialMap pfz={pfz} alerts={alerts} mapState={mapState} cached={isOffline} currentLocation={location ? { latitude: location.lat, longitude: location.lon, accuracy: 1000 } : null} route={route} routeLoading={routeLoading} onRouteRequest={planRoute} selectedPfz={selectedPfz} onPfzSelect={setSelectedPfz} onMapChange={(nextMapState) => { setMapState(nextMapState); saveMapState(nextMapState); }} /></div>
          <div className="map-footer"><span><i className="legend-dot zone" />Potential fishing zones</span><span><i className="legend-dot location" />{location ? `Resolved ${location.source} location` : locationStatus}</span>{pfz?.last_updated && <span>{pfz.stale ? "Last updated: " : "PFZ as of "}{new Date(pfz.last_updated).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>}</div>
        </section>
        <section className={`mobile-offline-column ${!showOffline ? "mobile-hidden" : ""}`}><div className="offline-panel"><button type="button" className="offline-panel-trigger" onClick={() => setOfflineExpanded((current) => !current)} aria-expanded={offlineExpanded}><strong>{message(appLanguage, "offlineData")}</strong><span aria-hidden="true">{offlineExpanded || showOffline ? "−" : "+"}</span></button>{(offlineExpanded || showOffline) && <div className="offline-panel-content"><p>{message(appLanguage, isOffline ? "offlinePaused" : "offlineStored")}</p><div className="offline-stat"><strong>{cachedAt ? formatAge(cachedAt) : "No snapshot yet"}</strong><span>{message(appLanguage, "lastSync")}</span></div><div className="offline-stat"><strong>{pfz?.features?.length || 0}</strong><span>{message(appLanguage, "cachedZones")}</span></div><div className="offline-stat"><strong>{alerts.length}</strong><span>{message(appLanguage, "cachedAlerts")}</span></div><p className="offline-note">{message(appLanguage, "offlineLimit")}</p></div>}</div></section>
      </section>
      {showSettings && <div className="settings-backdrop" role="presentation" onClick={() => setShowSettings(false)}><section className="settings-sheet" role="dialog" aria-modal="true" aria-labelledby="settings-title" onClick={(event) => event.stopPropagation()}><div className="settings-title"><h2 id="settings-title">{message(appLanguage, "settings")}</h2><button type="button" onClick={() => setShowSettings(false)} aria-label={message(appLanguage, "close")}>×</button></div><label htmlFor="app-language">{message(appLanguage, "appLanguage")}</label><select id="app-language" value={appLanguage} onChange={(event) => changeAppLanguage(event.target.value)}>{LOCALES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select><label htmlFor="voice-language">{message(appLanguage, "inputLanguage")}</label><select id="voice-language" value={voiceLanguage} onChange={(event) => setVoiceLanguage(event.target.value)}>{LOCALES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select>{location && <button type="button" className="location-change-button" onClick={changeLocation}>Change location</button>}<button type="button" suppressHydrationWarning className="clear-chat-button settings-clear-button" onClick={clearChat} disabled={Boolean(loading || !messages.length)}><Icon name="trash" size={15} />Clear chat</button><button type="button" className="auth-link settings-signout" onClick={() => signOut()}>{user.phoneNumber ? `Sign out (${user.phoneNumber})` : "Sign out"}</button></section></div>}
    </main>
  );
}
