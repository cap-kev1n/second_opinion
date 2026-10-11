"""Health check route indicating application status without external dependencies."""

from fastapi import APIRouter
from config import settings
from models.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Application Health Check")
def get_health() -> HealthResponse:
    """Return application operational status.
    
    Verifies that the web service is responsive.
    Does NOT depend on external LLM connectivity or third-party APIs.
    """
    return HealthResponse(
        status="healthy",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
