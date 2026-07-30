"""Stage 5 Slice 1B-2 — Provider Call real chain behavior tests.

Verifies that each orchestration chain correctly wires Provider Call recording
through the REAL low-level HTTP helpers (call_provider, call_practice_provider,
_generate). Tests monkeypatch httpx.post to throw httpx.TimeoutException,
letting the real helper complete exception conversion
(ValueError(...) from exc), then verify ProviderCall.status == timed_out
via classify_error's __cause__ chain walk.

Covers (Spec 003 / ADR 002):
- Course generation: call_provider → record_provider_call, plan+generation phases
- Tutor: call_provider → record_provider_call, plan+answer phases
- Practice generation: call_practice_provider → record_provider_call, plan+generation
- Practice grading: call_provider → record_provider_call, grading phase
- RAG Answer: _generate → record_provider_call, answer phase with rag owner

For each chain:
- Normal call produces correct owner/provider/model/phase/ordinal
- Timeout via monkeypatched httpx.post records timed_out status
- ProviderCall count and phase/ordinal are locked from the final DB query
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from learn_platform_api.db.models import (
    AgentRun,
    PracticeJob,
    ProviderCall,
    RagAnswerTrace,
    Workspace,
)
from learn_platform_api.services.provider_call_recorder import (
    STATUS_SUCCEEDED,
    STATUS_FAILED,
    STATUS_TIMED_OUT,
    STATUS_CANCELED,
    record_provider_call,
    classify_error,
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


def _fake_provider_response(usage_input=100, usage_output=50, content=None):
    """Build a fake httpx.Response that looks like a provider JSON response."""
    if content is None:
        content = json.dumps({"queries": ["q1"]})
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": usage_input, "completion_tokens": usage_output},
    }
    resp.raise_for_status = MagicMock()
    return resp


def _make_settings(**overrides):
    """Build a Settings object with test defaults."""
    from learn_platform_api.settings import Settings
    defaults = dict(
        product_generation_api_key="test-key",
        product_generation_base_url="https://fake.example.com",
        product_generation_model="deepseek-v4-flash",
        practice_generation_model="deepseek-v4-pro",
        product_generation_provider="deepseek",
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ============================================================================ #
# 1. Course generation — call_provider → record_provider_call                   #
# ============================================================================ #

def test_course_generation_records_plan_and_generation(db_session) -> None:
    """Course generation plan + generation via real call_provider produce
    ProviderCalls with correct phases."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_provider_response(content=json.dumps({"queries": ["q1"]}))

    with patch("httpx.post", side_effect=fake_post):
        # Plan call
        result1, usage1 = record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="plan",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "plan"}]),
        )
        # Generation call
        result2, usage2 = record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "gen"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
        .order_by(ProviderCall.ordinal)
    ))
    assert len(calls) == 2
    assert calls[0].phase == "plan"
    assert calls[0].ordinal == 0
    assert calls[0].status == STATUS_SUCCEEDED
    assert calls[1].phase == "generation"
    assert calls[1].ordinal == 1
    assert calls[1].status == STATUS_SUCCEEDED
    assert call_count == 2


def test_course_generation_timeout_via_real_helper(db_session) -> None:
    """Course generation timeout: monkeypatch httpx.post → TimeoutException,
    call_provider wraps as ValueError("generation_provider_unavailable") from exc,
    ProviderCall.status == timed_out via __cause__ chain."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=httpx.TimeoutException("read timeout")):
        with pytest.raises(ValueError, match="generation_provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-flash", phase="generation",
                call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_TIMED_OUT
    assert calls[0].error_code == PROVIDER_TIMEOUT  # OCR fix: timeout writes stable error_code


def test_course_generation_repair_records_repair_phase(db_session) -> None:
    """Course generation repair via real call_provider produces phase='repair'."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=lambda *a, **kw: _fake_provider_response(
        content=json.dumps({"fixed": True}), usage_input=80, usage_output=40,
    )):
        result, usage = record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="repair",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "repair"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].phase == "repair"
    assert calls[0].status == STATUS_SUCCEEDED


