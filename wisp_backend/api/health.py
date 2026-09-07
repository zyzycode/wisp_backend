from fastapi import APIRouter

from wisp_backend.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse()
