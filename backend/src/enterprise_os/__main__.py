"""Start the local API bound to loopback only."""

import uvicorn


def main() -> None:
    """Run the development API without exposing it to the local network."""
    uvicorn.run(
        "enterprise_os.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
