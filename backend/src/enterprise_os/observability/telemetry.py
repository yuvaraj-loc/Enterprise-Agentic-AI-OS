"""Thread-safe in-memory metrics and privacy-preserving request audit logs."""

import logging
import math
from threading import Lock
from time import monotonic
from typing import Literal

logger = logging.getLogger(__name__)

TelemetryOutcome = Literal[
    "answered",
    "needs_sources",
    "safety_rejected",
    "rejected",
    "failed",
]
_OUTCOMES: tuple[TelemetryOutcome, ...] = (
    "answered",
    "needs_sources",
    "safety_rejected",
    "rejected",
    "failed",
)


class TelemetryError(RuntimeError):
    """Raised when request metrics cannot be safely updated or read."""


class LocalTelemetry:
    """Keep aggregate counters in memory without storing questions or answers."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._started_at = monotonic()
        self._counts = {outcome: 0 for outcome in _OUTCOMES}
        self._total_duration_ms = 0.0

    def record_request(
        self,
        request_id: str,
        outcome: TelemetryOutcome,
        intent: str,
        source_count: int,
        duration_ms: float,
    ) -> None:
        """Update aggregate counters and emit a log without prompt or answer text."""
        try:
            if outcome not in _OUTCOMES:
                raise ValueError("Unsupported telemetry outcome.")
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError("A request identifier is required for telemetry.")
            if intent not in {"general", "company_data", "unknown"}:
                raise ValueError("Unsupported telemetry intent.")
            if not isinstance(source_count, int) or source_count < 0:
                raise ValueError("Source count must be a non-negative integer.")
            if (
                not isinstance(duration_ms, (int, float))
                or not math.isfinite(float(duration_ms))
                or duration_ms < 0
            ):
                raise ValueError("Request duration must be a finite non-negative number.")

            with self._lock:
                self._counts[outcome] += 1
                self._total_duration_ms += float(duration_ms)
        except Exception as exc:
            raise TelemetryError("Request telemetry could not be recorded.") from exc

        self._safe_log_request(
            request_id=request_id,
            outcome=outcome,
            intent=intent,
            source_count=source_count,
            duration_ms=float(duration_ms),
        )

    def snapshot(self) -> dict[str, int | float]:
        """Return a locked snapshot of aggregate process-local counters."""
        try:
            with self._lock:
                counts = dict(self._counts)
                total_duration_ms = self._total_duration_ms
                uptime_seconds = max(0.0, monotonic() - self._started_at)

            total_requests = sum(counts.values())
            return {
                "uptime_seconds": round(uptime_seconds, 3),
                "total_requests": total_requests,
                "answered_requests": counts["answered"],
                "needs_sources_requests": counts["needs_sources"],
                "safety_rejections": counts["safety_rejected"],
                "rejected_requests": counts["rejected"],
                "failed_requests": counts["failed"],
                "average_duration_ms": round(
                    total_duration_ms / total_requests if total_requests else 0.0,
                    3,
                ),
            }
        except Exception as exc:
            raise TelemetryError("Request telemetry could not be read.") from exc

    @staticmethod
    def _safe_log_request(
        request_id: str,
        outcome: TelemetryOutcome,
        intent: str,
        source_count: int,
        duration_ms: float,
    ) -> None:
        """Write metadata-only logs and suppress logging-handler failures."""
        try:
            logger.info(
                "assistant_request request_id=%s outcome=%s intent=%s "
                "source_count=%d duration_ms=%.3f",
                request_id,
                outcome,
                intent,
                source_count,
                duration_ms,
            )
        except Exception:
            return None

    @staticmethod
    def report_failure(error: Exception) -> None:
        """Report telemetry failures without allowing logging to break a response."""
        try:
            logger.error("Request telemetry failed (%s).", type(error).__name__)
        except Exception:
            return None


telemetry = LocalTelemetry()
