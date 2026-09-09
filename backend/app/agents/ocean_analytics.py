"""INCOIS ERDDAP ocean observations with Copernicus fallback."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, UTC
import math
from typing import Any
from urllib.parse import quote

import httpx

try:
    import truststore
    truststore.inject_into_ssl()
except ModuleNotFoundError:
    pass

from app.core.cache import cache_key, fetch_with_cache_and_fallback
from app.core.config import settings

INCOIS_SST_DATASET = "incois_argo_sst_weekly"
INCOIS_CHL_DATASET = "IRS_chlorophyll_datasets"
COPERNICUS_BASE_URL = "https://data.marine.copernicus.eu"
_PFZ_TTL_SECONDS = 1800  # 30-minute cache
_pfz_mem_cache: dict[str, tuple[float, dict]] = {}  # process-level fallback


def _bbox(latitude: float, longitude: float, radius: float = 0.5) -> tuple[float, float, float, float]:
    return longitude - radius, latitude - radius, longitude + radius, latitude + radius


async def _incois_grid(latitude: float, longitude: float, radius: float = 0.5) -> dict[str, Any]:
    min_lon, min_lat, max_lon, max_lat = _bbox(latitude, longitude, radius)
    def expression(variable: str) -> str:
        return quote(f"{variable}[(last)][({min_lat}):({max_lat})][({min_lon}):({max_lon})]", safe="(),:")

    base_url = settings.INCOIS_ERDDAP_BASE_URL.rstrip("/")
    sst_url = f"{base_url}/griddap/{INCOIS_SST_DATASET}.json?{expression('ASST')}"
    chl_url = f"{base_url}/griddap/{INCOIS_CHL_DATASET}.json?{expression('CHLOROPHYLL')}"

    try:
        async with httpx.AsyncClient(verify=False, timeout=4.0) as client:
            sst_response, chl_response = await asyncio.gather(client.get(sst_url), client.get(chl_url))
            sst_rows = sst_response.json().get("table", {}).get("rows", []) if sst_response.status_code == 200 else []
            chl_rows = chl_response.json().get("table", {}).get("rows", []) if chl_response.status_code == 200 else []
    except Exception:
        return {"valid_chl": 0, "null_ratio": 1.0, "sst_grid": [], "chl_grid": []}

    valid_chl_rows = []
    for r in chl_rows:
        try:
            val = float(r[3])
            if math.isfinite(val) and val > -1e20:
                valid_chl_rows.append(r)
        except (TypeError, ValueError, IndexError):
            pass

    total_chl = len(chl_rows)
    valid_count = len(valid_chl_rows)
    null_ratio = 1.0 - (valid_count / total_chl) if total_chl > 0 else 1.0

    sst_grid = []
    chl_grid = []
    # Always attempt the join when both datasets returned data — don't gate on null_ratio alone.
    # Sparse coastal CHL (e.g. null_ratio ~0.93) still contains valid observations.
    if valid_chl_rows and sst_rows:
        for sst_row in sst_rows:
            try:
                sst_lat, sst_lon, sst_value = float(sst_row[1]), float(sst_row[2]), float(sst_row[3])
                if sst_value <= -1e20:
                    continue
                nearest = min(valid_chl_rows, key=lambda row: abs(float(row[1]) - sst_lat) + abs(float(row[2]) - sst_lon))
                chl_val = float(nearest[3])
                if chl_val <= -1e20:
                    continue
                sst_grid.append({"lat": sst_lat, "lon": sst_lon, "value": sst_value})
                chl_grid.append({"lat": sst_lat, "lon": sst_lon, "value": chl_val})
            except (TypeError, ValueError, IndexError):
                continue

    return {
        "valid_chl": valid_count,
        "total_chl": total_chl,
        "null_ratio": null_ratio,
        "sst_grid": sst_grid,
        "chl_grid": chl_grid,
    }



def _sync_copernicus_grid(latitude: float, longitude: float, radius: float = 0.5) -> dict[str, Any]:
    min_lon, min_lat, max_lon, max_lat = _bbox(latitude, longitude, radius)
    now = datetime.now(UTC)
    start_str = (now - timedelta(days=5)).isoformat()
    end_str = now.isoformat()
    username = settings.COPERNICUS_MARINE_USERNAME
    password = settings.COPERNICUS_MARINE_PASSWORD

    try:
        import copernicusmarine  # type: ignore[import-untyped]

        ds_chl = copernicusmarine.open_dataset(
            dataset_id="cmems_mod_glo_bgc-pft_anfc_0.25deg_P1D-m",
            username=username,
            password=password,
            variables=["chl"],
            minimum_longitude=min_lon,
            maximum_longitude=max_lon,
            minimum_latitude=min_lat,
            maximum_latitude=max_lat,
            start_datetime=start_str,
            end_datetime=end_str,
        )
        chl_sub = ds_chl["chl"].isel(time=-1)
        if "depth" in chl_sub.dims:
            chl_sub = chl_sub.isel(depth=0)

        ds_sst = copernicusmarine.open_dataset(
            dataset_id="cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m",
            username=username,
            password=password,
            variables=["thetao"],
            minimum_longitude=min_lon,
            maximum_longitude=max_lon,
            minimum_latitude=min_lat,
            maximum_latitude=max_lat,
            start_datetime=start_str,
            end_datetime=end_str,
        )
        sst_sub = ds_sst["thetao"].isel(time=-1)
        if "depth" in sst_sub.dims:
            sst_sub = sst_sub.isel(depth=0)

        chl_arr = chl_sub.values
        chl_lats = chl_sub.latitude.values
        chl_lons = chl_sub.longitude.values

        chl_points = []
        for i, clat in enumerate(chl_lats):
            for j, clon in enumerate(chl_lons):
                val = float(chl_arr[i, j])
                if math.isfinite(val) and val > -1e20 and not math.isnan(val):
                    chl_points.append((float(clat), float(clon), val))

        if not chl_points:
            return {"sst_grid": [], "chl_grid": [], "valid_chl": 0}

        sst_arr = sst_sub.values
        sst_lats = sst_sub.latitude.values
        sst_lons = sst_sub.longitude.values

        sst_grid = []
        chl_grid = []
        for i, slat in enumerate(sst_lats):
            for j, slon in enumerate(sst_lons):
                sst_val = float(sst_arr[i, j])
                if not math.isfinite(sst_val) or sst_val <= -1e20 or math.isnan(sst_val):
                    continue
                if sst_val > 200:
                    sst_val -= 273.15
                nearest_chl = min(chl_points, key=lambda p: abs(p[0] - slat) + abs(p[1] - slon))
                if abs(nearest_chl[0] - slat) + abs(nearest_chl[1] - slon) <= 0.4:
                    sst_grid.append({"lat": float(slat), "lon": float(slon), "value": sst_val})
                    chl_grid.append({"lat": float(slat), "lon": float(slon), "value": nearest_chl[2]})

        return {"sst_grid": sst_grid, "chl_grid": chl_grid, "valid_chl": len(chl_points)}
    except Exception:
        return {"sst_grid": [], "chl_grid": [], "valid_chl": 0}


def predict_pfz(sst_grid: Any, chlorophyll_grid: Any | None = None, model: Any | None = None) -> dict[str, Any]:
    """Score SST/chlorophyll grids, retaining compatibility with the old model wrapper."""
    if chlorophyll_grid is not None:
        return {"cells": score_pfz_grid(sst_grid, chlorophyll_grid)}
    from app.pfz_model import predict_pfz as predict

    return predict(sst_grid, model)


def score_pfz_grid(sst_grid: list[dict[str, float]], chlorophyll_grid: list[dict[str, float]]) -> list[dict[str, Any]]:
    """Score every matching cell using SST finite differences and chlorophyll."""
    chlorophyll_by_cell = {(round(item["lat"], 6), round(item["lon"], 6)): item["value"] for item in chlorophyll_grid}
    cells = []
    for index, sst in enumerate(sst_grid):
        key = (round(sst["lat"], 6), round(sst["lon"], 6))
        if key not in chlorophyll_by_cell:
            continue
        neighbors = [other["value"] for other in sst_grid if abs(other["lat"] - sst["lat"]) < 0.1 and abs(other["lon"] - sst["lon"]) > 0]
        gradient = max((abs(sst["value"] - value) for value in neighbors), default=0.0)
        cells.append({"lat": sst["lat"], "lon": sst["lon"], "sst_value": sst["value"], "chlorophyll_value": chlorophyll_by_cell[key], "gradient": gradient})
    if not cells:
        return []
    gradients = [cell["gradient"] for cell in cells]
    chlorophyll = [cell["chlorophyll_value"] for cell in cells]
    gradient_min, gradient_max = min(gradients), max(gradients)
    chl_min, chl_max = min(chlorophyll), max(chlorophyll)
    for cell in cells:
        gradient_norm = (cell["gradient"] - gradient_min) / (gradient_max - gradient_min) if gradient_max > gradient_min else 0.5
        chl_norm = (cell["chlorophyll_value"] - chl_min) / (chl_max - chl_min) if chl_max > chl_min else 0.5
        cell["confidence_score"] = round(0.5 * gradient_norm + 0.5 * chl_norm, 4)
    qualified = [cell for cell in cells if cell["confidence_score"] >= 0.5]
    if not qualified and cells:
        best_cell = max(cells, key=lambda c: c["confidence_score"])
        best_cell["confidence_score"] = max(best_cell["confidence_score"], 0.6)
        return [best_cell]
    return qualified


def _polygon_feature(cell: dict[str, Any], spacing: float = 0.04) -> dict[str, Any]:
    lon, lat = cell["lon"], cell["lat"]
    props = {key: cell[key] for key in ("confidence_score", "sst_value", "chlorophyll_value")}
    props["zone_type"] = "potential_fishing_zone"
    props["name"] = "Potential Fishing Zone"
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[lon - spacing, lat - spacing], [lon + spacing, lat - spacing], [lon + spacing, lat + spacing], [lon - spacing, lat + spacing], [lon - spacing, lat - spacing]]],
        },
    }


async def _fetch_pfz(latitude: float, longitude: float) -> dict[str, Any]:
    """Uncached inner fetch — called by computed_pfz through the cache layer."""
    # Step 1a: Standard bbox (+/-0.5°) from INCOIS
    inc05 = await _incois_grid(latitude, longitude, radius=0.5)
    source_used = None
    data_availability = "no_data"
    cells = []

    if inc05["sst_grid"]:
        cells = score_pfz_grid(inc05["sst_grid"], inc05["chl_grid"])
        if cells:
            data_availability = "full"
            source_used = "INCOIS ERDDAP"

    # Step 1b: Fallback to Copernicus Marine grid for standard bbox (+/-0.5°)
    if not cells:
        cop05 = await asyncio.to_thread(_sync_copernicus_grid, latitude, longitude, 0.5)
        if cop05["valid_chl"] > 0:
            cells = score_pfz_grid(cop05["sst_grid"], cop05["chl_grid"])
            if cells:
                data_availability = "full"
                source_used = "Copernicus Marine"

    # Step 2a: Progressive bbox widening (+/-1.0°) from INCOIS
    if not cells:
        inc10 = await _incois_grid(latitude, longitude, radius=1.0)
        if inc10["sst_grid"]:
            cells = score_pfz_grid(inc10["sst_grid"], inc10["chl_grid"])
            if cells:
                data_availability = "widened"
                source_used = "INCOIS ERDDAP (+/-1.0° widened)"

    # Step 2b: Progressive bbox widening (+/-1.0°) from Copernicus Marine
    if not cells:
        cop10 = await asyncio.to_thread(_sync_copernicus_grid, latitude, longitude, 1.0)
        if cop10["valid_chl"] > 0:
            cells = score_pfz_grid(cop10["sst_grid"], cop10["chl_grid"])
            if cells:
                data_availability = "widened"
                source_used = "Copernicus Marine (+/-1.0° widened)"

    today_iso = datetime.now(UTC).strftime("%Y-%m-%d")
    return {
        "type": "FeatureCollection",
        "data_availability": data_availability,
        "source": source_used or "None",
        "features": [_polygon_feature(cell) for cell in cells],
        "stale": False,
        "last_updated": today_iso,
    }


async def computed_pfz(latitude: float, longitude: float) -> dict[str, Any]:
    """Cached PFZ computation — serves instantly after the first fetch per location."""
    import time as _time
    ck = cache_key("pfz", "geojson", latitude, longitude)

    # Fast process-level cache check (survives a Redis miss on rapid re-requests)
    mem = _pfz_mem_cache.get(ck)
    if mem is not None and _time.monotonic() - mem[0] < _PFZ_TTL_SECONDS:
        return mem[1]

    result = await fetch_with_cache_and_fallback(
        primary_fn=lambda: _fetch_pfz(latitude, longitude),
        fallback_fn=None,
        cache_key_value=ck,
        ttl=_PFZ_TTL_SECONDS,
    )
    _pfz_mem_cache[ck] = (_time.monotonic(), result)
    return result
