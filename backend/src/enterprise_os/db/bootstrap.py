"""Initialize and seed the local SQLite database."""

import json
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from enterprise_os.config import PROJECT_ROOT, get_settings
from enterprise_os.db.connection import SCHEMA_VERSION

logger = logging.getLogger(__name__)
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SEED_DIRECTORY = PROJECT_ROOT / "data" / "seed"
EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class EmployeeFixture(BaseModel):
    """Validated employee row loaded from the checked-in mock fixture."""

    model_config = ConfigDict(extra="forbid", strict=True)

    employee_id: int = Field(gt=0)
    full_name: str = Field(min_length=1, max_length=120)
    department: str = Field(min_length=1, max_length=120)
    job_title: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)

    @field_validator("full_name", "department", "job_title", "email", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class TicketFixture(BaseModel):
    """Validated ticket row loaded from the checked-in mock fixture."""

    model_config = ConfigDict(extra="forbid", strict=True)

    ticket_id: int = Field(gt=0)
    assigned_employee_id: int | None = Field(default=None, gt=0)
    customer_id: str = Field(min_length=1, max_length=64)
    order_id: str = Field(min_length=1, max_length=64)
    category: str = Field(pattern=r"^(refund_request|general|shipping)$")
    status: str = Field(pattern=r"^(open|in_progress|resolved|closed)$")
    delivery_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    request_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    item_condition: str = Field(min_length=1, max_length=500)
    amount_cents: int = Field(ge=0)
    requested_refund_method: str = Field(
        pattern=r"^(original_payment_method|store_credit|gift_card)$"
    )
    description: str = Field(min_length=1, max_length=1000)

    @field_validator(
        "customer_id",
        "order_id",
        "item_condition",
        "requested_refund_method",
        "description",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "TicketFixture":
        try:
            delivery_date = date.fromisoformat(self.delivery_date)
            request_date = date.fromisoformat(self.request_date)
        except ValueError as exc:
            raise ValueError("Ticket dates must be valid ISO calendar dates.") from exc
        if request_date < delivery_date:
            raise ValueError("request_date must be on or after delivery_date.")
        return self


class BootstrapError(RuntimeError):
    """Raised when schema setup or fixture loading fails."""


def _read_json_fixture(path: Path, adapter: TypeAdapter[Any]) -> list[Any]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BootstrapError(f"Unable to read required seed file: {path}") from exc

    try:
        result = adapter.validate_json(contents)
    except (ValidationError, ValueError) as exc:
        raise BootstrapError(f"Seed data is invalid in {path.name}: {exc}") from exc
    if not isinstance(result, list):
        raise BootstrapError(f"Seed file must contain a JSON array: {path.name}")
    return result


def _load_seed_data(seed_directory: Path) -> tuple[list[EmployeeFixture], list[TicketFixture]]:
    employees = _read_json_fixture(
        seed_directory / "employees.json",
        TypeAdapter(list[EmployeeFixture]),
    )
    tickets = _read_json_fixture(
        seed_directory / "tickets.json",
        TypeAdapter(list[TicketFixture]),
    )

    employee_ids = [employee.employee_id for employee in employees]
    ticket_ids = [ticket.ticket_id for ticket in tickets]
    employee_emails = [employee.email.casefold() for employee in employees]
    if len(set(employee_ids)) != len(employee_ids):
        raise BootstrapError("Employee seed data contains duplicate employee_id values.")
    if len(set(ticket_ids)) != len(ticket_ids):
        raise BootstrapError("Ticket seed data contains duplicate ticket_id values.")
    if len(set(employee_emails)) != len(employee_emails):
        raise BootstrapError("Employee seed data contains duplicate email values.")

    known_employee_ids = set(employee_ids)
    for ticket in tickets:
        if (
            ticket.assigned_employee_id is not None
            and ticket.assigned_employee_id not in known_employee_ids
        ):
            raise BootstrapError(
                f"Ticket {ticket.ticket_id} references an employee missing from the seed data."
            )
    return employees, tickets


def bootstrap_database(
    database_path: Path,
    seed_directory: Path = SEED_DIRECTORY,
    timeout_seconds: float = 5.0,
) -> tuple[int, int]:
    """Create or update the schema and upsert the checked-in demo records."""
    if not 0.0 < timeout_seconds <= 60.0:
        raise BootstrapError("SQLite timeout must be greater than 0 and no more than 60 seconds.")

    employees, tickets = _load_seed_data(seed_directory)

    try:
        path = Path(database_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    except (OSError, RuntimeError) as exc:
        raise BootstrapError("Unable to access the database directory or schema file.") from exc

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, timeout=timeout_seconds)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version > SCHEMA_VERSION:
            raise BootstrapError(
                f"Database schema version {current_version} is newer than supported "
                f"version {SCHEMA_VERSION}."
            )

        connection.executescript(schema_sql)
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            """
            INSERT INTO employees (employee_id, full_name, department, job_title, email)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(employee_id) DO UPDATE SET
                full_name = excluded.full_name,
                department = excluded.department,
                job_title = excluded.job_title,
                email = excluded.email
            """,
            [
                (
                    employee.employee_id,
                    employee.full_name,
                    employee.department,
                    employee.job_title,
                    employee.email,
                )
                for employee in employees
            ],
        )
        connection.executemany(
            """
            INSERT INTO tickets (
                ticket_id, assigned_employee_id, customer_id, order_id, category,
                status, delivery_date, request_date, item_condition, amount_cents,
                requested_refund_method, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                assigned_employee_id = excluded.assigned_employee_id,
                customer_id = excluded.customer_id,
                order_id = excluded.order_id,
                category = excluded.category,
                status = excluded.status,
                delivery_date = excluded.delivery_date,
                request_date = excluded.request_date,
                item_condition = excluded.item_condition,
                amount_cents = excluded.amount_cents,
                requested_refund_method = excluded.requested_refund_method,
                description = excluded.description
            """,
            [
                (
                    ticket.ticket_id,
                    ticket.assigned_employee_id,
                    ticket.customer_id,
                    ticket.order_id,
                    ticket.category,
                    ticket.status,
                    ticket.delivery_date,
                    ticket.request_date,
                    ticket.item_condition,
                    ticket.amount_cents,
                    ticket.requested_refund_method,
                    ticket.description,
                )
                for ticket in tickets
            ],
        )

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise BootstrapError("Seed data violates a SQLite foreign-key constraint.")

        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except BootstrapError:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        raise
    except (sqlite3.Error, OSError) as exc:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        raise BootstrapError("Unable to initialize or seed the local SQLite database.") from exc
    finally:
        if connection is not None:
            connection.close()

    return len(employees), len(tickets)


def main() -> int:
    """CLI entry point used for local database bootstrap."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    settings = get_settings()
    try:
        employee_count, ticket_count = bootstrap_database(
            settings.database_path,
            timeout_seconds=settings.sqlite_timeout_seconds,
        )
    except BootstrapError:
        logger.exception("Database bootstrap failed")
        return 1

    print(
        f"Initialized {settings.database_path} "
        f"with {employee_count} employees and {ticket_count} tickets."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
