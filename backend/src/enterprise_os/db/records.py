"""Fixed read-only queries for mock company records."""

from pathlib import Path
from typing import Any

from enterprise_os.db.connection import open_readonly_database


def get_ticket(
    database_path: Path,
    timeout_seconds: float,
    ticket_id: int,
) -> dict[str, Any] | None:
    """Return one ticket using a fixed parameterized SELECT statement."""
    with open_readonly_database(database_path, timeout_seconds) as connection:
        row = connection.execute(
            """
            SELECT ticket_id, assigned_employee_id, customer_id, order_id, category,
                   status, delivery_date, request_date, item_condition, amount_cents,
                   requested_refund_method, description
            FROM tickets
            WHERE ticket_id = ?
            """,
            (ticket_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def get_employee(
    database_path: Path,
    timeout_seconds: float,
    employee_id: int,
) -> dict[str, Any] | None:
    """Return one employee using a fixed parameterized SELECT statement."""
    with open_readonly_database(database_path, timeout_seconds) as connection:
        row = connection.execute(
            """
            SELECT employee_id, full_name, department, job_title, email
            FROM employees
            WHERE employee_id = ?
            """,
            (employee_id,),
        ).fetchone()
    return dict(row) if row is not None else None
