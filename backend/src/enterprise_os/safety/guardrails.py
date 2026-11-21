"""Dependency-free input, evidence, and answer checks for the local assistant."""

import logging
import re
from collections.abc import Sequence

logger = logging.getLogger(__name__)

_PROMPT_OVERRIDE_PATTERNS = (
    re.compile(
        r"\bignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+"
        r"(?:system\s+|developer\s+)?instructions?\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\bdisregard\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+instructions?\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:reveal|show|print|repeat|quote|display|dump)\b.{0,80}\b"
        r"(?:system|developer|hidden)\s+(?:prompt|instructions?|message)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"\b(?:jailbreak|do\s+anything\s+now)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:disable|bypass|override)\b.{0,60}\b"
        r"(?:safety|guardrails?|restrictions?|policy)\b",
        re.IGNORECASE | re.DOTALL,
    ),
)

_SENSITIVE_TERMS = (
    r"passwords?|passwd|credentials?|api\s+keys?|authentication\s+tokens?|"
    r"access\s+tokens?|government\s+ids?|social\s+security\s+numbers?|ssn|"
    r"bank(?:ing)?\s+(?:account\s+)?details?|bank\s+accounts?|routing\s+numbers?|"
    r"credit\s+card\s+numbers?|"
    r"private\s+medical\s+(?:records?|information)|medical\s+records?|diagnoses"
)
_SENSITIVE_DISCLOSURE_PATTERNS = (
    re.compile(
        rf"\b(?:show|give|provide|retrieve|reveal|display|expose|dump|list|return|print|send)"
        rf"\b.{{0,80}}\b(?:{_SENSITIVE_TERMS})\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"\bwhat(?:\s+is|'s)\s+(?:my|your|the|their|an?\s+)?"
        rf"(?:{_SENSITIVE_TERMS})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_SENSITIVE_TERMS})\b.{{0,60}}\b(?:of|for)\s+"
        r"(?:employee|customer|user|person|account)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"\b(?:employee|customer|user|person|account)(?:'s|’s)\s+"
        rf"(?:{_SENSITIVE_TERMS})\b",
        re.IGNORECASE,
    ),
)

_MUTATING_ACTION_PATTERN = re.compile(
    r"(?:^\s*(?:please\s+)?|\b(?:please|can you|could you|would you|i want you to|"
    r"go ahead and|now)\s+)"
    r"(?:create|insert|update|modify|change|delete|remove|drop|alter|write|approve|"
    r"issue|process|execute|cancel|refund|send)\b"
    r".{0,100}\b(?:ticket|employee|record|database|order|refund|payment|account|"
    r"policy|company)\b",
    re.IGNORECASE | re.DOTALL,
)

_SECRET_VALUE_PATTERNS = (
    re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{30,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:password|passwd|api[_ -]?key|access[_ -]?token|auth(?:entication)?[_ -]?token|secret)"
        r"\s*[:=]\s*[^\s,;]{8,}",
        re.IGNORECASE,
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?!000|666|9\d{2})\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:bank|routing|account)\s+(?:account\s+)?(?:number|no\.?)\s*"
        r"(?:is\s+|[:=]\s*)?\d{8,18}\b",
        re.IGNORECASE,
    ),
)


class InputGuardrailError(ValueError):
    """Raised when a user request is unsafe or outside read-only scope."""


class EvidenceGuardrailError(RuntimeError):
    """Raised when retrieved local evidence contains an instruction override."""


class OutputGuardrailError(RuntimeError):
    """Raised when an answer fails sensitivity or evidence checks."""


class SafetyCheckError(RuntimeError):
    """Raised when a guardrail itself fails and the request must fail closed."""


def _contains_prompt_override(text: str) -> bool:
    """Check for common instruction-override and hidden-prompt extraction patterns."""
    return any(pattern.search(text) is not None for pattern in _PROMPT_OVERRIDE_PATTERNS)


def check_user_input(question: str) -> None:
    """Reject prompt overrides, sensitive-data disclosure, and write-action requests."""
    try:
        if not isinstance(question, str) or not question.strip():
            raise InputGuardrailError("A non-empty question is required.")
        if _contains_prompt_override(question):
            raise InputGuardrailError(
                "This request contains instruction-override content and cannot be processed."
            )
        if any(pattern.search(question) is not None for pattern in _SENSITIVE_DISCLOSURE_PATTERNS):
            raise InputGuardrailError(
                "The assistant cannot disclose credentials, government identifiers, banking details, "
                "or private medical information."
            )
        if _MUTATING_ACTION_PATTERN.search(question):
            raise InputGuardrailError(
                "This assistant is read-only and cannot make or initiate company record changes."
            )
    except InputGuardrailError:
        raise
    except Exception as exc:
        logger.error("Input safety check failed (%s).", type(exc).__name__)
        raise SafetyCheckError("The input safety check could not complete safely.") from exc


def check_retrieved_evidence(evidence: str) -> None:
    """Reject retrieved documents or records that contain prompt override instructions."""
    try:
        if not isinstance(evidence, str):
            raise EvidenceGuardrailError("Retrieved evidence is not valid text.")
        if _contains_prompt_override(evidence):
            logger.warning("Retrieved evidence failed the instruction-override check.")
            raise EvidenceGuardrailError(
                "A local source did not pass the assistant safety check."
            )
    except EvidenceGuardrailError:
        raise
    except Exception as exc:
        logger.error("Evidence safety check failed (%s).", type(exc).__name__)
        raise SafetyCheckError("The evidence safety check could not complete safely.") from exc


def check_assistant_output(
    answer: str,
    intent: str,
    response_status: str,
    sources: Sequence[object],
) -> None:
    """Reject leaked secrets and company answers that lack a source reference."""
    try:
        if not isinstance(answer, str) or not answer.strip():
            raise OutputGuardrailError("The assistant produced an empty response.")
        if intent == "company_data" and response_status == "answered" and not sources:
            raise OutputGuardrailError(
                "A company-specific answer did not include supporting sources."
            )
        if _contains_prompt_override(answer):
            logger.warning("Assistant output contained instruction-override content.")
            raise OutputGuardrailError(
                "The assistant response failed an instruction-safety check."
            )
        if any(pattern.search(answer) is not None for pattern in _SECRET_VALUE_PATTERNS):
            logger.warning("Assistant output failed the sensitive-value check.")
            raise OutputGuardrailError(
                "The assistant response failed a sensitive-information safety check."
            )
    except OutputGuardrailError:
        raise
    except Exception as exc:
        logger.error("Output safety check failed (%s).", type(exc).__name__)
        raise SafetyCheckError("The output safety check could not complete safely.") from exc
