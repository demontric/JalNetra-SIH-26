"use client";

import { useEffect, useRef, useState } from "react";
import { useMap, useMapEvents } from "react-leaflet";
import { Circle, CircleMarker, GeoJSON, MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";

const ALERT_ZONES = {
  cyclone: polygonFeature("Cyclone watch", "weather_alert", [
    [86.7, 19.1],
    [88.9, 19.1],
    [88.9, 21.1],
    [86.7, 21.1],
    [86.7, 19.1],
  ]),
  geofence: polygonFeature("Protected coastal restriction", "weather_alert", [
    [87.8, 19.6],
    [88.6, 19.6],
    [88.6, 20.2],
    [87.8, 20.2],
    [87.8, 19.6],
  ]),
};

function polygonFeature(name, zoneType, coordinates) {
  return {
    type: "Feature",
    properties: { name, zone_type: zoneType },
    geometry: { type: "Polygon", coordinates: [coordinates] },
  };
}

function alertCollection(alerts) {
  return {
    type: "FeatureCollection",
    features: alerts.map((alert) => ({
      ...(ALERT_ZONES[alert.alert_type || alert.type] || ALERT_ZONES.cyclone),
      properties: {
        ...alert,
        name: alert.title || alert.message || alert.alert_type || alert.type,
        zone_type: "weather_alert",
      },
    })),
  };
}

function pfzKey(feature) {
  return `${feature?.properties?.name || "pfz"}-${feature?.geometry?.coordinates?.[0]?.[0]?.join(",")}`;
}

function pfzDestination(feature) {
  const points = feature.geometry.coordinates[0].slice(0, -1);
  return { lat: points.reduce((sum, [, lat]) => sum + lat, 0) / points.length, lon: points.reduce((sum, [lon]) => sum + lon, 0) / points.length };
}

function styleFeature(feature, cached, pfzStale, selectedPfz) {
  const zoneType = feature?.properties?.zone_type;
  const confidence = Number(feature?.properties?.confidence_score || 0);
  const green = Math.round(90 + confidence * 100).toString(16).padStart(2, "0");
  const selectedStyle = pfzKey(feature) === selectedPfz ? { color: "#0e7490", fillColor: "#22d3ee", fillOpacity: 0.55, weight: 4 } : {};
  const computedStyle = zoneType === "potential_fishing_zone" ? { color: "#166534", fillColor: `#${green}b84a`, fillOpacity: 0.25 + confidence * 0.45, weight: 2, ...selectedStyle } : {};
  const cachedStyle = cached || pfzStale ? { opacity: 0.68, fillOpacity: 0.18, weight: 2, dashArray: "7 5" } : {};
  if (zoneType === "potential_fishing_zone") {
    return { ...computedStyle, ...cachedStyle, ...selectedStyle };
  }
  if (zoneType === "weather_alert") {
    return { color: "#b45309", fillColor: "#f59e0b", fillOpacity: 0.22, weight: 2, ...cachedStyle };
  }
  return { color: "#1d4ed8", fillColor: "#60a5fa", fillOpacity: 0.12, weight: 2, dashArray: "6 4", ...cachedStyle };
}

function bindPopup(feature, layer, onPfzSelect) {
  const props = feature.properties || {};
  const details = props.confidence_score == null ? "" : `<br />Confidence: ${(props.confidence_score * 100).toFixed(0)}%<br />SST: ${Number(props.sst_value).toFixed(2)} C<br />Chlorophyll: ${Number(props.chlorophyll_value).toFixed(3)} mg/m3`;
  const selectable = props.zone_type === "potential_fishing_zone";
  layer.bindPopup(`<strong>${props.name || props.zone_type || "Marine zone"}</strong>${details}${selectable ? "<br />Click this zone to select it for safe routing." : ""}`);
  if (selectable) layer.on("click", () => onPfzSelect?.({ key: pfzKey(feature), destination: pfzDestination(feature) }));
}

function MapStateSaver({ onMapChange }) {
  useMapEvents({
    moveend(event) {
      const map = event.target;
      const center = map.getCenter();
      onMapChange?.({ center: [center.lat, center.lng], zoom: map.getZoom() });
    },
  });
  return null;
}

function MapStateRestorer({ mapState }) {
  const map = useMap();
  useEffect(() => {
    if (!mapState) return;
    const center = map.getCenter();
    if (center.lat !== mapState.center[0] || center.lng !== mapState.center[1] || map.getZoom() !== mapState.zoom) {
      map.setView(mapState.center, mapState.zoom, { animate: false });
    }
  }, [map, mapState]);
  return null;
}

function MapSizeObserver() {
  const map = useMap();
  const containerRef = useRef(null);

  useEffect(() => {
    const container = map.getContainer();
    const resize = () => map.invalidateSize({ pan: false, animate: false });
    containerRef.current = container;
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    return () => observer.disconnect();
  }, [map]);

  return null;
}

function CurrentLocationMarker({ location }) {
  const map = useMap();
  const centeredRef = useRef(false);

  useEffect(() => {
    if (!location || centeredRef.current) return;
    centeredRef.current = true;
    map.setView([location.latitude, location.longitude], Math.max(map.getZoom(), 11), { animate: false });
  }, [location, map]);

  if (!location) return null;
  const center = [location.latitude, location.longitude];
  return <><Circle center={center} radius={location.accuracy} pathOptions={{ color: "#0e7490", fillColor: "#67e8f9", fillOpacity: 0.12, weight: 1, dashArray: "4 4" }} /><Circle center={center} radius={9260} pathOptions={{ color: "#0e7490", fill: false, opacity: 0.5, weight: 1, dashArray: "5 6" }} /><CircleMarker center={center} radius={8} pathOptions={{ color: "#fff", fillColor: "#0e7490", fillOpacity: 1, weight: 3 }}><Tooltip permanent direction="top" offset={[0, -8]}>Your vessel position</Tooltip></CircleMarker></>;
}

function RouteClickHandler({ active, onSelect }) {
  useMapEvents({ click(event) { if (active) onSelect({ lat: event.latlng.lat, lon: event.latlng.lng }); } });
  return null;
}

function RouteLine({ route }) {
  const coordinates = route?.path_geojson?.geometry?.coordinates;
  if (!coordinates?.length) return null;
  const points = coordinates.map(([lon, lat]) => [lat, lon]);
  return <><Polyline positions={points} pathOptions={{ color: "#0e7490", weight: 5, opacity: 0.9 }} /><Polyline positions={points} pathOptions={{ color: "#d9f4ef", weight: 2, dashArray: "8 9", opacity: 0.9 }} /><CircleMarker center={points.at(-1)} radius={7} pathOptions={{ color: "#fff", fillColor: "#16a34a", fillOpacity: 1, weight: 3 }}><Tooltip permanent direction="top">Route destination</Tooltip></CircleMarker></>;
}

function prefetchTiles(center, zoom) {
  const scale = 2 ** zoom;
  const x = Math.floor(((center[1] + 180) / 360) * scale);
  const y = Math.floor(((1 - Math.asinh(Math.tan((center[0] * Math.PI) / 180)) / Math.PI) / 2) * scale);
  const urls = [];
  for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
    for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
      const tileX = (x + offsetX + scale) % scale;
      const tileY = Math.max(0, Math.min(scale - 1, y + offsetY));
      urls.push(`https://${["a", "b", "c"][urls.length % 3]}.tile.openstreetmap.org/${zoom}/${tileX}/${tileY}.png`);
    }
  }
  urls.forEach((url) => fetch(url).catch(() => null));
}

