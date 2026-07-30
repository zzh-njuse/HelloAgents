"""Stage 5 Part 2 Slice 2A — FK/start failure and wrapper finalization
acceptance evidence.

Replaces:
- test_start_fk_failure_nonexistent_agent_run_prevents_provider_call (called
  ProviderCallRecorder.start() directly, never passed fake_call to
  record_provider_call)
- test_start_fk_failure_nonexistent_rag_trace_prevents_provider_call (same)
- test_succeed_raises_on_missing_record (called recorder.succeed() directly,
  not through record_provider_call)
- test_fail_raises_on_missing_record (same)
- test_timeout_raises_on_missing_record (same)
- test_cancel_raises_on_missing_record (same)
- test_finalize_missing_does_not_swallow_provider_exception (same)
- test_record_provider_call_success_finalize_missing_does_not_return_success (same)

New tests call the real record_provider_call(..., call_fn=fake_call) and
verify:
- FK failure: IntegrityError propagates, fake_call count == 0
- Wrapper finalization missing: provider success + record deleted →
  RuntimeError("provider_call_finalize_failed"), not success result
- Wrapper finalization missing: provider failure + record deleted →
  original exception preserved with finalization failure in cause chain
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from learn_platform_api.db.base import Base
from learn_platform_api.db.models import (
    AgentRun,
    PracticeJob,
    ProviderCall,
    RagAnswerTrace,
    Workspace,
)
from learn_platform_api.services.provider_call_recorder import (
    ProviderCallRecorder,
    record_provider_call,
    STATUS_STARTED,
    STATUS_SUCCEEDED,
    STATUS_FAILED,
)


# --- ADR 004 helper -----------------------------------------------------------

def _sf(db_session):
    """Return the test session factory for independent recorder sessions."""
    return getattr(db_session, '_test_session_factory', None)


# --- seed helpers -------------------------------------------------------------

def _ws(db_session) -> Workspace:
    ws = Workspace(name="ws", slug=f"ws-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.flush()
    db_session.commit()
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
    db_session.commit()
    return ar


def _trace(db_session, ws: Workspace) -> RagAnswerTrace:
    t = RagAnswerTrace(
        workspace_id=ws.id, question_hash="0" * 64, status="succeeded",
        prompt_template_version="v1", evidence_chunk_ids=[], citation_ids=[],
    )
    db_session.add(t)
    db_session.flush()
    db_session.commit()
    return t


# ============================================================================ #
# Fix 4: FK/start failure via record_provider_call(..., call_fn=fake_call)     #
# ============================================================================ #

def test_fk_failure_nonexistent_agent_run_via_wrapper(db_session) -> None:
    """Fix 4: Real DB FK failure via record_provider_call() — using a
    non-existent AgentRun ID causes the independent session commit to fail
    (IntegrityError on FK constraint), and fake_call is NEVER invoked.

    This test uses record_provider_call(..., call_fn=fake_call), not
    ProviderCallRecorder.start() directly. The fake_call counter proves
    the provider was never reached.
    """
    ws = _ws(db_session)
    db_session.commit()

    fake_agent_run_id = f"ar-nonexistent-{uuid4().hex[:8]}"
    call_count = 0

    def fake_call():
        nonlocal call_count
        call_count += 1
        return ({}, {})

    # Create an FK-enforcing session factory for this test.
    fk_engine = create_engine(
        f"sqlite+pysqlite:///{Path(db_session.get_bind().engine.url.database)}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(fk_engine, "connect")
    def _set_fk_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=fk_engine)
    FKSession = sessionmaker(bind=fk_engine, autoflush=False, expire_on_commit=False)

    # Use a session from the FK-enforcing factory as the business session.
    with FKSession() as fk_db:
        fk_db._test_session_factory = FKSession

        with pytest.raises(IntegrityError):
            record_provider_call(
                fk_db, workspace_id=ws.id, agent_run_id=fake_agent_run_id,
                provider="deepseek", model="deepseek-v4-flash", phase="generation",
                call_fn=fake_call,
                _session_factory=FKSession,
            )

    assert call_count == 0, "fake_call must never be invoked when start fails"
    fk_engine.dispose()


def test_fk_failure_nonexistent_rag_trace_via_wrapper(db_session) -> None:
    """Fix 4: Real DB FK failure via record_provider_call() — using a
    non-existent RagAnswerTrace ID causes IntegrityError, and fake_call
    is NEVER invoked."""
    ws = _ws(db_session)
    db_session.commit()

    fake_trace_id = f"tr-nonexistent-{uuid4().hex[:8]}"
    call_count = 0

    def fake_call():
        nonlocal call_count
        call_count += 1
        return ({}, {})

    fk_engine = create_engine(
        f"sqlite+pysqlite:///{Path(db_session.get_bind().engine.url.database)}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(fk_engine, "connect")
    def _set_fk_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=fk_engine)
    FKSession = sessionmaker(bind=fk_engine, autoflush=False, expire_on_commit=False)

    with FKSession() as fk_db:
        fk_db._test_session_factory = FKSession

        with pytest.raises(IntegrityError):
            record_provider_call(
                fk_db, workspace_id=ws.id, rag_answer_trace_id=fake_trace_id,
                provider="deepseek", model="deepseek-v4-flash", phase="answer",
                call_fn=fake_call,
                _session_factory=FKSession,
            )

    assert call_count == 0
    fk_engine.dispose()


# ============================================================================ #
# Fix 2: Wrapper finalization missing — provider success, record deleted       #
# ============================================================================ #

def test_wrapper_success_finalize_missing_via_record_provider_call(db_session) -> None:
    """Fix 2: record_provider_call() — provider succeeds but finalizer finds
    the ProviderCall record deleted (by another session during call_fn).

    The wrapper must NOT return the success result. It must raise
    RuntimeError("provider_call_finalize_failed") with the finalization
    error in the cause chain.

    The call_fn deletes the just-created ProviderCall from an independent
    session, then returns a success result.
    """
    ws = _ws(db_session)
    run = _run(db_session, ws)
    sf = _sf(db_session)

    def call_fn_that_deletes_record():
        """call_fn: find and delete the just-started ProviderCall, then
        return success."""
        # Find the most recent started ProviderCall for this run.
        with sf() as del_db:
            pc = del_db.scalar(
                select(ProviderCall)
                .where(
                    ProviderCall.agent_run_id == run.id,
                    ProviderCall.status == STATUS_STARTED,
                )
                .order_by(ProviderCall.started_at.desc())
                .limit(1)
            )
            if pc is not None:
                del_db.delete(pc)
                del_db.commit()
        # Return success result — but the record is gone.
        return ({"result": "ok"}, {"input_tokens": 50, "output_tokens": 25})

    with pytest.raises(RuntimeError, match="provider_call_finalize_failed") as exc_info:
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=call_fn_that_deletes_record,
        )

    # The cause chain must contain the finalization failure.
    cause = exc_info.value.__cause__
    assert cause is not None
    assert "provider_call_finalize_missing" in str(cause)


# ============================================================================ #
# Fix 2: Wrapper finalization missing — provider failure, record deleted       #
# ============================================================================ #

def test_wrapper_failure_finalize_missing_via_record_provider_call(db_session) -> None:
    """Fix 2: record_provider_call() — provider throws AND finalizer finds
    the ProviderCall record deleted.

    The caller must receive the ORIGINAL provider exception (not a
    RuntimeError about finalization). The finalization failure must be
    preserved in the __cause__ chain, not swallowed.

    The call_fn deletes the just-created ProviderCall from an independent
    session, then raises a known provider exception.
    """
    ws = _ws(db_session)
    run = _run(db_session, ws)
    sf = _sf(db_session)

    def call_fn_that_deletes_and_fails():
        """call_fn: find and delete the just-started ProviderCall, then
        raise a known provider exception."""
        with sf() as del_db:
            pc = del_db.scalar(
                select(ProviderCall)
                .where(
                    ProviderCall.agent_run_id == run.id,
                    ProviderCall.status == STATUS_STARTED,
                )
                .order_by(ProviderCall.started_at.desc())
                .limit(1)
            )
            if pc is not None:
                del_db.delete(pc)
                del_db.commit()
        raise ValueError("provider_unavailable")

    with pytest.raises(ValueError, match="provider_unavailable") as exc_info:
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=call_fn_that_deletes_and_fails,
        )

    # The original ValueError must be the raised exception.
    assert isinstance(exc_info.value, ValueError)
    assert str(exc_info.value) == "provider_unavailable"

    # The cause chain must contain the finalization failure.
    cause = exc_info.value.__cause__
    assert cause is not None
    assert "provider_call_finalize_missing" in str(cause)


# ============================================================================ #
# Fix 2: Wrapper finalization missing — timeout, record deleted                #
# ============================================================================ #

def test_wrapper_timeout_finalize_missing_via_record_provider_call(db_session) -> None:
    """Fix 2: record_provider_call() — provider times out AND finalizer
    finds the ProviderCall record deleted.

    The caller must receive the original timeout exception. The
    finalization failure must be in the cause chain.
    """
    import httpx

    ws = _ws(db_session)
    run = _run(db_session, ws)
    sf = _sf(db_session)

    def call_fn_that_deletes_and_times_out():
        with sf() as del_db:
            pc = del_db.scalar(
                select(ProviderCall)
                .where(
                    ProviderCall.agent_run_id == run.id,
                    ProviderCall.status == STATUS_STARTED,
                )
                .order_by(ProviderCall.started_at.desc())
                .limit(1)
            )
            if pc is not None:
                del_db.delete(pc)
                del_db.commit()
        raise httpx.TimeoutException("read timeout")

    with pytest.raises(httpx.TimeoutException) as exc_info:
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=call_fn_that_deletes_and_times_out,
        )

    assert isinstance(exc_info.value, httpx.TimeoutException)
    cause = exc_info.value.__cause__
    assert cause is not None
    assert "provider_call_finalize_missing" in str(cause)
