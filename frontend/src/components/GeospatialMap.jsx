"use client";

import dynamic from "next/dynamic";

const LeafletMapInner = dynamic(() => import("./LeafletMapInner"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full min-h-[360px] items-center justify-center bg-slate-100 text-sm font-medium text-slate-600">
      Loading marine map
    </div>
  ),
});

export default function GeospatialMap({ pfz, alerts = [], mapState, cached, currentLocation, onMapChange, route, routeLoading, onRouteRequest, selectedPfz, onPfzSelect }) {
  return <LeafletMapInner pfz={pfz} alerts={alerts} mapState={mapState} cached={cached} currentLocation={currentLocation} onMapChange={onMapChange} route={route} routeLoading={routeLoading} onRouteRequest={onRouteRequest} selectedPfz={selectedPfz} onPfzSelect={onPfzSelect} />;
}
