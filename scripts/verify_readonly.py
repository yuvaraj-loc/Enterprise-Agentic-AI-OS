"""Verify that the application database connection rejects write statements."""

import sqlite3

from enterprise_os.config import get_settings
from enterprise_os.db.connection import (
    DatabaseNotInitializedError,
    DatabaseUnavailableError,
    open_readonly_database,
)


def main() -> int:
    """Attempt a no-op delete and require SQLite to reject the write."""
    settings = get_settings()
    try:
        with open_readonly_database(
            settings.database_path,
            settings.sqlite_timeout_seconds,
        ) as connection:
            connection.execute("DELETE FROM tickets WHERE ticket_id = ?", (-1,))
    except DatabaseNotInitializedError:
        print("Read-only check could not run: initialize the database first.")
        return 1
    except DatabaseUnavailableError as exc:
        cause = exc.__cause__
        if isinstance(cause, sqlite3.OperationalError) and "readonly" in str(cause).casefold():
            print("Read-only check passed: SQLite rejected the write statement.")
            return 0
        print(f"Read-only check failed: unexpected database error ({cause or exc}).")
        return 1

    print("Read-only check failed: the database accepted a write statement.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
