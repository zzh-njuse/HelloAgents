"""Stage 5 Part 2 Slice 2A — RAG Trace acceptance evidence.

Replaces the old test_rag_trace_succeeded_is_committed and
test_rag_trace_failed_is_committed which manually created a Trace,
assigned status, and committed — never calling answer_question().

New tests call the REAL answer_question() service, monkeypatching only
the low-level external boundaries (retrieval, embedding, provider HTTP).
The service itself creates and finalizes the RagAnswerTrace.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from learn_platform_api.db.models import (
    ProviderCall,
    RagAnswerTrace,
    Workspace,
)
from learn_platform_api.services.provider_call_recorder import (
    STATUS_SUCCEEDED,
    STATUS_FAILED,
    STATUS_TIMED_OUT,
    PROVIDER_TIMEOUT,
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


def _make_settings(**overrides):
    """Build a Settings object with test defaults."""
    from learn_platform_api.settings import Settings
    defaults = dict(
        product_generation_api_key="test-key",
        product_generation_base_url="https://fake.example.com",
        product_generation_model="deepseek-v4-flash",
        product_generation_provider="deepseek",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _fake_provider_response(usage_input=100, usage_output=50, content=None):
    """Build a fake httpx.Response that looks like a provider JSON response."""
    if content is None:
        content = json.dumps({"queries": ["q1"]})
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": usage_input, "completion_tokens": usage_output},
    }
    resp.raise_for_status = MagicMock()
    return resp


def _fake_retrieval_result(text="Evidence text", chunk_id="chunk-1",
                            document_id="doc-1", version_id="ver-1",
                            document_name="Test Doc", heading_path=None,
                            score=0.95):
    """Build a fake RetrievalResult that answer_question() will accept."""
    from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
    return RetrievalResult(
        score=score,
        text=text,
        citation=CitationRead(
            document_id=document_id,
            document_version_id=version_id,
            chunk_id=chunk_id,
            document_name=document_name,
            heading_path=heading_path or [],
            start_offset=0,
            end_offset=len(text),
        ),
    )


# ============================================================================ #
# RAG Trace via real answer_question() — success path                          #
# ============================================================================ #

def test_rag_trace_succeeded_via_answer_question(db_session) -> None:
    """RAG answer success: answer_question() creates and commits a RagAnswerTrace
    with status='succeeded'. Verified from a new session.

    Only monkeypatches: retrieve (retrieval), embed_texts (embedding),
    httpx.post (provider HTTP). The service itself creates and finalizes
    the Trace — we never assign trace.status directly.
    """
    from learn_platform_api.services.answers import answer_question

    ws = _ws(db_session)
    settings = _make_settings()

    answer_content = json.dumps({
        "claims": [{"text": "fact", "citation_ids": ["c1"]}],
        "limitations": [],
    })
    fake_result = _fake_retrieval_result(text="Some evidence text")

    with patch("learn_platform_api.services.answers.retrieve") as mock_retrieve, \
         patch("learn_platform_api.services.answers.httpx.post") as mock_post:
        mock_retrieve.return_value = ("query-trace-1", [fake_result])
        mock_post.return_value = _fake_provider_response(
            content=answer_content, usage_input=300, usage_output=150,
        )

        result = answer_question(
            db_session, settings, ws.id, "What is X?", top_k=5,
            document_ids=None,
        )

    # answer_question returns a dict with trace_id and status
    assert result["status"] == "succeeded"
    trace_id = result["trace_id"]

    # Verify from a completely new session — the Trace must be persisted.
    sf = _sf(db_session)
    with sf() as verify_db:
        trace = verify_db.get(RagAnswerTrace, trace_id)
        assert trace is not None
        assert trace.status == "succeeded"
        assert trace.input_tokens is not None
        assert trace.output_tokens is not None
        assert trace.completed_at is not None

        # Also verify Provider Calls for this trace have correct owner and status.
        calls = list(verify_db.scalars(
            select(ProviderCall).where(ProviderCall.rag_answer_trace_id == trace_id)
        ))
        assert len(calls) >= 1
        for call in calls:
            assert call.status == STATUS_SUCCEEDED
            assert call.rag_answer_trace_id == trace_id
            assert call.agent_run_id is None


# ============================================================================ #
# RAG Trace via real answer_question() — failure path                          #
# ============================================================================ #

def test_rag_trace_failed_via_answer_question(db_session) -> None:
    """RAG answer failure: answer_question() creates and commits a RagAnswerTrace
    with status='failed' and stable error_code. Verified from a new session.

    The failure is produced by the real provider helper raising
    httpx.TimeoutException, which _generate converts to
    ValueError("generation_provider_unavailable") from exc.
    answer_question() records the failure and commits the trace.
    """
    import httpx
    from learn_platform_api.services.answers import answer_question

    ws = _ws(db_session)
    settings = _make_settings()

    fake_result = _fake_retrieval_result(text="Some evidence text")

    with patch("learn_platform_api.services.answers.retrieve") as mock_retrieve, \
         patch("learn_platform_api.services.answers.httpx.post") as mock_post:
        mock_retrieve.return_value = ("query-trace-1", [fake_result])
        mock_post.side_effect = httpx.TimeoutException("read timeout")

        with pytest.raises(ValueError, match="generation_provider_unavailable"):
            answer_question(
                db_session, settings, ws.id, "What is X?", top_k=5,
                document_ids=None,
            )

    # Find the trace that was created — it must be failed.
    sf = _sf(db_session)
    with sf() as verify_db:
        # The most recent trace for this workspace
        trace = verify_db.scalar(
            select(RagAnswerTrace)
            .where(RagAnswerTrace.workspace_id == ws.id)
            .order_by(RagAnswerTrace.created_at.desc())
            .limit(1)
        )
        assert trace is not None
        assert trace.status == "failed"
        assert trace.error_code is not None
        assert trace.completed_at is not None

        # Verify the Provider Call for this trace has timed_out status.
        calls = list(verify_db.scalars(
            select(ProviderCall).where(ProviderCall.rag_answer_trace_id == trace.id)
        ))
        assert len(calls) >= 1
        assert calls[0].status == STATUS_TIMED_OUT
        assert calls[0].error_code == PROVIDER_TIMEOUT


# ============================================================================ #
# RAG Trace via real answer_question() — provider unavailable failure          #
# ============================================================================ #

def test_rag_trace_failed_provider_unavailable_via_answer_question(db_session) -> None:
    """RAG answer failure (provider unavailable): answer_question() commits
    a failed trace with error_code='generation_provider_unavailable'."""
    import httpx
    from learn_platform_api.services.answers import answer_question

    ws = _ws(db_session)
    settings = _make_settings()

    fake_result = _fake_retrieval_result(text="Some evidence text")

    with patch("learn_platform_api.services.answers.retrieve") as mock_retrieve, \
         patch("learn_platform_api.services.answers.httpx.post") as mock_post:
        mock_retrieve.return_value = ("query-trace-1", [fake_result])
        mock_post.side_effect = httpx.ConnectError("connection refused")

        with pytest.raises(ValueError, match="generation_provider_unavailable"):
            answer_question(
                db_session, settings, ws.id, "What is X?", top_k=5,
                document_ids=None,
            )

    sf = _sf(db_session)
    with sf() as verify_db:
        trace = verify_db.scalar(
            select(RagAnswerTrace)
            .where(RagAnswerTrace.workspace_id == ws.id)
            .order_by(RagAnswerTrace.created_at.desc())
            .limit(1)
        )
        assert trace is not None
        assert trace.status == "failed"
        assert trace.error_code == "generation_provider_unavailable"
        assert trace.completed_at is not None
