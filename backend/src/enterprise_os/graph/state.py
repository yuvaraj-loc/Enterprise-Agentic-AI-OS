"""Typed state and provider-facing output schemas for the assistant graph."""

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

AssistantIntent = Literal["general", "company_data"]
AssistantStatus = Literal["answered", "needs_sources"]


class AssistantState(TypedDict, total=False):
    """State persisted by LangGraph during one independent question run."""

    question: str
    intent: AssistantIntent
    status: AssistantStatus
    answer: str
    company_evidence: str
    evidence_sufficient: bool
    evidence_gap_message: str
    sources: list[dict[str, str | None]]


class RoutePlan(BaseModel):
    """Model output used to choose the safe company assistant route."""

    model_config = ConfigDict(extra="forbid")

    intent: AssistantIntent = Field(
        description=(
            "Use general for questions answerable without this organization's private "
            "records or policies. Use company_data when internal sources are required."
        )
    )


class GeneralAnswer(BaseModel):
    """Structured answer for a general question with no company source dependency."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=8000)


class CompanyAnswer(BaseModel):
    """Answer grounded in the local policy and record evidence passed by the graph."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=8000)