# ============================================================================ #
# 2. Tutor — call_provider → record_provider_call                              #
# ============================================================================ #

def test_tutor_records_plan_and_answer(db_session) -> None:
    """Tutor plan + answer via real call_provider produce ProviderCalls."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_provider_response(content=json.dumps({"intent": "explain"}))

    with patch("httpx.post", side_effect=fake_post):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="plan",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "plan"}]),
        )
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="answer",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "answer"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
        .order_by(ProviderCall.ordinal)
    ))
    assert len(calls) == 2
    assert calls[0].phase == "plan"
    assert calls[1].phase == "answer"
    assert call_count == 2


def test_tutor_timeout_via_real_helper(db_session) -> None:
    """Tutor timeout: monkeypatch httpx.post → TimeoutException,
    call_provider wraps as ValueError, ProviderCall.status == timed_out."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=httpx.TimeoutException("connect timeout")):
        with pytest.raises(ValueError, match="generation_provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-flash", phase="answer",
                call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_TIMED_OUT
    assert calls[0].error_code == PROVIDER_TIMEOUT  # OCR fix: timeout writes stable error_code


def test_tutor_repair_records_repair_phase(db_session) -> None:
    """Tutor repair via real call_provider produces phase='repair'."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=lambda *a, **kw: _fake_provider_response(
        content=json.dumps({"blocks": []}), usage_input=50, usage_output=25,
    )):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="repair",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "repair"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].phase == "repair"


# ============================================================================ #
# 3. Practice generation — call_practice_provider → record_provider_call        #
# ============================================================================ #

def test_practice_generation_records_plan_and_generation(db_session) -> None:
    """Practice generation plan + generation via real call_practice_provider."""
    from learn_platform_api.services.practice_generation import call_practice_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_provider_response(content=json.dumps({"queries": ["q1"]}))

    with patch("httpx.post", side_effect=fake_post):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-pro", phase="plan",
            call_fn=lambda: call_practice_provider(settings, [{"role": "user", "content": "plan"}]),
        )
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-pro", phase="generation",
            call_fn=lambda: call_practice_provider(settings, [{"role": "user", "content": "gen"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
        .order_by(ProviderCall.ordinal)
    ))
    assert len(calls) == 2
    assert calls[0].phase == "plan"
    assert calls[1].phase == "generation"
    assert call_count == 2


def test_practice_generation_timeout_via_real_helper(db_session) -> None:
    """Practice generation timeout: monkeypatch httpx.post → TimeoutException,
    call_practice_provider wraps as ValueError, ProviderCall.status == timed_out."""
    from learn_platform_api.services.practice_generation import call_practice_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=httpx.TimeoutException("read timeout")):
        with pytest.raises(ValueError, match="provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-pro", phase="generation",
                call_fn=lambda: call_practice_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_TIMED_OUT
    assert calls[0].error_code == PROVIDER_TIMEOUT  # OCR fix: timeout writes stable error_code


def test_practice_generation_repair_records_repair_phase(db_session) -> None:
    """Practice generation repair via real call_practice_provider."""
    from learn_platform_api.services.practice_generation import call_practice_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=lambda *a, **kw: _fake_provider_response(
        content=json.dumps({"items": []}), usage_input=60, usage_output=30,
    )):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-pro", phase="repair",
            call_fn=lambda: call_practice_provider(settings, [{"role": "user", "content": "repair"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].phase == "repair"


# ============================================================================ #
# 4. Practice grading — call_provider → record_provider_call                    #
# ============================================================================ #

def test_practice_grading_records_grading(db_session) -> None:
    """Practice grading via real call_provider produces phase='grading'."""
    from learn_platform_api.services.practice_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=lambda *a, **kw: _fake_provider_response(
        content=json.dumps({"verdict": "correct", "score": 100}),
        usage_input=80, usage_output=40,
    )):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="grading",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "grade"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].phase == "grading"
    assert calls[0].status == STATUS_SUCCEEDED


def test_practice_grading_timeout_via_real_helper(db_session) -> None:
    """Practice grading timeout: monkeypatch httpx.post → TimeoutException,
    call_provider wraps as ValueError, ProviderCall.status == timed_out."""
    from learn_platform_api.services.practice_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=httpx.TimeoutException("read timeout")):
        with pytest.raises(ValueError, match="provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-flash", phase="grading",
                call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_TIMED_OUT
    assert calls[0].error_code == PROVIDER_TIMEOUT  # OCR fix: timeout writes stable error_code


def test_practice_grading_repair_records_repair_phase(db_session) -> None:
    """Practice grading repair via real call_provider."""
    from learn_platform_api.services.practice_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=lambda *a, **kw: _fake_provider_response(
        content=json.dumps({"verdict": "correct", "score": 100}),
        usage_input=40, usage_output=20,
    )):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="repair",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "repair"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].phase == "repair"


# ============================================================================ #
# 5. RAG Answer — _generate → record_provider_call                             #
# ============================================================================ #

def test_rag_answer_records_answer_with_rag_owner(db_session) -> None:
    """RAG answer via real _generate produces ProviderCall with rag owner."""
    from learn_platform_api.services.answers import _generate

    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    settings = _make_settings()

    answer_content = json.dumps({
        "claims": [{"text": "fact", "citation_ids": ["c1"]}],
        "limitations": [],
    })

    _gen_latency = [0]

    def _call_generate_for_recorder(messages):
        """Wrap _generate to return (result, usage) 2-tuple."""
        result, usage, latency = _generate(settings, messages)
        _gen_latency[0] = latency
        return result, usage

    with patch("httpx.post", side_effect=lambda *a, **kw: _fake_provider_response(
        content=answer_content, usage_input=300, usage_output=150,
    )):
        result, usage = record_provider_call(
            db_session, workspace_id=ws.id, rag_answer_trace_id=trace.id,
            provider="deepseek", model="deepseek-v4-flash", phase="answer",
            call_fn=lambda: _call_generate_for_recorder([{"role": "user", "content": "answer"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.rag_answer_trace_id == trace.id)
    ))
    assert len(calls) == 1
    assert calls[0].phase == "answer"
    assert calls[0].ordinal == 0
    assert calls[0].status == STATUS_SUCCEEDED
    assert calls[0].rag_answer_trace_id == trace.id
    assert calls[0].agent_run_id is None
    assert calls[0].input_tokens == 300
    assert calls[0].output_tokens == 150


def test_rag_answer_timeout_via_real_helper(db_session) -> None:
    """RAG answer timeout: monkeypatch httpx.post → TimeoutException,
    _generate wraps as ValueError("generation_provider_unavailable") from exc,
    ProviderCall.status == timed_out via __cause__ chain."""
    from learn_platform_api.services.answers import _generate

    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    settings = _make_settings()

    _gen_latency = [0]

    def _call_generate_for_recorder(messages):
        result, usage, latency = _generate(settings, messages)
        _gen_latency[0] = latency
        return result, usage

    with patch("httpx.post", side_effect=httpx.TimeoutException("read timeout")):
        with pytest.raises(ValueError, match="generation_provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, rag_answer_trace_id=trace.id,
                provider="deepseek", model="deepseek-v4-flash", phase="answer",
                call_fn=lambda: _call_generate_for_recorder([{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.rag_answer_trace_id == trace.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_TIMED_OUT
    assert calls[0].error_code == PROVIDER_TIMEOUT  # OCR fix: timeout writes stable error_code


def test_rag_answer_repair_records_repair_phase(db_session) -> None:
    """RAG answer repair via real _generate produces phase='repair'."""
    from learn_platform_api.services.answers import _generate

    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    settings = _make_settings()

    answer_content = json.dumps({
        "claims": [{"text": "fact", "citation_ids": ["c1"]}],
        "limitations": [],
    })

    _gen_latency = [0]

    def _call_generate_for_recorder(messages):
        result, usage, latency = _generate(settings, messages)
        _gen_latency[0] = latency
        return result, usage

    with patch("httpx.post", side_effect=lambda *a, **kw: _fake_provider_response(
        content=answer_content, usage_input=300, usage_output=150,
    )):
        # Answer call
        record_provider_call(
            db_session, workspace_id=ws.id, rag_answer_trace_id=trace.id,
            provider="deepseek", model="deepseek-v4-flash", phase="answer",
            call_fn=lambda: _call_generate_for_recorder([{"role": "user", "content": "answer"}]),
        )
        # Repair call
        record_provider_call(
            db_session, workspace_id=ws.id, rag_answer_trace_id=trace.id,
            provider="deepseek", model="deepseek-v4-flash", phase="repair",
            call_fn=lambda: _call_generate_for_recorder([{"role": "user", "content": "repair"}]),
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.rag_answer_trace_id == trace.id)
        .order_by(ProviderCall.ordinal)
    ))
    assert len(calls) == 2
    assert calls[0].phase == "answer"
    assert calls[0].ordinal == 0
    assert calls[1].phase == "repair"
    assert calls[1].ordinal == 1


# ============================================================================ #
# 6. classify_error: budget_exceeded → failed, not canceled                     #
# ============================================================================ #

def test_classify_lesson_budget_exceeded_is_failed() -> None:
    """lesson_budget_exceeded maps to failed, not canceled."""
    status, code = classify_error(ValueError("lesson_budget_exceeded"))
    assert status == STATUS_FAILED
    assert code == "lesson_budget_exceeded"


def test_classify_practice_budget_exceeded_is_failed() -> None:
    """practice_budget_exceeded maps to failed, not canceled."""
    status, code = classify_error(ValueError("practice_budget_exceeded"))
    assert status == STATUS_FAILED
    assert code == "practice_budget_exceeded"


def test_classify_grading_budget_exceeded_is_failed() -> None:
    """grading_budget_exceeded maps to failed, not canceled."""
    status, code = classify_error(ValueError("grading_budget_exceeded"))
    assert status == STATUS_FAILED
    assert code == "grading_budget_exceeded"


def test_classify_agent_step_budget_exceeded_is_failed() -> None:
    """agent_step_budget_exceeded maps to failed, not canceled."""
    status, code = classify_error(ValueError("agent_step_budget_exceeded"))
    assert status == STATUS_FAILED
    assert code == "agent_step_budget_exceeded"


# ============================================================================ #
# 7. classify_error: __cause__ chain walk for timeout                           #
# ============================================================================ #

def _make_chained_timeout_via_cause() -> Exception:
    """Build ValueError with httpx.TimeoutException as __cause__."""
    try:
        raise httpx.TimeoutException("read timeout")
    except httpx.TimeoutException as inner:
        exc = ValueError("generation_provider_unavailable")
        exc.__cause__ = inner
        return exc


def _make_chained_timeout_via_context() -> Exception:
    """Build ValueError with httpx.TimeoutException as __context__.

    __context__ is set when an exception is raised inside an except handler.
    """
    try:
        try:
            raise httpx.TimeoutException("connect timeout")
        except httpx.TimeoutException:
            raise ValueError("generation_provider_unavailable")
    except ValueError as exc:
        return exc


def _make_chained_connect_error_via_cause() -> Exception:
    """Build ValueError with httpx.ConnectError as __cause__."""
    try:
        raise httpx.ConnectError("connection refused")
    except httpx.ConnectError as inner:
        exc = ValueError("generation_provider_unavailable")
        exc.__cause__ = inner
        return exc


def test_classify_valueerror_wrapping_timeout_via_cause() -> None:
    """ValueError("generation_provider_unavailable") from TimeoutException → timed_out."""
    wrapped = _make_chained_timeout_via_cause()
    status, code = classify_error(wrapped)
    assert status == STATUS_TIMED_OUT
    assert code == PROVIDER_TIMEOUT


def test_classify_valueerror_wrapping_timeout_via_context() -> None:
    """ValueError with TimeoutException as implicit __context__ → timed_out."""
    wrapped = _make_chained_timeout_via_context()
    status, code = classify_error(wrapped)
    assert status == STATUS_TIMED_OUT
    assert code == PROVIDER_TIMEOUT


def test_classify_cause_chain_no_infinite_loop() -> None:
    """Cyclic __cause__ chain does not infinite-loop."""
    exc1 = ValueError("a")
    exc2 = ValueError("b")
    exc1.__cause__ = exc2
    exc2.__cause__ = exc1  # cycle
    status, code = classify_error(exc1)
    assert status == STATUS_FAILED
    assert code == UNKNOWN_ERROR


def test_classify_valueerror_wrapping_non_timeout_cause() -> None:
    """ValueError wrapping a non-timeout cause → not timed_out."""
    wrapped = _make_chained_connect_error_via_cause()
    status, code = classify_error(wrapped)
    assert status == STATUS_FAILED
    assert code == "generation_provider_unavailable"


# ============================================================================ #
# 8. record_provider_call: budget_exceeded → failed (not canceled)              #
# ============================================================================ #

def test_record_provider_call_budget_exceeded_is_failed(db_session) -> None:
    """lesson_budget_exceeded through record_provider_call records failed."""
    ws = _ws(db_session)
    run = _run(db_session, ws)

    def fake_call():
        raise ValueError("lesson_budget_exceeded")

    with pytest.raises(ValueError, match="lesson_budget_exceeded"):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=fake_call,
        )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "lesson_budget_exceeded"


# ============================================================================ #
# 9. Usage and ordinal correctness (via real call_provider)                     #
# ============================================================================ #

def test_usage_recorded_correctly(db_session) -> None:
    """Usage tokens are recorded exactly as reported by the provider."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=lambda *a, **kw: _fake_provider_response(
        usage_input=1234, usage_output=567,
    )):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
        )

    pc = db_session.scalar(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    )
    assert pc.input_tokens == 1234
    assert pc.output_tokens == 567
    assert pc.latency_ms is not None and pc.latency_ms >= 0
    assert pc.completed_at is not None


