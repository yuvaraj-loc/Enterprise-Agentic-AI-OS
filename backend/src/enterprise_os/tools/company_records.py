"""Fixed-query, read-only tools for ticket and employee records."""

import logging
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from enterprise_os.config import Settings
from enterprise_os.db.connection import DatabaseError, open_readonly_database

logger = logging.getLogger(__name__)

MAX_RECORD_IDS_PER_KIND = 5
MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807

_TICKET_ID = re.compile(
    r"\btickets?\s*(?:(?:id|number|no\.?)\s*)?#?\s*(\d+)\b",
    re.IGNORECASE,
)
_EMPLOYEE_ID = re.compile(
    r"\bemployees?\s*(?:(?:id|number|no\.?)\s*)?#?\s*(\d+)\b",
    re.IGNORECASE,
)
_POLICY_TERMS = re.compile(
    r"\b(policy|policies|rule|rules|refund|return|violate|violation|eligible|"
    r"eligibility|exception|compliant|compliance)\b",
    re.IGNORECASE,
)
_EMAIL_REQUEST = re.compile(r"\b(email(?:\s+address)?|contact\s+details?)\b", re.IGNORECASE)
_TICKET_REFERENCE = re.compile(r"\btickets?\b", re.IGNORECASE)
_EMPLOYEE_REFERENCE = re.compile(r"\bemployees?\b", re.IGNORECASE)


class RecordRequestError(ValueError):
    """Raised when a question requests too many or invalid record identifiers."""


class CompanyToolError(RuntimeError):
    """Raised when a local read-only company record tool fails."""


def requires_policy_evidence(question: str) -> bool:
    """Return whether the user asks about a policy, rule, or compliance decision."""
    return bool(_POLICY_TERMS.search(question))


def _extract_ids(pattern: re.Pattern[str], question: str, entity: str) -> list[int]:
    """Extract explicit, bounded IDs associated with the requested entity name."""
    values: list[int] = []
    for match in pattern.finditer(question):
        raw_value = match.group(1)
        if len(raw_value) > 19:
            raise RecordRequestError(
                f"{entity.capitalize()} identifiers must fit within a signed 64-bit integer."
            )
        value = int(raw_value)
        if value <= 0 or value > MAX_SQLITE_INTEGER:
            raise RecordRequestError(f"{entity.capitalize()} identifiers must be positive integers.")
        if value not in values:
            values.append(value)
        if len(values) > MAX_RECORD_IDS_PER_KIND:
            raise RecordRequestError(
                f"A request may include at most {MAX_RECORD_IDS_PER_KIND} {entity} IDs."
            )
    return values


def _read_ticket(
    database_path: Path,
    timeout_seconds: float,
    ticket_id: int,
) -> dict[str, Any] | None:
    """Read only fields needed to explain a ticket or evaluate refund policy."""
    with open_readonly_database(database_path, timeout_seconds) as connection:
        row = connection.execute(
            """
            SELECT ticket_id, category, status, delivery_date, request_date,
                   item_condition, amount_cents, requested_refund_method, description
            FROM tickets
            WHERE ticket_id = ?
            """,
            (ticket_id,),
        ).fetchone()
    if row is None:
        return None

    record = dict(row)
    try:
        delivered = date.fromisoformat(str(record["delivery_date"]))
        requested = date.fromisoformat(str(record["request_date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CompanyToolError(
            f"Ticket {ticket_id} contains invalid dates and cannot be analyzed."
        ) from exc
    record["days_after_delivery"] = (requested - delivered).days
    return record


def _read_employee(
    database_path: Path,
    timeout_seconds: float,
    employee_id: int,
    include_email: bool,
) -> dict[str, Any] | None:
    """Read only requested employee fields through one of two fixed SELECT queries."""
    with open_readonly_database(database_path, timeout_seconds) as connection:
        if include_email:
            row = connection.execute(
                """
                SELECT employee_id, full_name, department, job_title, email
                FROM employees
                WHERE employee_id = ?
                """,
                (employee_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT employee_id, full_name, department, job_title
                FROM employees
                WHERE employee_id = ?
                """,
                (employee_id,),
            ).fetchone()
    return dict(row) if row is not None else None


def read_only_company_records(question: str, settings: Settings) -> dict[str, Any]:
    """Run the only supported record lookups using fixed, parameterized read queries."""
    if not isinstance(question, str) or not question.strip():
        raise RecordRequestError("A non-empty question is required to look up records.")

    ticket_ids = _extract_ids(_TICKET_ID, question, "ticket")
    employee_ids = _extract_ids(_EMPLOYEE_ID, question, "employee")
    include_email = bool(_EMAIL_REQUEST.search(question))
    unresolved_record_types: list[str] = []
    if not requires_policy_evidence(question):
        if _TICKET_REFERENCE.search(question) and not ticket_ids:
            unresolved_record_types.append("ticket")
        if _EMPLOYEE_REFERENCE.search(question) and not employee_ids:
            unresolved_record_types.append("employee")

    try:
        tickets: list[dict[str, Any]] = []
        for ticket_id in ticket_ids:
            record = _read_ticket(
                settings.database_path,
                settings.sqlite_timeout_seconds,
                ticket_id,
            )
            if record is not None:
                tickets.append(record)

        employees: list[dict[str, Any]] = []
        for employee_id in employee_ids:
            record = _read_employee(
                settings.database_path,
                settings.sqlite_timeout_seconds,
                employee_id,
                include_email,
            )
            if record is not None:
                employees.append(record)
    except CompanyToolError:
        raise
    except (DatabaseError, sqlite3.Error, OSError) as exc:
        logger.error("Read-only company record query failed (%s).", type(exc).__name__)
        raise CompanyToolError(
            "The local company records could not be read. Check the initialized SQLite database."
        ) from exc
    except Exception as exc:
        logger.error("Company records tool failed (%s).", type(exc).__name__)
        raise CompanyToolError("The company records tool failed. Please retry.") from exc

    found_ticket_ids = {int(record["ticket_id"]) for record in tickets}
    found_employee_ids = {int(record["employee_id"]) for record in employees}
    return {
        "tickets": tickets,
        "requested_ticket_ids": ticket_ids,
        "missing_ticket_ids": [item for item in ticket_ids if item not in found_ticket_ids],
        "employees": employees,
        "requested_employee_ids": employee_ids,
        "missing_employee_ids": [item for item in employee_ids if item not in found_employee_ids],
        "unresolved_record_types": unresolved_record_types,
    }
