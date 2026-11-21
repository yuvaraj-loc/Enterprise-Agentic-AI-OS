"""Read-only mock employee and ticket endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from enterprise_os.api.schemas import EmployeeResponse, TicketResponse
from enterprise_os.config import Settings, get_settings
from enterprise_os.db.connection import DatabaseError, DatabaseNotInitializedError
from enterprise_os.db.records import get_employee, get_ticket

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["mock company records"])
PositiveRecordId = Annotated[int, Path(gt=0, le=9_223_372_036_854_775_807)]


def _database_unavailable(exc: DatabaseError) -> HTTPException:
    if isinstance(exc, DatabaseNotInitializedError):
        detail = (
            "Local database is not initialized. Run "
            "`uv run --project backend python -m enterprise_os.db.bootstrap`."
        )
    else:
        logger.warning("Read-only company record query failed", exc_info=exc)
        detail = "Local database is unavailable."
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
def read_ticket(
    ticket_id: PositiveRecordId,
    settings: Settings = Depends(get_settings),
) -> TicketResponse:
    """Return a mock ticket using a fixed parameterized SELECT query."""
    try:
        record = get_ticket(settings.database_path, settings.sqlite_timeout_seconds, ticket_id)
    except DatabaseError as exc:
        raise _database_unavailable(exc) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket {ticket_id} was not found.",
        )
    return TicketResponse.model_validate(record)


@router.get("/employees/{employee_id}", response_model=EmployeeResponse)
def read_employee(
    employee_id: PositiveRecordId,
    settings: Settings = Depends(get_settings),
) -> EmployeeResponse:
    """Return a mock employee using a fixed parameterized SELECT query."""
    try:
        record = get_employee(
            settings.database_path,
            settings.sqlite_timeout_seconds,
            employee_id,
        )
    except DatabaseError as exc:
        raise _database_unavailable(exc) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee {employee_id} was not found.",
        )
    return EmployeeResponse.model_validate(record)
