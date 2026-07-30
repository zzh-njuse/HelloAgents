"""Focused acceptance tests for Spec 008 / ADR 006."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from learn_platform_api.db.models import (
    AgentRun,
    AgentToolCall,
    JobToolAuthorization,
    PracticeJob,
    Workspace,
)
from learn_platform_api.services.remote_tool_call_recorder import (
    RemoteToolCallRecorder,
    TOOL_AUTHORIZATION_INVALID,
    TOOL_BUDGET_EXCEEDED,
)


def _seed(db_session, *, max_calls: int = 2):
    ws = Workspace(name="durable-tools", slug=f"tools-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.flush()
    job = PracticeJob(
        workspace_id=ws.id,
        job_type="generate_set",
        output_language="zh-CN",
        difficulty="standard",
        item_count=1,
        request_hash="0" * 64,
        idempotency_key=f"tools-{uuid4().hex[:8]}",
        attempt_count=1,
    )
    db_session.add(job)
    db_session.flush()
    run = AgentRun(
        practice_job_id=job.id,
        workspace_id=ws.id,
        role="exercise_author",
        attempt_number=1,
        status="running",
    )
    auth = JobToolAuthorization(
        workspace_id=ws.id,
        capability_id="code_execution",
        practice_job_id=job.id,
        max_calls=max_calls,
        used_calls=0,
    )
    db_session.add_all([run, auth])
    db_session.commit()
    return ws, job, run, auth


def _recorder(db_session, ws, run, auth, ordinal: int):
    return RemoteToolCallRecorder(
        db_session,
        workspace_id=ws.id,
        agent_run_id=run.id,
        authorization_kind="job",
        authorization_id=auth.id,
        capability_id="code_execution",
        tool_name="ValidateCodingReference",
        ordinal=ordinal,
        input_hash="a" * 16,
    )


def test_reservation_and_success_survive_business_rollback(db_session) -> None:
    ws, _job, run, auth = _seed(db_session)
    recorder = _recorder(db_session, ws, run, auth, 1)

    assert recorder.reserve() == 1
    recorder.succeed(result_count=3)
    db_session.rollback()

    factory = db_session._test_session_factory
    with factory() as check:
        persisted_auth = check.get(JobToolAuthorization, auth.id)
        call = check.scalar(
            select(AgentToolCall).where(
                AgentToolCall.agent_run_id == run.id,
                AgentToolCall.ordinal == 1,
            )
        )
        assert persisted_auth is not None
        assert persisted_auth.used_calls == 1
        assert call is not None
        assert call.status == "succeeded"
        assert call.result_count == 3


def test_budget_exhaustion_does_not_create_second_fact(db_session) -> None:
    ws, _job, run, auth = _seed(db_session, max_calls=1)
    first = _recorder(db_session, ws, run, auth, 1)
    first.reserve()
    first.fail(error_code="backend_unavailable")

    second = _recorder(db_session, ws, run, auth, 2)
    with pytest.raises(ValueError, match=TOOL_BUDGET_EXCEEDED):
        second.reserve()

    factory = db_session._test_session_factory
    with factory() as check:
        calls = list(
            check.scalars(
                select(AgentToolCall).where(
                    AgentToolCall.agent_run_id == run.id
                )
            )
        )
        assert len(calls) == 1
        assert check.get(JobToolAuthorization, auth.id).used_calls == 1


def test_workspace_mismatch_rejected_before_fact(db_session) -> None:
    ws, _job, run, auth = _seed(db_session)
    other = Workspace(name="other", slug=f"other-{uuid4().hex[:8]}")
    db_session.add(other)
    db_session.commit()

    recorder = RemoteToolCallRecorder(
        db_session,
        workspace_id=other.id,
        agent_run_id=run.id,
        authorization_kind="job",
        authorization_id=auth.id,
        capability_id="code_execution",
        tool_name="ValidateCodingReference",
        ordinal=1,
    )
    with pytest.raises(ValueError, match=TOOL_AUTHORIZATION_INVALID):
        recorder.reserve()


def test_finalize_missing_is_not_silent(db_session) -> None:
    ws, _job, run, auth = _seed(db_session)
    recorder = _recorder(db_session, ws, run, auth, 1)
    recorder.reserve()
    factory = db_session._test_session_factory
    with factory() as delete_session:
        call = delete_session.get(AgentToolCall, recorder.call_id)
        delete_session.delete(call)
        delete_session.commit()

    with pytest.raises(RuntimeError, match="remote_tool_call_finalize_missing"):
        recorder.succeed()