def test_ordinal_monotonic_across_phases(db_session) -> None:
    """Ordinal is monotonic across different phases within the same owner."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", side_effect=lambda *a, **kw: _fake_provider_response()):
        for phase in ["plan", "generation", "repair"]:
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-flash", phase=phase,
                call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
        .order_by(ProviderCall.ordinal)
    ))
    assert [c.ordinal for c in calls] == [0, 1, 2]
    assert [c.phase for c in calls] == ["plan", "generation", "repair"]


# ============================================================================ #
# 10. Provider stub call count                                                  #
# ============================================================================ #

def test_provider_stub_called_exactly_once_per_record(db_session) -> None:
    """The provider stub is called exactly once per record_provider_call invocation."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()
    call_count = 0

    def fake_post(*a, **kw):
        nonlocal call_count
        call_count += 1
        return _fake_provider_response()

    with patch("httpx.post", side_effect=fake_post):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="generation",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
        )
    assert call_count == 1

    with patch("httpx.post", side_effect=fake_post):
        record_provider_call(
            db_session, workspace_id=ws.id, agent_run_id=run.id,
            provider="deepseek", model="deepseek-v4-flash", phase="repair",
            call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
        )
    assert call_count == 2  # two calls total


def test_provider_stub_not_called_on_recorder_error(db_session) -> None:
    """If the recorder fails (invalid phase), the stub is never called."""
    ws = _ws(db_session)
    call_count = 0

    def stub():
        nonlocal call_count
        call_count += 1
        return ({}, {})

    with pytest.raises(ValueError, match="unknown_provider_call_phase"):
        record_provider_call(
            db_session, workspace_id=ws.id,
            provider="deepseek", model="deepseek-v4-flash",
            phase="invalid_phase", call_fn=stub,
        )
    assert call_count == 0


