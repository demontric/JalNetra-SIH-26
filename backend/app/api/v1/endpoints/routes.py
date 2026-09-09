from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.services.route_planner import RoutePlanningError, plan_route

router = APIRouter()


class RouteRequest(BaseModel):
    origin: Dict[str, float]  # {"lat": 9.28, "lon": 79.12}
    destination: Dict[str, float]  # {"lat": 9.45, "lon": 79.35}
    vessel_type: Optional[str] = "motorized_boat"


class RouteResponse(BaseModel):
    route_id: str
    distance_km: float
    estimated_time_mins: int
    hazard_notes: List[str]
    path_geojson: Dict[str, Any]


@router.post("/route", response_model=RouteResponse)
def calculate_safe_route(request: RouteRequest) -> RouteResponse:
    try:
        result = plan_route(request.origin, request.destination, request.vessel_type or "motorized_boat")
    except RoutePlanningError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RouteResponse(**result)
