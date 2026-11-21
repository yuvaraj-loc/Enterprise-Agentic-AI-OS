"""FastAPI application factory and ASGI application."""

import logging
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from enterprise_os import __version__
from enterprise_os.api.routes.assistant import router as assistant_router
from enterprise_os.api.routes.health import router as health_router
from enterprise_os.api.routes.records import router as records_router
from enterprise_os.config import PROJECT_ROOT, Settings, get_settings
from enterprise_os.db.connection import DatabaseError, verify_database_ready
from enterprise_os.graph.workflow import build_assistant_graph
from enterprise_os.llm.factory import ChatModelProvider

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Initialize the existing SQLite database and checkpointed assistant graph."""
    settings: Settings = get_settings()
    try:
        verify_database_ready(settings.database_path, settings.sqlite_timeout_seconds)
    except DatabaseError as exc:
        logger.warning(
            "Assistant graph disabled because the Milestone 1 database is unavailable (%s).",
            type(exc).__name__,
        )
        application.state.assistant_graph = None
        yield
        return

    try:
        async with AsyncSqliteSaver.from_conn_string(str(settings.database_path)) as checkpointer:
            await checkpointer.setup()
            application.state.assistant_graph = build_assistant_graph(
                settings,
                ChatModelProvider(settings),
                checkpointer,
            )
            yield
    except (sqlite3.Error, OSError) as exc:
        logger.error("Assistant checkpoint initialization failed (%s).", type(exc).__name__)
        raise RuntimeError("Assistant checkpoint storage could not be initialized.") from exc


def create_app() -> FastAPI:
    """Create the local single-user company operations assistant API."""
    application = FastAPI(
        title="Enterprise Agentic AI OS",
        description="Local single-user, read-only company operations assistant demo.",
        version=__version__,
        redoc_url=None,
        lifespan=lifespan,
    )

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def frontend_index() -> HTMLResponse:
        """Serve the self-contained local demo interface."""
        index_path = PROJECT_ROOT / "frontend" / "index.html"
        try:
            html = index_path.read_text(encoding="utf-8")
            return HTMLResponse(content=html)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="The local demo interface was not found.",
            ) from exc
        except (OSError, UnicodeError) as exc:
            raise HTTPException(
                status_code=500,
                detail="The local demo interface could not be read.",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="The local demo interface could not be served.",
            ) from exc

    application.include_router(health_router)
    application.include_router(records_router)
    application.include_router(assistant_router)
    return application


app = create_app()
