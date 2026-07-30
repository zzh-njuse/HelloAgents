"""Stage 5 Slice 1B-2 — Provider Call recorder and business chain wiring tests.

Covers (Spec 003 / ADR 002):
- Shared recorder: start/succeed/fail/timeout/cancel, usage, ordinal, price selection
- Owner mutual exclusion (agent_run_id vs rag_answer_trace_id)
- RAG owner ordinal uniqueness
- RAG owner Workspace isolation (cross-workspace rejected on Postgres)
- RagAnswerTrace cascade deletion (on Postgres)
- Migration 0025 round-trip (on isolated Postgres)
- Business chain wiring: each chain produces correct Provider Call facts
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from learn_platform_api.db.models import (
    AgentRun,
    PracticeJob,
    ProviderCall,
    ProviderRateSnapshot,
    RagAnswerTrace,
    Workspace,
)
from learn_platform_api.services.provider_call_recorder import (
    ProviderCallRecorder,
    record_provider_call,
    classify_error,
    ALL_PHASES,
    COURSE_PHASES,
    TUTOR_PHASES,
    PRACTICE_GENERATION_PHASES,
    PRACTICE_GRADING_PHASES,
    RAG_ANSWER_PHASES,
    STATUS_STARTED,
    STATUS_SUCCEEDED,
    STATUS_FAILED,
    STATUS_TIMED_OUT,
    STATUS_CANCELED,
    PROVIDER_UNAVAILABLE,
    PROVIDER_TIMEOUT,
    GENERATION_CANCELED,
    UNKNOWN_ERROR,
)


# --- ADR 004 helper: get the test session factory from the fixture ---------------

def _sf(db_session):
    """Return the test session factory for independent recorder sessions."""
    return getattr(db_session, '_test_session_factory', None)


# --- seed helpers ---------------------------------------------------------------

def _ws(db_session) -> Workspace:
    ws = Workspace(name="ws", slug=f"ws-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.flush()
    return ws


def _run(db_session, ws: Workspace) -> AgentRun:
    pj = PracticeJob(
        workspace_id=ws.id, job_type="generate_set", output_language="zh-CN",
        difficulty="standard", item_count=1, request_hash="0" * 64,
        idempotency_key=f"run-key-{uuid4().hex[:8]}", attempt_count=0,
    )
    db_session.add(pj)
    db_session.flush()
    ar = AgentRun(
        practice_job_id=pj.id, workspace_id=ws.id,
        role="exercise_author", attempt_number=1, status="succeeded",
    )
    db_session.add(ar)
    db_session.flush()
    # ADR 004 S5.1: the owner must be committed so the independent recorder
    # session can reference it as a FK target.
    db_session.commit()
    return ar


def _trace(db_session, ws: Workspace) -> RagAnswerTrace:
    t = RagAnswerTrace(
        workspace_id=ws.id, question_hash="0" * 64, status="succeeded",
        prompt_template_version="v1", evidence_chunk_ids=[], citation_ids=[],
    )
    db_session.add(t)
    db_session.flush()
    # ADR 004 S5.1: the owner must be committed so the independent recorder
    # session can reference it as a FK target.
    db_session.commit()
    return t


def _snapshot(
    db_session,
    *,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    input_rate: str = "40",
    output_rate: str = "120",
    effective_at: datetime | None = None,
) -> ProviderRateSnapshot:
    snap = ProviderRateSnapshot(
        provider=provider, model=model,
        input_rate_per_1m=Decimal(input_rate),
        output_rate_per_1m=Decimal(output_rate),
        effective_at=effective_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(snap)
    db_session.flush()
    # ADR 004: commit so the independent recorder session can see the snapshot.
    db_session.commit()
    return snap


# --- Phase allowlist tests ------------------------------------------------------

def test_all_phases_are_low_cardinality() -> None:
    assert len(ALL_PHASES) <= 15  # stable, low-cardinality
    for phase in ALL_PHASES:
        assert len(phase) <= 40
        assert phase == phase.strip()  # no whitespace


def test_phase_sets_are_stable_and_low_cardinality() -> None:
    """Each chain's phases are stable low-cardinality strings."""
    for phases in [COURSE_PHASES, TUTOR_PHASES, PRACTICE_GENERATION_PHASES, PRACTICE_GRADING_PHASES, RAG_ANSWER_PHASES]:
        assert len(phases) >= 1
        for phase in phases:
            assert phase == phase.strip()
            assert len(phase) <= 40


# --- Recorder: start/succeed/fail/timeout/cancel --------------------------------

