"""Process liveness and local database readiness endpoints."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status

from enterprise_os.api.schemas import (
    AssistantMetricsResponse,
    AssistantReadinessResponse,
    HealthResponse,
)
from enterprise_os.config import PROJECT_ROOT, Settings, get_settings
from enterprise_os.db.connection import (
    DatabaseError,
    DatabaseNotInitializedError,
    DatabaseUnavailableError,
    verify_database_ready,
)
from enterprise_os.observability.telemetry import telemetry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get(
    "/health/live",
    response_model=HealthResponse,
    response_model_exclude_none=True,
)
def liveness() -> HealthResponse:
    """Report that the API process is accepting requests."""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
def readiness(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Report readiness only when the local Version 1 database is usable."""
    try:
        verify_database_ready(settings.database_path, settings.sqlite_timeout_seconds)
    except DatabaseNotInitializedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Local database is not initialized. Run "
                "`uv run --project backend python -m enterprise_os.db.bootstrap`."
            ),
        ) from exc
    except DatabaseUnavailableError as exc:
        logger.warning("Local database readiness check failed", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local database is unavailable.",
        ) from exc
    return HealthResponse(status="ok", database="ready")


def _provider_is_configured(settings: Settings) -> bool:
    """Check selected provider key and model presence without exposing either value."""
    if settings.llm_provider == "openai":
        api_key = settings.openai_api_key
        model = settings.openai_model
    else:
        api_key = settings.gemini_api_key
        model = settings.gemini_model
    return bool(
        api_key is not None
        and api_key.get_secret_value().strip()
        and model is not None
        and model.strip()
    )


@router.get("/health/assistant", response_model=AssistantReadinessResponse)
def assistant_readiness(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AssistantReadinessResponse:
    """Report local component readiness without making a provider API call."""
    try:
        database_status = "ready"
        try:
            verify_database_ready(settings.database_path, settings.sqlite_timeout_seconds)
        except DatabaseError:
            database_status = "unavailable"

        graph_status = (
            "ready"
            if getattr(request.app.state, "assistant_graph", None) is not None
            else "unavailable"
        )
        provider_configured = _provider_is_configured(settings)

        policy_directory = PROJECT_ROOT / "data" / "policies"
        try:
            policy_documents = (
                sum(1 for path in Path(policy_directory).glob("*.md") if path.is_file())
                if policy_directory.is_dir()
                else 0
            )
        except (OSError, RuntimeError):
            policy_documents = 0

        ready = (
            database_status == "ready"
            and graph_status == "ready"
            and provider_configured
            and policy_documents > 0
        )
        response = AssistantReadinessResponse(
            status="ready" if ready else "degraded",
            database=database_status,
            assistant_graph=graph_status,
            provider=settings.llm_provider,
            provider_configured=provider_configured,
            policy_documents=policy_documents,
        )
        if not ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=response.model_dump(),
            )
        return response
    except HTTPException:
        raise
    except Exception as exc:
        telemetry.report_failure(exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant readiness could not be determined.",
        ) from exc


@router.get("/health/metrics", response_model=AssistantMetricsResponse)
def assistant_metrics() -> AssistantMetricsResponse:
    """Return process-local aggregates without exposing prompts or answer text."""
    try:
        return AssistantMetricsResponse.model_validate(telemetry.snapshot())
    except Exception as exc:
        telemetry.report_failure(exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant metrics are temporarily unavailable.",
        ) from exc
