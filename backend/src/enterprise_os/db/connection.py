"""Read-only SQLite connections used by the API."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1


class DatabaseError(RuntimeError):
    """Base class for expected local database errors."""


class DatabaseNotInitializedError(DatabaseError):
    """Raised when the local database has not been bootstrapped."""


class DatabaseUnavailableError(DatabaseError):
    """Raised when the initialized local database cannot be read."""


@contextmanager
def open_readonly_database(
    database_path: Path,
    timeout_seconds: float,
) -> Iterator[sqlite3.Connection]:
    """Open an existing SQLite file in read-only mode and close it reliably."""
    path = Path(database_path)
    if not path.is_file():
        raise DatabaseNotInitializedError("Local database file does not exist.")

    connection: sqlite3.Connection | None = None
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=timeout_seconds,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError("The local SQLite database could not be read.") from exc
    finally:
        if connection is not None:
            connection.close()


def verify_database_ready(database_path: Path, timeout_seconds: float) -> None:
    """Raise a typed error unless the expected Version 1 schema is available."""
    with open_readonly_database(database_path, timeout_seconds) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            raise DatabaseNotInitializedError(
                "Local database schema is missing or has an unsupported version."
            )

        required_columns = {
            "employees": {"employee_id", "full_name", "department", "job_title", "email"},
            "tickets": {
                "ticket_id",
                "assigned_employee_id",
                "customer_id",
                "order_id",
                "category",
                "status",
                "delivery_date",
                "request_date",
                "item_condition",
                "amount_cents",
                "requested_refund_method",
                "description",
            },
        }
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        existing_tables = {str(row[0]) for row in rows}
        for table_name, expected_columns in required_columns.items():
            if table_name not in existing_tables:
                raise DatabaseNotInitializedError(
                    "Local database is missing required Version 1 tables."
                )
            actual_columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            if not expected_columns.issubset(actual_columns):
                raise DatabaseNotInitializedError(
                    f"Local database table {table_name} is missing required columns."
                )