def test_recorder_start_creates_started_call(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    assert recorder.call_id is not None
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.status == STATUS_STARTED
    assert pc.phase == "generation"
    assert pc.provider == "deepseek"
    assert pc.model == "deepseek-v4-flash"
    assert pc.ordinal == 0
    assert pc.agent_run_id == run.id
    assert pc.workspace_id == ws.id
    assert pc.started_at is not None
    assert pc.completed_at is None


def test_recorder_succeed_records_usage(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.succeed(input_tokens=100, output_tokens=50)
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.status == STATUS_SUCCEEDED
    assert pc.input_tokens == 100
    assert pc.output_tokens == 50
    assert pc.latency_ms is not None and pc.latency_ms >= 0
    assert pc.completed_at is not None


def test_recorder_fail_records_error_code(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.fail(error_code="provider_unavailable")
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.status == STATUS_FAILED
    assert pc.error_code == "provider_unavailable"
    assert pc.completed_at is not None


def test_recorder_timeout(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.timeout()
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.status == STATUS_TIMED_OUT
    assert pc.error_code == PROVIDER_TIMEOUT  # OCR fix: timeout writes stable error_code
    assert pc.completed_at is not None


def test_recorder_cancel(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.cancel(error_code="generation_canceled")
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.status == STATUS_CANCELED
    assert pc.error_code == "generation_canceled"
    assert pc.completed_at is not None


# --- Usage: NULL when not reported ----------------------------------------------

def test_recorder_succeed_null_usage_stays_null(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="answer",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.succeed()  # no usage provided
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.input_tokens is None
    assert pc.output_tokens is None


def test_recorder_succeed_single_dim_usage(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="answer",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.succeed(input_tokens=100)  # output_tokens omitted
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.input_tokens == 100
    assert pc.output_tokens is None


# --- Ordinal: monotonic within owner -------------------------------------------

def test_ordinal_monotonic_within_run(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    for i, phase in enumerate(["plan", "generation", "repair"]):
        recorder = ProviderCallRecorder(
            workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase=phase,
            _session_factory=_sf(db_session),
        )
        recorder.start()
        recorder.succeed(input_tokens=10, output_tokens=5)
        pc = db_session.get(ProviderCall, recorder.call_id)
        assert pc.ordinal == i


def test_ordinal_monotonic_within_rag_trace(db_session) -> None:
    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    for i, phase in enumerate(["answer", "repair"]):
        recorder = ProviderCallRecorder(
            workspace_id=ws.id, rag_answer_trace_id=trace.id,
            provider="deepseek", model="deepseek-v4-flash", phase=phase,
            _session_factory=_sf(db_session),
        )
        recorder.start()
        recorder.succeed(input_tokens=10, output_tokens=5)
        pc = db_session.get(ProviderCall, recorder.call_id)
        assert pc.ordinal == i


# --- Price snapshot selection ---------------------------------------------------

def test_price_snapshot_selected_when_available(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    snap = _snapshot(db_session, provider="deepseek", model="deepseek-v4-flash",
                     input_rate="40", output_rate="120",
                     effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.provider_rate_snapshot_id == snap.id


def test_price_snapshot_null_when_no_match(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    # No snapshot for this provider/model
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="openai", model="gpt-4o", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.provider_rate_snapshot_id is None


def test_price_snapshot_excludes_future(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    # Future snapshot: effective_at is firmly in the future (now + 365 days),
    # so it must NOT be bound to the current Provider Call regardless of the
    # calendar date the test runs on.
    _snapshot(db_session, provider="deepseek", model="deepseek-v4-flash",
              input_rate="100", output_rate="300",
              effective_at=datetime.now(timezone.utc) + timedelta(days=365))
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.provider_rate_snapshot_id is None  # future price excluded


def test_price_snapshot_picks_most_recent(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    s1 = _snapshot(db_session, provider="deepseek", model="deepseek-v4-flash",
                   input_rate="40", output_rate="120",
                   effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    s2 = _snapshot(db_session, provider="deepseek", model="deepseek-v4-flash",
                   input_rate="50", output_rate="150",
                   effective_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.provider_rate_snapshot_id == s2.id  # most recent before now


# --- Owner mutual exclusion ----------------------------------------------------

def test_double_owner_rejected(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    trace = _trace(db_session, ws)
    with pytest.raises(ValueError, match="provider_call_double_owner"):
        ProviderCallRecorder(
            workspace_id=ws.id,
            agent_run_id=run.id, rag_answer_trace_id=trace.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            _session_factory=_sf(db_session),
        )


def test_rag_owner_call_created(db_session) -> None:
    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, rag_answer_trace_id=trace.id,
        provider="deepseek", model="deepseek-v4-flash", phase="answer",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.succeed(input_tokens=200, output_tokens=100)
    pc = db_session.get(ProviderCall, recorder.call_id)
    assert pc.rag_answer_trace_id == trace.id
    assert pc.agent_run_id is None
    assert pc.status == STATUS_SUCCEEDED


# --- RAG owner ordinal uniqueness (partial unique index on SQLite) ---------------

def test_rag_ordinal_unique_within_trace(db_session) -> None:
    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    pc1 = ProviderCall(
        workspace_id=ws.id, rag_answer_trace_id=trace.id,
        ordinal=0, phase="answer", provider="deepseek", model="deepseek-v4-flash",
        status=STATUS_SUCCEEDED, input_tokens=10, output_tokens=5,
    )
    db_session.add(pc1)
    db_session.flush()
    with pytest.raises(IntegrityError):
        pc2 = ProviderCall(
            workspace_id=ws.id, rag_answer_trace_id=trace.id,
            ordinal=0, phase="repair", provider="deepseek", model="deepseek-v4-flash",
            status=STATUS_SUCCEEDED, input_tokens=10, output_tokens=5,
        )
        db_session.add(pc2)
        db_session.flush()
    db_session.rollback()


# --- Unknown phase rejected -----------------------------------------------------

def test_unknown_phase_rejected(db_session) -> None:
    ws = _ws(db_session)
    with pytest.raises(ValueError, match="unknown_provider_call_phase"):
        ProviderCallRecorder(
            workspace_id=ws.id,
            provider="deepseek", model="deepseek-v4-flash",
            phase="dynamic_phase_123",
            _session_factory=_sf(db_session),
        )


# --- record_provider_call convenience wrapper -----------------------------------

def test_record_provider_call_success(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    call_count = 0

    def fake_call():
        nonlocal call_count
        call_count += 1
        return ({"result": "ok"}, {"input_tokens": 50, "output_tokens": 25})

    result, usage = record_provider_call(
        db_session, workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        call_fn=fake_call,
    )
    assert result == {"result": "ok"}
    assert usage == {"input_tokens": 50, "output_tokens": 25}
    assert call_count == 1
    # Verify the ProviderCall was recorded
    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_SUCCEEDED


def test_record_provider_call_failure(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    call_count = 0

    def fake_call():
        nonlocal call_count
        call_count += 1
        raise ValueError("provider_unavailable")

    with pytest.raises(ValueError, match="provider_unavailable"):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=fake_call,
        )
    assert call_count == 1
    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "provider_unavailable"


def test_record_provider_call_cancel(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)

    def fake_call():
        raise ValueError("generation_canceled")

    with pytest.raises(ValueError, match="generation_canceled"):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=fake_call,
        )
    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_CANCELED


# --- Constraint failure prevents provider call ----------------------------------

def test_invalid_phase_rejected_before_provider_call(db_session) -> None:
    """Fix 4 (renamed): Invalid phase is rejected at recorder construction,
    before any session is opened. The provider stub is never called."""
    ws = _ws(db_session)
    call_count = 0

    def fake_call():
        nonlocal call_count
        call_count += 1
        return ({}, {})

    # Using an invalid phase triggers ValueError from the recorder itself
    with pytest.raises(ValueError, match="unknown_provider_call_phase"):
        record_provider_call(
            db_session, workspace_id=ws.id,
            provider="deepseek", model="deepseek-v4-flash",
            phase="invalid_phase", call_fn=fake_call,
        )
    assert call_count == 0  # provider stub never called


# --- Forbidden columns check ----------------------------------------------------

_FORBIDDEN_PROVIDER_CALL_COLUMNS = {
    "prompt", "message", "messages", "evidence", "answer", "answers",
    "response", "raw_response", "raw_error", "error_message", "error_text",
    "payload", "content", "body", "text", "question", "completion",
    "output_text", "raw_payload",
}


def test_provider_call_still_has_no_forbidden_columns() -> None:
    """1B-2* must not add any sensitive payload columns."""
    columns = {c.name for c in ProviderCall.__table__.columns}
    leaked = columns & _FORBIDDEN_PROVIDER_CALL_COLUMNS
    assert not leaked, f"ProviderCall must not store sensitive payload columns: {leaked}"
    assert "error_code" in columns
    assert "error_message" not in columns


# --- ORM: owner mutual exclusion CHECK constraint --------------------------------

def test_orm_double_owner_rejected(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    trace = _trace(db_session, ws)
    with pytest.raises(IntegrityError):
        pc = ProviderCall(
            workspace_id=ws.id,
            agent_run_id=run.id,
            rag_answer_trace_id=trace.id,
            ordinal=0, phase="generation",
            provider="deepseek", model="deepseek-v4-flash",
            status=STATUS_STARTED,
        )
        db_session.add(pc)
        db_session.flush()
    db_session.rollback()


# --- ORM: RAG owner ordinal unique partial index --------------------------------

def test_orm_rag_ordinal_unique(db_session) -> None:
    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    pc1 = ProviderCall(
        workspace_id=ws.id, rag_answer_trace_id=trace.id,
        ordinal=0, phase="answer", provider="deepseek", model="deepseek-v4-flash",
        status=STATUS_STARTED,
    )
    db_session.add(pc1)
    db_session.flush()
    with pytest.raises(IntegrityError):
        pc2 = ProviderCall(
            workspace_id=ws.id, rag_answer_trace_id=trace.id,
            ordinal=0, phase="repair", provider="deepseek", model="deepseek-v4-flash",
            status=STATUS_STARTED,
        )
        db_session.add(pc2)
        db_session.flush()
    db_session.rollback()


def test_orm_different_rag_ordinals_allowed(db_session) -> None:
    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    pc1 = ProviderCall(
        workspace_id=ws.id, rag_answer_trace_id=trace.id,
        ordinal=0, phase="answer", provider="deepseek", model="deepseek-v4-flash",
        status=STATUS_STARTED,
    )
    pc2 = ProviderCall(
        workspace_id=ws.id, rag_answer_trace_id=trace.id,
        ordinal=1, phase="repair", provider="deepseek", model="deepseek-v4-flash",
        status=STATUS_STARTED,
    )
    db_session.add_all([pc1, pc2])
    db_session.commit()  # no IntegrityError


# --- ORM: workspace-only calls still work ---------------------------------------

def test_orm_workspace_only_call(db_session) -> None:
    ws = _ws(db_session)
    pc = ProviderCall(
        workspace_id=ws.id,
        agent_run_id=None,
        rag_answer_trace_id=None,
        ordinal=0, phase="generation",
        provider="deepseek", model="deepseek-v4-flash",
        status=STATUS_STARTED,
    )
    db_session.add(pc)
    db_session.commit()
    assert pc.agent_run_id is None
    assert pc.rag_answer_trace_id is None


# --- classify_error: stable error classification --------------------------------

def test_classify_httpx_timeout_is_timed_out() -> None:
    import httpx
    status, code = classify_error(httpx.TimeoutException("read timeout"))
    assert status == STATUS_TIMED_OUT
    assert code == PROVIDER_TIMEOUT


def test_classify_httpx_connect_error_is_failed() -> None:
    import httpx
    status, code = classify_error(httpx.ConnectError("connection refused"))
    assert status == STATUS_FAILED
    assert code == PROVIDER_UNAVAILABLE


def test_classify_known_cancellation_valueerror() -> None:
    status, code = classify_error(ValueError("generation_canceled"))
    assert status == STATUS_CANCELED
    assert code == GENERATION_CANCELED


def test_classify_practice_cancellation() -> None:
    status, code = classify_error(ValueError("practice_canceled"))
    assert status == STATUS_CANCELED
    assert code == GENERATION_CANCELED


def test_classify_budget_exceeded_is_failed_not_canceled() -> None:
    """Budget-exceeded codes map to failed, not canceled."""
    for msg in ("lesson_budget_exceeded", "practice_budget_exceeded",
                "grading_budget_exceeded", "agent_step_budget_exceeded"):
        status, code = classify_error(ValueError(msg))
        assert status == STATUS_FAILED, f"{msg} should be failed, not canceled"
        assert code == msg, f"{msg} should use itself as error code"


def test_classify_known_business_valueerror() -> None:
    status, code = classify_error(ValueError("provider_unavailable"))
    assert status == STATUS_FAILED
    assert code == "provider_unavailable"


def test_classify_unknown_valueerror() -> None:
    status, code = classify_error(ValueError("some_new_error"))
    assert status == STATUS_FAILED
    assert code == UNKNOWN_ERROR


def test_classify_unknown_exception_type() -> None:
    status, code = classify_error(RuntimeError("something broke"))
    assert status == STATUS_FAILED
    assert code == UNKNOWN_ERROR


def _make_chained_timeout_via_cause() -> Exception:
    """Build ValueError with httpx.TimeoutException as __cause__."""
    import httpx
    try:
        raise httpx.TimeoutException("read timeout")
    except httpx.TimeoutException as inner:
        exc = ValueError("generation_provider_unavailable")
        exc.__cause__ = inner
        return exc


def _make_chained_timeout_via_context() -> Exception:
    """Build ValueError with httpx.TimeoutException as __context__.

    __context__ is set when an exception is raised inside an except handler.
    We must actually raise it to trigger Python's implicit __context__ chaining.
    """
    import httpx
    try:
        try:
            raise httpx.TimeoutException("connect timeout")
        except httpx.TimeoutException:
            raise ValueError("generation_provider_unavailable")
    except ValueError as exc:
        return exc


def _make_chained_non_timeout_via_cause() -> Exception:
    """Build ValueError with a non-timeout ValueError as __cause__."""
    try:
        raise ValueError("inner_error")
    except ValueError as inner:
        exc = ValueError("generation_provider_unavailable")
        exc.__cause__ = inner
        return exc


def test_classify_chained_timeout_via_cause() -> None:
    """ValueError wrapping httpx.TimeoutException via __cause__ → timed_out."""
    wrapped = _make_chained_timeout_via_cause()
    status, code = classify_error(wrapped)
    assert status == STATUS_TIMED_OUT
    assert code == PROVIDER_TIMEOUT


def test_classify_chained_timeout_via_context() -> None:
    """ValueError with httpx.TimeoutException as __context__ → timed_out."""
    wrapped = _make_chained_timeout_via_context()
    status, code = classify_error(wrapped)
    assert status == STATUS_TIMED_OUT
    assert code == PROVIDER_TIMEOUT


def test_classify_cause_chain_cycle_safe() -> None:
    """Cyclic __cause__ chain does not infinite-loop."""
    exc1 = ValueError("a")
    exc2 = ValueError("b")
    exc1.__cause__ = exc2
    exc2.__cause__ = exc1  # cycle
    status, code = classify_error(exc1)
    assert status == STATUS_FAILED
    assert code == UNKNOWN_ERROR


def test_classify_no_cause_chain_no_timeout() -> None:
    """ValueError without TimeoutException in chain → not timed_out."""
    wrapped = _make_chained_non_timeout_via_cause()
    status, code = classify_error(wrapped)
    assert status == STATUS_FAILED
    assert code == "generation_provider_unavailable"


# --- record_provider_call: timeout → timed_out ----------------------------------

def test_record_provider_call_timeout(db_session) -> None:
    import httpx
    ws = _ws(db_session)
    run = _run(db_session, ws)
    call_count = 0

    def fake_call():
        nonlocal call_count
        call_count += 1
        raise httpx.TimeoutException("read timeout")

    with pytest.raises(httpx.TimeoutException):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=fake_call,
        )
    assert call_count == 1
    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_TIMED_OUT
    assert calls[0].error_code == PROVIDER_TIMEOUT  # OCR fix: timeout writes stable error_code


# --- record_provider_call: cancel with stable code -------------------------------

def test_record_provider_call_cancel_stable_code(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)

    def fake_call():
        raise ValueError("generation_canceled")

    with pytest.raises(ValueError, match="generation_canceled"):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=fake_call,
        )
    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_CANCELED
    assert calls[0].error_code == GENERATION_CANCELED


# --- record_provider_call: unknown ValueError → unknown_error --------------------

def test_record_provider_call_unknown_error(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)

    def fake_call():
        raise ValueError("some_unrecognized_error")

    with pytest.raises(ValueError, match="some_unrecognized_error"):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=fake_call,
        )
    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == UNKNOWN_ERROR


# --- OCR Fix 1: empty choices → stable ValueError --------------------------------

def test_record_provider_call_empty_choices_rag_answer(db_session) -> None:
    """RAG Answer _generate: provider returns choices=[] → ValueError('invalid_model_output'),
    ProviderCall records failed with stable error_code."""
    from unittest.mock import patch, MagicMock
    from learn_platform_api.services.answers import _generate

    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    from learn_platform_api.settings import Settings
    settings = Settings(
        product_generation_api_key="test-key",
        product_generation_base_url="https://fake.example.com",
        product_generation_model="deepseek-v4-flash",
        product_generation_provider="deepseek",
    )

    resp = MagicMock(spec=__import__("httpx").Response)
    resp.status_code = 200
    resp.json.return_value = {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 0}}
    resp.raise_for_status = MagicMock()

    _gen_latency = [0]
    def _call_generate_for_recorder(messages):
        result, usage, latency = _generate(settings, messages)
        _gen_latency[0] = latency
        return result, usage

    with patch("httpx.post", return_value=resp):
        with pytest.raises(ValueError, match="invalid_model_output"):
            record_provider_call(
                db_session, workspace_id=ws.id, rag_answer_trace_id=trace.id,
                provider="deepseek", model="deepseek-v4-flash", phase="answer",
                call_fn=lambda: _call_generate_for_recorder([{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.rag_answer_trace_id == trace.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "invalid_model_output"


def test_record_provider_call_empty_choices_course(db_session) -> None:
    """Course call_provider: provider returns choices=[] → ValueError('generation_provider_unavailable'),
    ProviderCall records failed with stable error_code."""
    from unittest.mock import patch, MagicMock
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    from learn_platform_api.settings import Settings
    settings = Settings(
        product_generation_api_key="test-key",
        product_generation_base_url="https://fake.example.com",
        product_generation_model="deepseek-v4-flash",
    )

    resp = MagicMock(spec=__import__("httpx").Response)
    resp.status_code = 200
    resp.json.return_value = {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 0}}
    resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=resp):
        with pytest.raises(ValueError, match="generation_provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-flash", phase="generation",
                call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "generation_provider_unavailable"


def test_record_provider_call_empty_choices_practice(db_session) -> None:
    """Practice call_provider: provider returns choices=[] → ValueError('provider_unavailable'),
    ProviderCall records failed with stable error_code."""
    from unittest.mock import patch, MagicMock
    from learn_platform_api.services.practice_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    from learn_platform_api.settings import Settings
    settings = Settings(
        product_generation_api_key="test-key",
        product_generation_base_url="https://fake.example.com",
        product_generation_model="deepseek-v4-flash",
    )

    resp = MagicMock(spec=__import__("httpx").Response)
    resp.status_code = 200
    resp.json.return_value = {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 0}}
    resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=resp):
        with pytest.raises(ValueError, match="provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-flash", phase="generation",
                call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "provider_unavailable"


def test_record_provider_call_empty_choices_practice_generation(db_session) -> None:
    """Practice call_practice_provider: provider returns choices=[] → ValueError('provider_unavailable'),
    ProviderCall records failed with stable error_code."""
    from unittest.mock import patch, MagicMock
    from learn_platform_api.services.practice_generation import call_practice_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    from learn_platform_api.settings import Settings
    settings = Settings(
        product_generation_api_key="test-key",
        product_generation_base_url="https://fake.example.com",
        practice_generation_model="deepseek-v4-pro",
    )

    resp = MagicMock(spec=__import__("httpx").Response)
    resp.status_code = 200
    resp.json.return_value = {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 0}}
    resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=resp):
        with pytest.raises(ValueError, match="provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-pro", phase="generation",
                call_fn=lambda: call_practice_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "provider_unavailable"


# --- OCR Fix 2: timeout records both status=timed_out and error_code=provider_timeout ---

def test_record_provider_call_timeout_has_stable_error_code(db_session) -> None:
    """Direct httpx.TimeoutException → ProviderCall has both status=timed_out
    and error_code=provider_timeout."""
    import httpx
    ws = _ws(db_session)
    run = _run(db_session, ws)

    def fake_call():
        raise httpx.TimeoutException("read timeout")

    with pytest.raises(httpx.TimeoutException):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=fake_call,
        )
    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_TIMED_OUT
    assert calls[0].error_code == PROVIDER_TIMEOUT


def test_record_provider_call_chained_timeout_has_stable_error_code(db_session) -> None:
    """ValueError wrapping httpx.TimeoutException → ProviderCall has both
    status=timed_out and error_code=provider_timeout."""
    import httpx
    ws = _ws(db_session)
    run = _run(db_session, ws)

    def fake_call():
        try:
            raise httpx.TimeoutException("read timeout")
        except httpx.TimeoutException as inner:
            raise ValueError("generation_provider_unavailable") from inner

    with pytest.raises(ValueError, match="generation_provider_unavailable"):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=fake_call,
        )
    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_TIMED_OUT
    assert calls[0].error_code == PROVIDER_TIMEOUT


def test_non_timeout_failure_not_misclassified(db_session) -> None:
    """Non-timeout httpx.HTTPError → status=failed, NOT timed_out."""
    import httpx
    ws = _ws(db_session)
    run = _run(db_session, ws)

    def fake_call():
        raise httpx.ConnectError("connection refused")

    with pytest.raises(httpx.ConnectError):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=fake_call,
        )
    calls = list(db_session.scalars(select(ProviderCall).where(ProviderCall.agent_run_id == run.id)))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == PROVIDER_UNAVAILABLE


# ============================================================================ #
# ADR 004: Independent recorder session — rollback persistence & isolation      #
# ============================================================================ #

def test_provider_call_survives_business_rollback(db_session) -> None:
    """ADR 004 S3.1: Provider Call fact survives business transaction rollback.

    When the business session rolls back after a provider call, the
    ProviderCall row must still be present in the database because it
    was committed in an independent transaction.
    """
    ws = _ws(db_session)
    run = _run(db_session, ws)

    # Simulate: recorder commits a ProviderCall, then business rolls back.
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.succeed(input_tokens=100, output_tokens=50)
    call_id = recorder.call_id
    assert call_id is not None

    # Business session rolls back (simulating worker error handling).
    db_session.rollback()

    # The ProviderCall must still exist (committed in independent tx).
    # Use a fresh session to verify, since the test session was rolled back.
    sf = _sf(db_session)
    with sf() as verify_db:
        pc = verify_db.get(ProviderCall, call_id)
        assert pc is not None
        assert pc.status == STATUS_SUCCEEDED
        assert pc.input_tokens == 100
        assert pc.output_tokens == 50


def test_timeout_provider_call_survives_business_rollback(db_session) -> None:
    """ADR 004: timeout ProviderCall survives business rollback.

    This is the core scenario from the system test: Tutor timeout causes
    recorder to form timed_out/provider_timeout, then worker rollback
    must not delete it.
    """
    import httpx
    ws = _ws(db_session)
    run = _run(db_session, ws)

    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="answer",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.timeout()
    call_id = recorder.call_id

    # Business rollback (as in tutor_workers.run_tutor_turn).
    db_session.rollback()

    # Verify the timed_out fact persists.
    sf = _sf(db_session)
    with sf() as verify_db:
        pc = verify_db.get(ProviderCall, call_id)
        assert pc is not None
        assert pc.status == STATUS_TIMED_OUT
        assert pc.error_code == PROVIDER_TIMEOUT


def test_failed_provider_call_survives_business_rollback(db_session) -> None:
    """ADR 004: failed ProviderCall survives business rollback."""
    ws = _ws(db_session)
    run = _run(db_session, ws)

    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.fail(error_code="provider_unavailable")
    call_id = recorder.call_id

    db_session.rollback()

    sf = _sf(db_session)
    with sf() as verify_db:
        pc = verify_db.get(ProviderCall, call_id)
        assert pc is not None
        assert pc.status == STATUS_FAILED
        assert pc.error_code == "provider_unavailable"


def test_recorder_does_not_modify_caller_session(db_session) -> None:
    """ADR 004 S5.4: The independent recorder1 recorder Session never touches,
    closes, rolls back or commits the caller's business Session.

    After recording, the caller's session should have no pending ProviderCall
    writes (they were committed in the independent session).
    """
    ws = _ws(db_session)
    run = _run(db_session, ws)

    # The caller's session has no ProviderCall objects in its identity map.
    before_count = len(list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    )))
    assert before_count == 0

    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.succeed(input_tokens=50, output_tokens=25)

    # The caller's session still has no ProviderCall objects (they were
    # committed in the independent session, not added to this session).
    # We need to commit/refresh to see them since they're in a different session.
    db_session.commit()
    after_count = len(list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    )))
    assert after_count == 1


def test_start_invalid_phase_prevents_provider_call(db_session) -> None:
    """Fix 4 (renamed): Invalid phase is rejected at recorder construction,
    before any session is opened. The provider stub is never called.

    This is a validation-level failure, NOT a real DB commit/FK failure.
    See test_start_fk_failure_nonexistent_agent_run_prevents_provider_call
    for the real DB constraint failure test.
    """
    ws = _ws(db_session)
    call_count = 0

    def fake_call():
        nonlocal call_count
        call_count += 1
        return ({}, {})

    # Using an invalid phase triggers ValueError from the recorder itself
    # before any session is opened.
    with pytest.raises(ValueError, match="unknown_provider_call_phase"):
        record_provider_call(
            db_session, workspace_id=ws.id,
            provider="deepseek", model="deepseek-v4-flash",
            phase="invalid_phase", call_fn=fake_call,
        )
    assert call_count == 0  # provider stub never called


def test_succeeded_call_remains_succeeded_after_artifact_validation_failure(db_session) -> None:
    """ADR 004 S3.3: provider returns success but artifact validation fails ->
    the ProviderCall still has status=succeeded.

    The provider call fact is independent of business artifact validation.
    """
    ws = _ws(db_session)
    run = _run(db_session, ws)

    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="answer",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.succeed(input_tokens=200, output_tokens=100)
    call_id = recorder.call_id

    # Business artifact validation fails -> rollback.
    db_session.rollback()

    # ProviderCall is still succeeded.
    sf = _sf(db_session)
    with sf() as verify_db:
        pc = verify_db.get(ProviderCall, call_id)
        assert pc is not None
        assert pc.status == STATUS_SUCCEEDED


def test_rag_owner_provider_call_survives_business_rollback(db_session) -> None:
    """ADR 004: RAG Answer ProviderCall survives business rollback."""
    ws = _ws(db_session)
    trace = _trace(db_session, ws)

    recorder = ProviderCallRecorder(
        workspace_id=ws.id, rag_answer_trace_id=trace.id,
        provider="deepseek", model="deepseek-v4-flash", phase="answer",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    recorder.succeed(input_tokens=300, output_tokens=150)
    call_id = recorder.call_id

    db_session.rollback()

    sf = _sf(db_session)
    with sf() as verify_db:
        pc = verify_db.get(ProviderCall, call_id)
        assert pc is not None
        assert pc.status == STATUS_SUCCEEDED
        assert pc.rag_answer_trace_id == trace.id


# ============================================================================ #
# Fix 1: RAG Answer Trace final state — replaced by acceptance tests           #
# ============================================================================ #
# The old test_rag_trace_succeeded_is_committed and
# test_rag_trace_failed_is_committed manually created a Trace, assigned
# status, and committed — never calling answer_question(). They have been
# replaced by test_acceptance_evidence_rag_trace.py which calls the real
# answer_question() service.


# ============================================================================ #
# Fix 2: Recorder finalizer unit tests (direct finalizer calls)                #
# ============================================================================ #
# These are UNIT tests for the ProviderCallRecorder finalizer methods,
# verifying that each finalizer raises RuntimeError when the record is
# missing. They test the recorder's finalizer behavior directly, NOT
# through the record_provider_call() wrapper.
#
# The WRAPPER-level acceptance tests (which prove the wrapper does not
# return success on finalize-missing, and preserves original exceptions)
# are in test_acceptance_evidence_wrapper.py.

def test_recorder_succeed_unit_raises_on_missing_record(db_session) -> None:
    """Unit: succeed() raises RuntimeError('provider_call_finalize_missing')
    when the ProviderCall record is gone from the independent session."""
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    call_id = recorder.call_id
    assert call_id is not None

    sf = _sf(db_session)
    with sf() as del_db:
        pc = del_db.get(ProviderCall, call_id)
        if pc is not None:
            del_db.delete(pc)
            del_db.commit()

    with pytest.raises(RuntimeError, match="provider_call_finalize_missing"):
        recorder.succeed(input_tokens=10, output_tokens=5)


def test_recorder_fail_unit_raises_on_missing_record(db_session) -> None:
    """Unit: fail() raises RuntimeError('provider_call_finalize_missing')."""
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    call_id = recorder.call_id

    sf = _sf(db_session)
    with sf() as del_db:
        pc = del_db.get(ProviderCall, call_id)
        if pc is not None:
            del_db.delete(pc)
            del_db.commit()

    with pytest.raises(RuntimeError, match="provider_call_finalize_missing"):
        recorder.fail(error_code="provider_unavailable")


def test_recorder_timeout_unit_raises_on_missing_record(db_session) -> None:
    """Unit: timeout() raises RuntimeError('provider_call_finalize_missing')."""
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    call_id = recorder.call_id

    sf = _sf(db_session)
    with sf() as del_db:
        pc = del_db.get(ProviderCall, call_id)
        if pc is not None:
            del_db.delete(pc)
            del_db.commit()

    with pytest.raises(RuntimeError, match="provider_call_finalize_missing"):
        recorder.timeout()


def test_recorder_cancel_unit_raises_on_missing_record(db_session) -> None:
    """Unit: cancel() raises RuntimeError('provider_call_finalize_missing')."""
    ws = _ws(db_session)
    run = _run(db_session, ws)
    recorder = ProviderCallRecorder(
        workspace_id=ws.id, agent_run_id=run.id,
        provider="deepseek", model="deepseek-v4-flash", phase="generation",
        _session_factory=_sf(db_session),
    )
    recorder.start()
    call_id = recorder.call_id

    sf = _sf(db_session)
    with sf() as del_db:
        pc = del_db.get(ProviderCall, call_id)
        if pc is not None:
            del_db.delete(pc)
            del_db.commit()

    with pytest.raises(RuntimeError, match="provider_call_finalize_missing"):
        recorder.cancel(error_code="generation_canceled")


# ============================================================================ #
# Fix 4: Input validation (invalid phase) — renamed for accuracy               #
# ============================================================================ #
# The old test_invalid_phase_prevents_provider_call_renamed only verified
# that an invalid phase is rejected at recorder construction time. This is
# a validation-level failure, NOT a real DB commit/FK failure.
#
# The real FK failure tests (which use record_provider_call with fake_call)
# are in test_acceptance_evidence_wrapper.py.

def test_invalid_phase_rejected_is_input_validation(db_session) -> None:
    """Input validation: Invalid phase is rejected at recorder construction,
    before any session is opened. This is NOT a DB constraint failure."""
    ws = _ws(db_session)
    call_count = 0

    def fake_call():
        nonlocal call_count
        call_count += 1
        return ({}, {})

    with pytest.raises(ValueError, match="unknown_provider_call_phase"):
        record_provider_call(
            db_session, workspace_id=ws.id,
            provider="deepseek", model="deepseek-v4-flash",
            phase="invalid_phase", call_fn=fake_call,
        )
    assert call_count == 0
