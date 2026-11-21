"""HTTP endpoint for the checkpointed company operations assistant."""

import logging
import sqlite3
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from enterprise_os.api.assistant_schemas import AskRequest, AskResponse
from enterprise_os.rag.policy_search import PolicySearchError
from enterprise_os.observability.telemetry import telemetry
from enterprise_os.safety.guardrails import (
    EvidenceGuardrailError,
    InputGuardrailError,
    OutputGuardrailError,
    SafetyCheckError,
    check_assistant_output,
    check_user_input,
)
from enterprise_os.tools.company_records import CompanyToolError, RecordRequestError
from enterprise_os.llm.factory import LLMCallError, LLMConfigurationError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["assistant"])


@router.post("/ask", response_model=AskResponse)
async def ask_assistant(payload: AskRequest, request: Request) -> AskResponse:
    """Route one question and return a structured answer or a source-needed result."""
    request_id = uuid4()
    started_at = perf_counter()
    outcome = "failed"
    intent_for_log = "unknown"
    source_count = 0
    try:
        graph = getattr(request.app.state, "assistant_graph", None)
        if graph is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The assistant workflow is not available.",
            )
        check_user_input(payload.question)
        state = await graph.ainvoke(
            {"question": payload.question},
            config={
                "configurable": {"thread_id": str(request_id)},
                "recursion_limit": 4,
            },
        )
        response = AskResponse(
            request_id=request_id,
            intent=state["intent"],
            status=state["status"],
            answer=state["answer"],
            sources=state.get("sources", []),
        )
        check_assistant_output(
            response.answer,
            response.intent,
            response.status,
            response.sources,
        )
        outcome = response.status
        intent_for_log = response.intent
        source_count = len(response.sources)
        return response
    except HTTPException:
        outcome = "failed"
        raise
    except InputGuardrailError as exc:
        outcome = "safety_rejected"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except EvidenceGuardrailError as exc:
        outcome = "safety_rejected"
        logger.warning("Retrieved evidence failed a safety check (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A local source did not pass the assistant safety check.",
        ) from exc
    except OutputGuardrailError as exc:
        outcome = "safety_rejected"
        logger.warning("Assistant response failed a safety check (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant response failed a safety check. Please retry.",
        ) from exc
    except SafetyCheckError as exc:
        logger.error("A safety guardrail could not complete (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A required assistant safety check could not complete.",
        ) from exc
    except RecordRequestError as exc:
        outcome = "rejected"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (PolicySearchError, CompanyToolError) as exc:
        logger.error("Assistant company source tool failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LLMCallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except sqlite3.Error as exc:
        logger.error("Assistant checkpoint operation failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant state storage is unavailable. Please retry.",
        ) from exc
    except ValidationError as exc:
        logger.warning("Assistant produced an invalid API response (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant returned an invalid response. Please retry.",
        ) from exc
    except (KeyError, TypeError) as exc:
        logger.error("Assistant workflow returned incomplete state (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant returned an incomplete response. Please retry.",
        ) from exc
    except Exception as exc:
        logger.error(
            "Assistant workflow failed for request %s (%s).",
            request_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The assistant could not complete this request. Please retry.",
        ) from exc
    finally:
        try:
            telemetry.record_request(
                request_id=str(request_id),
                outcome=outcome,
                intent=intent_for_log,
                source_count=source_count,
                duration_ms=(perf_counter() - started_at) * 1_000,
            )
        except Exception as exc:
            telemetry.report_failure(exc)