function MapTilePrefetcher({ mapState, cached }) {
  const prefetchedRef = useRef(false);

  useEffect(() => {
    if (cached || prefetchedRef.current || !mapState) return;
    prefetchedRef.current = true;
    prefetchTiles(mapState.center, mapState.zoom);
  }, [cached, mapState]);

  return null;
}

export default function LeafletMapInner({ pfz, alerts, mapState, cached, currentLocation, onMapChange, route, routeLoading, onRouteRequest, selectedPfz, onPfzSelect }) {
  const activeAlerts = alertCollection(alerts);
  const [showPfz, setShowPfz] = useState(true);
  const [showAlerts, setShowAlerts] = useState(true);
  const [planningRoute, setPlanningRoute] = useState(false);
  const routePosition = route?.path_geojson?.geometry?.coordinates?.length ? route.path_geojson.geometry.coordinates.map(([lon, lat]) => [lat, lon]) : null;

  function selectRouteDestination(destination) {
    setPlanningRoute(false);
    onRouteRequest?.(destination);
  }

  return (
    <div className="marine-map-root">
    <MapContainer
      center={mapState?.center || [20.25, 88.45]}
      zoom={mapState?.zoom || 8}
      scrollWheelZoom
      className="marine-map-canvas"
      maxBounds={[
        [5, 66],
        [24, 99],
      ]}
      maxBoundsViscosity={0.6}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <MapSizeObserver />
      <MapTilePrefetcher mapState={mapState} cached={cached} />
      <CurrentLocationMarker location={currentLocation} />
      <MapStateRestorer mapState={mapState} />
      <MapStateSaver onMapChange={onMapChange} />
      <RouteClickHandler active={planningRoute} onSelect={selectRouteDestination} />
      <RouteLine route={route} />
      {showPfz && pfz?.features?.length ? (
        <GeoJSON key={`pfz-${pfz.last_updated || pfz.features.length}-${selectedPfz?.key || "none"}`} data={pfz} style={(feature) => styleFeature(feature, cached, pfz.stale, selectedPfz?.key)} onEachFeature={(feature, layer) => bindPopup(feature, layer, onPfzSelect)} />
      ) : null}
      {showAlerts && <GeoJSON data={activeAlerts} style={(feature) => styleFeature(feature, cached)} onEachFeature={bindPopup} />}
    </MapContainer>
    <div className="marine-map-hud" aria-label="Map controls">
      <div className="map-live-chip"><span />Live marine layers</div>
      <div className="map-layer-controls"><button type="button" className={showPfz ? "is-active" : ""} onClick={() => setShowPfz((value) => !value)}>PFZ {pfz?.features?.length || 0}</button><button type="button" className={showAlerts ? "is-active warning" : ""} onClick={() => setShowAlerts((value) => !value)}>Alerts {alerts.length}</button></div>
    </div>
    <div className="route-control"><button type="button" disabled={!currentLocation || routeLoading} className={planningRoute ? "is-planning" : ""} onClick={() => selectedPfz ? onRouteRequest?.(selectedPfz.destination) : setPlanningRoute((value) => !value)}>{routeLoading ? "Finding route…" : selectedPfz ? "Route to selected PFZ" : planningRoute ? "Click the map to set destination" : "Plan safe route"}</button>{route && <div><strong>{route.distance_km.toFixed(1)} km · {route.estimated_time_mins} min</strong><span>{route.hazard_notes?.[0] || "Route avoids known hazards."}</span></div>}</div>
    {routePosition && <div className="route-endpoint">Destination set</div>}
    </div>
  );
}
