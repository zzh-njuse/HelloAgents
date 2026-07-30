"""Stage 5 Slice 2A -- shared Provider Call recorder (Spec 003 / ADR 004).

A single recorder used by all five token-billing chains (Course generation,
Tutor, Practice generation, Practice grading, RAG Answer). Low-layer HTTP
helpers never guess owner; the orchestration that owns the DB session,
Workspace and business owner calls this recorder.

Contract highlights (Spec 003 S3, ADR 004 S3-4):

- Creates a ``started`` Provider Call in an INDEPENDENT short-lived
  transaction and COMMITS before the network request.
- Writes actual provider/model, owner, monotonic ordinal, stable phase,
  started_at.
- Selects the latest price snapshot with the same provider/model and
  effective_at <= started_at; keeps NULL if none found.
- Constraint or commit failure in the independent session prevents the
  provider call (caller must not proceed to the network request).
- On return: records succeeded, usage, latency, completed_at.
- On HTTP/provider/parse error: records failed.
- On explicit timeout: records timed_out.
- On explicit cancel: records canceled.
- Each finalize (succeed/fail/timeout/cancel) also uses an independent
  short-lived transaction and commits, so the fact survives business rollback.
- Saves only stable error codes, never exception bodies.
- Does NOT estimate missing usage or persist derived cost.
- The independent recorder Session never touches, closes, rolls back or
  commits the caller's business Session.
- ORM instances from the caller's Session are never passed to the independent
  Session; only stable IDs and whitelisted scalars cross the boundary.
- Exception finalization does NOT swallow the original business exception
  or disguise failure as success.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from learn_platform_api.db.models import ProviderCall, ProviderRateSnapshot
from learn_platform_api.db.session import SessionLocal


# --- Centralized phase allowlist (Spec 003 S6) --------------------------------
# Low-cardinality stable strings expressing call purpose. Never contains
# dynamic IDs, content, or exceptions.

COURSE_PHASES = frozenset({
    "plan",          # course architect search plan
    "generation",    # course outline / lesson draft generation
    "repair",        # artifact structure repair
})

TUTOR_PHASES = frozenset({
    "plan",          # teaching plan (skill or baseline)
    "answer",        # answer generation
    "repair",        # answer structure repair
})

PRACTICE_GENERATION_PHASES = frozenset({
    "plan",          # search plan
    "generation",    # practice set generation
    "repair",        # structure / novelty / specialized repair
})

PRACTICE_GRADING_PHASES = frozenset({
    "grading",       # rubric grading
    "repair",        # grading repair
})

RAG_ANSWER_PHASES = frozenset({
    "answer",        # RAG answer generation
    "repair",        # answer structure repair
})

ALL_PHASES = (
    COURSE_PHASES | TUTOR_PHASES | PRACTICE_GENERATION_PHASES
    | PRACTICE_GRADING_PHASES | RAG_ANSWER_PHASES
)


# --- Status constants ----------------------------------------------------------

STATUS_STARTED = "started"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_TIMED_OUT = "timed_out"
STATUS_CANCELED = "canceled"


# --- Stable error-code classification (Spec 003 S7) ----------------------------
# No substring matching on exception text. Each known business ValueError
# maps to a stable low-cardinality code. Unknown exceptions get a fixed
# generic code. Exception bodies are never persisted.

# Known stable error codes from business logic (low-cardinality, no dynamic content).
# These are the only codes that may appear in ProviderCall.error_code.
PROVIDER_UNAVAILABLE = "provider_unavailable"
PROVIDER_TIMEOUT = "provider_timeout"
GENERATION_CANCELED = "generation_canceled"
INVALID_MODEL_OUTPUT = "invalid_model_output"
PROVIDER_UNCONFIGURED = "provider_unconfigured"
UNKNOWN_ERROR = "unknown_error"

# Set of known stable business error codes (for validation; not exhaustive).
_STABLE_BUSINESS_CODES = frozenset({
    PROVIDER_UNAVAILABLE,
    PROVIDER_TIMEOUT,
    GENERATION_CANCELED,
    INVALID_MODEL_OUTPUT,
    PROVIDER_UNCONFIGURED,
    "generation_provider_unavailable",
    "generation_provider_unconfigured",
    "lesson_budget_exceeded",
    "practice_budget_exceeded",
    "practice_canceled",
    "grading_budget_exceeded",
    "agent_step_budget_exceeded",
    "source_snapshot_stale",
    "insufficient_evidence",
    "lesson_evidence_insufficient",
    "invalid_agent_artifact",
    "invalid_practice_artifact",
    "invalid_model_output",
    "invalid_formula_content",
    "invalid_learning_target",
    "unsupported_practice_item_type",
    "retrieval_unavailable",
})


def _walk_cause_chain(exc: Exception) -> Exception | None:
    """Walk __cause__ / __context__ to find a hidden httpx.TimeoutException.

    Stops at the first match and avoids cycles by tracking visited ids.
    Returns the TimeoutException if found, else None.
    """
    visited: set[int] = set()
    current: Exception | None = exc
    while current is not None:
        if id(current) in visited:
            return None
        visited.add(id(current))
        if isinstance(current, httpx.TimeoutException):
            return current
        # __cause__ (explicit `raise X from Y`) takes priority over __context__
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return None


def classify_error(exc: Exception) -> tuple[str, str]:
    """Classify an exception into (status, stable_error_code).

    Returns:
        (status, error_code) where status is one of the STATUS_* constants
        and error_code is a stable low-cardinality string.

    Classification rules (no substring guessing on exception text):
    1. httpx.TimeoutException (direct or chained via __cause__/__context__)
       -> (timed_out, provider_timeout)
    2. httpx.HTTPError (non-timeout) -> (failed, provider_unavailable)
    3. ValueError with a known stable cancellation message
       (generation_canceled, practice_canceled) -> (canceled, generation_canceled)
    4. ValueError with a known stable message -> (failed, that_message)
    5. Any other exception -> (failed, unknown_error)

    Budget-exceeded codes (lesson_budget_exceeded, practice_budget_exceeded,
    grading_budget_exceeded, agent_step_budget_exceeded) are NOT cancellation;
    they map to (failed, that_message) as known business failures.

    The exception body is never persisted; only the stable code is saved.
    """
    # Direct match
    if isinstance(exc, httpx.TimeoutException):
        return STATUS_TIMED_OUT, PROVIDER_TIMEOUT
    # Walk the cause chain for a hidden TimeoutException (e.g. ValueError
    # wrapping a timeout from a low-level HTTP helper).
    if _walk_cause_chain(exc) is not None:
        return STATUS_TIMED_OUT, PROVIDER_TIMEOUT
    if isinstance(exc, httpx.HTTPError):
        return STATUS_FAILED, PROVIDER_UNAVAILABLE
    if isinstance(exc, ValueError):
        msg = str(exc)
        # Only explicit stable cancellation codes -> canceled.
        # Budget-exceeded codes are NOT cancellation.
        if msg in ("generation_canceled", "practice_canceled"):
            return STATUS_CANCELED, GENERATION_CANCELED
        # Known stable business error codes -- use the message itself as the code
        if msg in _STABLE_BUSINESS_CODES:
            return STATUS_FAILED, msg
        # Fallback: unknown ValueError
        return STATUS_FAILED, UNKNOWN_ERROR
    # Any other exception type
    return STATUS_FAILED, UNKNOWN_ERROR


# --- Price snapshot selection (Spec 003 S5) ------------------------------------

def _select_rate_snapshot(
    db: Session,
    *,
    provider: str,
    model: str,
    started_at: datetime,
) -> str | None:
    """Find the latest price snapshot for the same provider/model whose
    effective_at is on or before started_at. Returns the snapshot ID or None."""
    row = db.scalar(
        select(ProviderRateSnapshot.id)
        .where(
            ProviderRateSnapshot.provider == provider,
            ProviderRateSnapshot.model == model,
            ProviderRateSnapshot.effective_at <= started_at,
        )
        .order_by(ProviderRateSnapshot.effective_at.desc())
        .limit(1)
    )
    return row  # None if no matching snapshot


# --- Ordinal allocation --------------------------------------------------------

def _next_ordinal(
    db: Session,
    *,
    workspace_id: str,
    agent_run_id: str | None,
    rag_answer_trace_id: str | None,
) -> int:
    """Allocate the next ordinal for the given owner.

    For AgentRun owner: max ordinal where agent_run_id matches.
    For RAG owner: max ordinal where rag_answer_trace_id matches.
    For workspace-only: max ordinal where both owners are NULL and workspace matches.
    Returns 0 if no prior calls exist for this owner.
    """
    if agent_run_id is not None:
        max_ord = db.scalar(
            select(func.coalesce(func.max(ProviderCall.ordinal), -1))
            .where(ProviderCall.agent_run_id == agent_run_id)
        )
    elif rag_answer_trace_id is not None:
        max_ord = db.scalar(
            select(func.coalesce(func.max(ProviderCall.ordinal), -1))
            .where(ProviderCall.rag_answer_trace_id == rag_answer_trace_id)
        )
    else:
        max_ord = db.scalar(
            select(func.coalesce(func.max(ProviderCall.ordinal), -1))
            .where(
                ProviderCall.workspace_id == workspace_id,
                ProviderCall.agent_run_id.is_(None),
                ProviderCall.rag_answer_trace_id.is_(None),
            )
        )
    return max(max_ord, -1) + 1


# --- Recorder ------------------------------------------------------------------

class ProviderCallRecorder:
    """Shared recorder for one provider request attempt.

    Per ADR 004: the recorder owns an independent short-lived Session
    for start and finalize operations. Each operation commits independently
    so the Provider Call fact survives business transaction rollback.

    The caller's business Session is never touched, closed, rolled back
    or committed by the recorder's independent Session.

    Usage in orchestration::

        recorder = ProviderCallRecorder(
            workspace_id=ws_id,
            agent_run_id=run.id,   # or rag_answer_trace_id=trace.id
            provider="deepseek",
            model="deepseek-v4-flash",
            phase="generation",
        )
        recorder.start()  # commits 'started' ProviderCall in independent tx

        try:
            result, usage = call_provider(settings, messages)
            recorder.succeed(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            )
        except httpx.TimeoutException:
            recorder.timeout()
            raise
        except Exception as exc:
            status, code = classify_error(exc)
            if status == STATUS_CANCELED:
                recorder.cancel(error_code=code)
            elif status == STATUS_TIMED_OUT:
                recorder.timeout()
            else:
                recorder.fail(error_code=code)
            raise

    The recorder never calls the provider itself; it only records the fact.
    """

    def __init__(
        self,
        *,
        workspace_id: str,
        provider: str,
        model: str,
        phase: str,
        agent_run_id: str | None = None,
        rag_answer_trace_id: str | None = None,
        _session_factory: Any = None,
    ) -> None:
        if phase not in ALL_PHASES:
            raise ValueError(f"unknown_provider_call_phase:{phase}")
        if agent_run_id is not None and rag_answer_trace_id is not None:
            raise ValueError("provider_call_double_owner")
        self._workspace_id = workspace_id
        self._agent_run_id = agent_run_id
        self._rag_answer_trace_id = rag_answer_trace_id
        self._provider = provider
        self._model = model
        self._phase = phase
        self._call_id: str | None = None
        self._started_perf: float = 0.0
        self._session_factory = _session_factory or SessionLocal

    def start(self) -> None:
        """Create a ``started`` ProviderCall in an independent transaction and commit.

        Raises on constraint failure (caller must NOT proceed to the
        network request).
        """
        started_at = datetime.now(timezone.utc)
        with self._session_factory() as ind_db:
            ordinal = _next_ordinal(
                ind_db,
                workspace_id=self._workspace_id,
                agent_run_id=self._agent_run_id,
                rag_answer_trace_id=self._rag_answer_trace_id,
            )
            snapshot_id = _select_rate_snapshot(
                ind_db,
                provider=self._provider,
                model=self._model,
                started_at=started_at,
            )
            pc = ProviderCall(
                workspace_id=self._workspace_id,
                agent_run_id=self._agent_run_id,
                rag_answer_trace_id=self._rag_answer_trace_id,
                ordinal=ordinal,
                phase=self._phase,
                provider=self._provider,
                model=self._model,
                status=STATUS_STARTED,
                started_at=started_at,
                provider_rate_snapshot_id=snapshot_id,
            )
            ind_db.add(pc)
            ind_db.commit()
            # After commit, pc.id is available (expire_on_commit=False).
            self._call_id = pc.id
        self._started_perf = time.perf_counter()

    def succeed(
        self,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Record a successful provider return in an independent transaction; commit."""
        if self._call_id is None:
            return
        now = datetime.now(timezone.utc)
        latency_ms = round((time.perf_counter() - self._started_perf) * 1000)
        with self._session_factory() as ind_db:
            pc = ind_db.get(ProviderCall, self._call_id)
            if pc is None:
                # Fix 2: recorder has a call_id but the record is gone —
                # must fail explicitly, not silently return (Spec 003 S7).
                raise RuntimeError("provider_call_finalize_missing")
            pc.status = STATUS_SUCCEEDED
            pc.input_tokens = input_tokens
            pc.output_tokens = output_tokens
            pc.latency_ms = latency_ms
            pc.completed_at = now
            ind_db.commit()

    def fail(self, *, error_code: str | None = None) -> None:
        """Record a provider/HTTP/parse error in an independent transaction; commit."""
        if self._call_id is None:
            return
        now = datetime.now(timezone.utc)
        latency_ms = round((time.perf_counter() - self._started_perf) * 1000)
        with self._session_factory() as ind_db:
            pc = ind_db.get(ProviderCall, self._call_id)
            if pc is None:
                raise RuntimeError("provider_call_finalize_missing")
            pc.status = STATUS_FAILED
            pc.error_code = error_code
            pc.latency_ms = latency_ms
            pc.completed_at = now
            ind_db.commit()

    def timeout(self) -> None:
        """Record an explicit timeout in an independent transaction; commit.

        Per OCR fix: always writes both status=timed_out and
        error_code=provider_timeout (Spec 003 S3.2, Spec 002 S2).
        """
        if self._call_id is None:
            return
        now = datetime.now(timezone.utc)
        latency_ms = round((time.perf_counter() - self._started_perf) * 1000)
        with self._session_factory() as ind_db:
            pc = ind_db.get(ProviderCall, self._call_id)
            if pc is None:
                raise RuntimeError("provider_call_finalize_missing")
            pc.status = STATUS_TIMED_OUT
            pc.error_code = PROVIDER_TIMEOUT
            pc.latency_ms = latency_ms
            pc.completed_at = now
            ind_db.commit()

    def cancel(self, *, error_code: str | None = None) -> None:
        """Record an explicit cancellation in an independent transaction; commit."""
        if self._call_id is None:
            return
        now = datetime.now(timezone.utc)
        latency_ms = round((time.perf_counter() - self._started_perf) * 1000)
        with self._session_factory() as ind_db:
            pc = ind_db.get(ProviderCall, self._call_id)
            if pc is None:
                raise RuntimeError("provider_call_finalize_missing")
            pc.status = STATUS_CANCELED
            pc.error_code = error_code
            pc.latency_ms = latency_ms
            pc.completed_at = now
            ind_db.commit()

    @property
    def call_id(self) -> str | None:
        """The ID of the started ProviderCall, or None if not yet started."""
        return self._call_id


