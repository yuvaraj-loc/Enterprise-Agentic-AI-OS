"""Request and response contracts for the assistant endpoint."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    """One independent question submitted to the assistant."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(strict=True, min_length=3, max_length=3000)


class AskSource(BaseModel):
    """One local policy excerpt or company record used to ground an answer."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["policy", "ticket", "employee"]
    reference: str = Field(min_length=1, max_length=260)
    title: str = Field(min_length=1, max_length=200)
    section: str | None = Field(default=None, max_length=200)


class AskResponse(BaseModel):
    """Structured result of one independent graph run."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    intent: Literal["general", "company_data"]
    status: Literal["answered", "needs_sources"]
    answer: str = Field(min_length=1, max_length=8000)
    sources: list[AskSource] = Field(default_factory=list, max_length=20)
