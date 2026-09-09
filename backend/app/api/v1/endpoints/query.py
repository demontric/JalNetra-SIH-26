from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class QueryRequest(BaseModel):
    query: str
    language: str = "en-IN"
    user_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@router.post("/query")
async def process_user_query(request: QueryRequest):
    """Use the canonical graph route; FastAPI runs this sync handler off-loop."""
    from main import run_query

    return await run_query(request.query, request.language, request.latitude, request.longitude)