# --- Convenience wrapper for the common pattern --------------------------------

def record_provider_call(
    db: Session,
    *,
    workspace_id: str,
    provider: str,
    model: str,
    phase: str,
    agent_run_id: str | None = None,
    rag_answer_trace_id: str | None = None,
    call_fn: Callable[[], tuple[Any, dict[str, Any]]],
    _session_factory: Any = None,
) -> tuple[Any, dict[str, Any]]:
    """Wrap a provider call with Provider Call recording.

    Creates a ``started`` fact in an independent transaction and commits,
    calls ``call_fn()``, then records the outcome using classify_error for stable
    error classification:

    - httpx.TimeoutException -> timed_out
    - Known cancellation ValueErrors -> canceled
    - Other ValueError / httpx.HTTPError -> failed with stable code
    - Unknown exceptions -> failed with ``unknown_error``

    Returns the (result, usage) from call_fn.
    Re-raises any exception after recording.

    The ``db`` parameter is the caller's business Session. It is NOT used
    by the recorder for writes; the recorder uses its own independent Session.
    It is accepted for API compatibility with existing callers.

    ``_session_factory`` is internal-only for test injection; production callers
    must not pass it.
    """
    # Auto-detect test session factory from the db session if available.
    effective_factory = _session_factory
    if effective_factory is None and hasattr(db, '_test_session_factory'):
        effective_factory = db._test_session_factory
    recorder = ProviderCallRecorder(
        workspace_id=workspace_id,
        provider=provider,
        model=model,
        phase=phase,
        agent_run_id=agent_run_id,
        rag_answer_trace_id=rag_answer_trace_id,
        _session_factory=effective_factory,
    )
    recorder.start()
    try:
        result, usage = call_fn()
        try:
            recorder.succeed(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            )
        except Exception as finalize_exc:
            # Fix 2: provider succeeded but finalization failed — must not
            # return the success result (Spec 003 S7). Raise with cause chain.
            raise RuntimeError("provider_call_finalize_failed") from finalize_exc
        return result, usage
    except Exception as exc:
        status, code = classify_error(exc)
        try:
            if status == STATUS_TIMED_OUT:
                recorder.timeout()
            elif status == STATUS_CANCELED:
                recorder.cancel(error_code=code)
            else:
                recorder.fail(error_code=code)
        except Exception as finalize_exc:
            # Fix 2: finalization failure must not swallow the original
            # business exception. Preserve the original as __cause__.
            # Do NOT persist exception bodies (Spec 003 S7).
            raise exc from finalize_exc
        raise
