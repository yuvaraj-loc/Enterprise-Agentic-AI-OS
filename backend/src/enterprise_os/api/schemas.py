"""Explicit API response contracts."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Liveness and readiness response."""

    status: Literal["ok"]
    database: Literal["ready"] | None = None


class AssistantReadinessResponse(BaseModel):
    """Local component readiness without exposing credentials or local file paths."""

    status: Literal["ready", "degraded"]
    database: Literal["ready", "unavailable"]
    assistant_graph: Literal["ready", "unavailable"]
    provider: Literal["openai", "gemini"]
    provider_configured: bool
    policy_documents: int = Field(ge=0)


class AssistantMetricsResponse(BaseModel):
    """Process-local aggregate request counts and latency, with no prompt data."""

    uptime_seconds: float = Field(ge=0)
    total_requests: int = Field(ge=0)
    answered_requests: int = Field(ge=0)
    needs_sources_requests: int = Field(ge=0)
    safety_rejections: int = Field(ge=0)
    rejected_requests: int = Field(ge=0)
    failed_requests: int = Field(ge=0)
    average_duration_ms: float = Field(ge=0)


class EmployeeResponse(BaseModel):
    """Public fields returned for a mock employee lookup."""

    model_config = ConfigDict(extra="forbid")

    employee_id: int = Field(gt=0)
    full_name: str
    department: str
    job_title: str
    email: str


class TicketResponse(BaseModel):
    """Public fields returned for a mock ticket lookup."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int = Field(gt=0)
    assigned_employee_id: int | None
    customer_id: str
    order_id: str
    category: Literal["refund_request", "general", "shipping"]
    status: Literal["open", "in_progress", "resolved", "closed"]
    delivery_date: date
    request_date: date
    item_condition: str
    amount_cents: int = Field(ge=0)
    requested_refund_method: Literal["original_payment_method", "store_credit", "gift_card"]
    description: str