# ============================================================================ #
# 11. OCR Fix 1: empty choices=[] → stable ValueError via real helpers          #
# ============================================================================ #

def _fake_empty_choices_response():
    """Build a fake httpx.Response with choices=[] (HTTP 200, valid JSON)."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 0},
    }
    resp.raise_for_status = MagicMock()
    return resp


def test_rag_answer_empty_choices_via_real_helper(db_session) -> None:
    """RAG Answer _generate: choices=[] → ValueError('invalid_model_output'),
    ProviderCall records failed with error_code='invalid_model_output'."""
    from learn_platform_api.services.answers import _generate

    ws = _ws(db_session)
    trace = _trace(db_session, ws)
    settings = _make_settings()

    _gen_latency = [0]
    def _call_generate_for_recorder(messages):
        result, usage, latency = _generate(settings, messages)
        _gen_latency[0] = latency
        return result, usage

    with patch("httpx.post", return_value=_fake_empty_choices_response()):
        with pytest.raises(ValueError, match="invalid_model_output"):
            record_provider_call(
                db_session, workspace_id=ws.id, rag_answer_trace_id=trace.id,
                provider="deepseek", model="deepseek-v4-flash", phase="answer",
                call_fn=lambda: _call_generate_for_recorder([{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.rag_answer_trace_id == trace.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "invalid_model_output"


def test_course_generation_empty_choices_via_real_helper(db_session) -> None:
    """Course call_provider: choices=[] → ValueError('generation_provider_unavailable'),
    ProviderCall records failed with error_code='generation_provider_unavailable'."""
    from learn_platform_api.services.course_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", return_value=_fake_empty_choices_response()):
        with pytest.raises(ValueError, match="generation_provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-flash", phase="generation",
                call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "generation_provider_unavailable"


def test_practice_call_provider_empty_choices_via_real_helper(db_session) -> None:
    """Practice call_provider: choices=[] → ValueError('provider_unavailable'),
    ProviderCall records failed with error_code='provider_unavailable'."""
    from learn_platform_api.services.practice_generation import call_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", return_value=_fake_empty_choices_response()):
        with pytest.raises(ValueError, match="provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-flash", phase="generation",
                call_fn=lambda: call_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "provider_unavailable"


def test_practice_call_practice_provider_empty_choices_via_real_helper(db_session) -> None:
    """Practice call_practice_provider: choices=[] → ValueError('provider_unavailable'),
    ProviderCall records failed with error_code='provider_unavailable'."""
    from learn_platform_api.services.practice_generation import call_practice_provider

    ws = _ws(db_session)
    run = _run(db_session, ws)
    settings = _make_settings()

    with patch("httpx.post", return_value=_fake_empty_choices_response()):
        with pytest.raises(ValueError, match="provider_unavailable"):
            record_provider_call(
                db_session, workspace_id=ws.id, agent_run_id=run.id,
                provider="deepseek", model="deepseek-v4-pro", phase="generation",
                call_fn=lambda: call_practice_provider(settings, [{"role": "user", "content": "test"}]),
            )

    calls = list(db_session.scalars(
        select(ProviderCall).where(ProviderCall.agent_run_id == run.id)
    ))
    assert len(calls) == 1
    assert calls[0].status == STATUS_FAILED
    assert calls[0].error_code == "provider_unavailable"


# ============================================================================ #
# Fix 3: Course lesson owner commit — replaced by acceptance test              #
# ============================================================================ #
# The old test_course_lesson_owner_commit_is_minimal manually replayed the
# product's create-AgentRun/commit/create-authorization/rollback sequence
# in the test, rather than calling the real _execute_lesson_generation().
# It has been replaced by test_acceptance_evidence_course_owner.py which
# calls the real service.
