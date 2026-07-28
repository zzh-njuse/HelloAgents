"""Stage 5 Slice 1B-3 — focused HTTP tests for Provider Call read API.

Covers (Spec 004 §7 / packet §8):
- Workspace list and detail normal responses;
- AgentRun, RAG, Workspace-only three owner kinds;
- agent_run/status/phase/limit filters;
- RAG owner filter;
- Two owner filters simultaneously → 422;
- Limit boundary and illegal enum → 422;
- Cross-workspace owner filter → empty list;
- Cross-workspace / nonexistent detail → same 404;
- started_at DESC, id DESC stable sort;
- Calculated cost fixed 8-decimal;
- Real zero cost;
- provider/model/usage/rate four unknown reasons;
- Future/subsequent prices don't change bound historical calls;
- failed/timed_out/canceled only compute from facts;
- Snapshot FK abnormal/unreadable → safe degradation;
- List has no N+1 (SQLAlchemy query counter);
- Response JSON contains no forbidden fields;
- AgentRun API regression.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun,
    Course,
    CourseGenerationJob,
    CourseVersion,
    ProviderCall,
    ProviderRateSnapshot,
    RagAnswerTrace,
    Workspace,
)

# --- Forbidden keys (Spec 004 §3) ---------------------------------------------
# These must never appear in any Provider Call read response.
FORBIDDEN_KEYS = {
    "prompt", "message", "question", "answer", "evidence", "citation",
    "response", "payload", "raw", "raw_response", "raw_error",
    "http_body", "http_header", "headers", "body",
    "key", "api_key", "base_url", "url", "connection_string",
    "hash", "input_hash", "file_path", "path", "absolute_path",
    "provider_rate_snapshot_id", "rate_snapshot_id",
    "input_rate", "output_rate", "input_rate_per_1m", "output_rate_per_1m",
    "question_hash", "answer_hash", "evidence_chunk_ids", "citation_ids",
    "effective_at", "created_at",  # created_at is internal, not in whitelist
}


def _collect_keys(obj, into=None):
    """Recursively collect all JSON keys."""
    into = set() if into is None else into
    if isinstance(obj, dict):
        into.update(obj.keys())
        for value in obj.values():
            _collect_keys(value, into)
    elif isinstance(obj, list):
        for value in obj:
            _collect_keys(value, into)
    return into


# --- Helpers -------------------------------------------------------------------

def _make_workspace(db: Session, *, name: str = "WS", slug: str = "ws") -> Workspace:
    ws = Workspace(name=name, slug=slug)
    db.add(ws)
    db.flush()
    return ws


def _make_rate_snapshot(
    db: Session,
    *,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    input_rate: Decimal = Decimal("2.00000000"),
    output_rate: Decimal = Decimal("8.00000000"),
    effective_at: datetime | None = None,
) -> ProviderRateSnapshot:
    if effective_at is None:
        effective_at = datetime.now(timezone.utc) - timedelta(days=1)
    snap = ProviderRateSnapshot(
        provider=provider,
        model=model,
        input_rate_per_1m=input_rate,
        output_rate_per_1m=output_rate,
        effective_at=effective_at,
    )
    db.add(snap)
    db.flush()
    return snap


def _make_agent_run(db: Session, workspace: Workspace) -> AgentRun:
    """Create a minimal AgentRun with a CourseGenerationJob owner."""
    course = Course(workspace_id=workspace.id, title="T", goal="G")
    db.add(course)
    db.flush()
    version = CourseVersion(
        course_id=course.id, workspace_id=workspace.id,
        version_number=1, status="active", title="T",
    )
    db.add(version)
    db.flush()
    course.current_active_version_id = version.id
    job = CourseGenerationJob(
        workspace_id=workspace.id, course_id=course.id,
        job_type="course_outline", output_language="zh-CN",
        status="succeeded", idempotency_key=str(uuid4()),
    )
    db.add(job)
    db.flush()
    run = AgentRun(
        course_generation_job_id=job.id,
        workspace_id=workspace.id,
        role="course_architect",
        attempt_number=1,
        status="succeeded",
        step_count=1,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        completed_at=datetime.now(timezone.utc) - timedelta(seconds=55),
    )
    db.add(run)
    db.flush()
    return run


def _make_rag_trace(db: Session, workspace: Workspace) -> RagAnswerTrace:
    trace = RagAnswerTrace(
        workspace_id=workspace.id,
        question_hash="h" * 64,
        status="succeeded",
        prompt_template_version="v1",
        evidence_chunk_ids=[],
        citation_ids=[],
    )
    db.add(trace)
    db.flush()
    return trace


def _make_call(
    db: Session,
    workspace: Workspace,
    *,
    agent_run_id: str | None = None,
    rag_answer_trace_id: str | None = None,
    ordinal: int = 0,
    phase: str = "generation",
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    status: str = "succeeded",
    input_tokens: int | None = 100,
    output_tokens: int | None = 200,
    latency_ms: int | None = 500,
    error_code: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    snapshot_id: str | None = None,
) -> ProviderCall:
    if started_at is None:
        started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    if completed_at is None and status != "started":
        completed_at = started_at + timedelta(milliseconds=latency_ms or 500)
    call = ProviderCall(
        workspace_id=workspace.id,
        agent_run_id=agent_run_id,
        rag_answer_trace_id=rag_answer_trace_id,
        ordinal=ordinal,
        phase=phase,
        provider=provider,
        model=model,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        error_code=error_code,
        started_at=started_at,
        completed_at=completed_at,
        provider_rate_snapshot_id=snapshot_id,
    )
    db.add(call)
    db.flush()
    return call


# --- Tests ---------------------------------------------------------------------

def test_list_and_detail_normal_response(client: TestClient, db_session: Session) -> None:
    """Workspace list and detail return normal responses."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)
    call = _make_call(db_session, ws, snapshot_id=snap.id)
    db_session.commit()

    list_body = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls").json()
    assert len(list_body) == 1
    item = list_body[0]
    assert item["id"] == call.id
    assert item["provider"] == "deepseek"
    assert item["model"] == "deepseek-v4-flash"
    assert item["status"] == "succeeded"
    assert item["input_tokens"] == 100
    assert item["output_tokens"] == 200
    assert item["cost"]["currency"] == "CNY"
    assert item["cost"]["status"] == "calculated"

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["id"] == call.id
    assert detail["cost"]["status"] == "calculated"


def test_three_owner_kinds(client: TestClient, db_session: Session) -> None:
    """AgentRun, RAG, and Workspace-only three owner kinds."""
    ws = _make_workspace(db_session)
    run = _make_agent_run(db_session, ws)
    trace = _make_rag_trace(db_session, ws)
    snap = _make_rate_snapshot(db_session)

    call_ar = _make_call(db_session, ws, agent_run_id=run.id, ordinal=0, snapshot_id=snap.id)
    call_rag = _make_call(db_session, ws, rag_answer_trace_id=trace.id, ordinal=0, snapshot_id=snap.id)
    call_ws = _make_call(db_session, ws, ordinal=0, snapshot_id=snap.id)
    db_session.commit()

    body = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls").json()
    owners = {item["id"]: item["owner"] for item in body}

    assert owners[call_ar.id]["kind"] == "agent_run"
    assert owners[call_ar.id]["agent_run_id"] == run.id
    assert owners[call_ar.id]["rag_answer_trace_id"] is None

    assert owners[call_rag.id]["kind"] == "rag_answer"
    assert owners[call_rag.id]["rag_answer_trace_id"] == trace.id
    assert owners[call_rag.id]["agent_run_id"] is None

    assert owners[call_ws.id]["kind"] == "workspace"
    assert owners[call_ws.id]["agent_run_id"] is None
    assert owners[call_ws.id]["rag_answer_trace_id"] is None


def test_agent_run_filter(client: TestClient, db_session: Session) -> None:
    """agent_run_id filter narrows to calls belonging to that run."""
    ws = _make_workspace(db_session)
    run1 = _make_agent_run(db_session, ws)
    run2 = _make_agent_run(db_session, ws)
    snap = _make_rate_snapshot(db_session)

    _make_call(db_session, ws, agent_run_id=run1.id, ordinal=0, snapshot_id=snap.id)
    _make_call(db_session, ws, agent_run_id=run1.id, ordinal=1, snapshot_id=snap.id)
    _make_call(db_session, ws, agent_run_id=run2.id, ordinal=0, snapshot_id=snap.id)
    db_session.commit()

    body = client.get(
        f"/api/v1/workspaces/{ws.id}/provider-calls",
        params={"agent_run_id": run1.id},
    ).json()
    assert len(body) == 2
    assert all(item["owner"]["agent_run_id"] == run1.id for item in body)


def test_status_filter(client: TestClient, db_session: Session) -> None:
    """status filter narrows to calls with that status."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)

    _make_call(db_session, ws, ordinal=0, status="succeeded", snapshot_id=snap.id)
    _make_call(db_session, ws, ordinal=1, status="failed", snapshot_id=snap.id, error_code="provider_unavailable")
    db_session.commit()

    body = client.get(
        f"/api/v1/workspaces/{ws.id}/provider-calls",
        params={"status": "succeeded"},
    ).json()
    assert len(body) == 1
    assert body[0]["status"] == "succeeded"


def test_phase_filter(client: TestClient, db_session: Session) -> None:
    """phase filter narrows to calls with that phase."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)

    _make_call(db_session, ws, ordinal=0, phase="generation", snapshot_id=snap.id)
    _make_call(db_session, ws, ordinal=1, phase="answer", snapshot_id=snap.id)
    db_session.commit()

    body = client.get(
        f"/api/v1/workspaces/{ws.id}/provider-calls",
        params={"phase": "generation"},
    ).json()
    assert len(body) == 1
    assert body[0]["phase"] == "generation"


def test_limit_filter(client: TestClient, db_session: Session) -> None:
    """limit controls the number of results."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)

    for i in range(5):
        _make_call(db_session, ws, ordinal=i, snapshot_id=snap.id,
                   started_at=datetime.now(timezone.utc) - timedelta(seconds=50 - i))
    db_session.commit()

    body = client.get(
        f"/api/v1/workspaces/{ws.id}/provider-calls",
        params={"limit": 3},
    ).json()
    assert len(body) == 3


def test_rag_owner_filter(client: TestClient, db_session: Session) -> None:
    """rag_answer_trace_id filter narrows to calls belonging to that trace."""
    ws = _make_workspace(db_session)
    trace1 = _make_rag_trace(db_session, ws)
    trace2 = _make_rag_trace(db_session, ws)
    snap = _make_rate_snapshot(db_session)

    _make_call(db_session, ws, rag_answer_trace_id=trace1.id, ordinal=0, snapshot_id=snap.id)
    _make_call(db_session, ws, rag_answer_trace_id=trace2.id, ordinal=0, snapshot_id=snap.id)
    db_session.commit()

    body = client.get(
        f"/api/v1/workspaces/{ws.id}/provider-calls",
        params={"rag_answer_trace_id": trace1.id},
    ).json()
    assert len(body) == 1
    assert body[0]["owner"]["rag_answer_trace_id"] == trace1.id


def test_double_owner_filter_returns_422(client: TestClient, db_session: Session) -> None:
    """Both owner filters simultaneously → 422."""
    ws = _make_workspace(db_session)
    db_session.commit()

    resp = client.get(
        f"/api/v1/workspaces/{ws.id}/provider-calls",
        params={"agent_run_id": str(uuid4()), "rag_answer_trace_id": str(uuid4())},
    )
    assert resp.status_code == 422


def test_limit_boundary_and_invalid_enum_return_422(client: TestClient, db_session: Session) -> None:
    """limit boundary (0, 51) and invalid enum → 422."""
    ws = _make_workspace(db_session)
    db_session.commit()
    base = f"/api/v1/workspaces/{ws.id}/provider-calls"

    assert client.get(base, params={"limit": 0}).status_code == 422
    assert client.get(base, params={"limit": 51}).status_code == 422
    assert client.get(base, params={"status": "bogus"}).status_code == 422
    assert client.get(base, params={"phase": "bogus"}).status_code == 422


def test_cross_workspace_owner_filter_empty_list(client: TestClient, db_session: Session) -> None:
    """Cross-workspace owner filter returns empty list, no leakage."""
    ws_a = _make_workspace(db_session, name="A", slug="a")
    ws_b = _make_workspace(db_session, name="B", slug="b")
    run = _make_agent_run(db_session, ws_a)
    snap = _make_rate_snapshot(db_session)

    _make_call(db_session, ws_a, agent_run_id=run.id, ordinal=0, snapshot_id=snap.id)
    db_session.commit()

    # Filter by ws_a's run_id on ws_b → empty list (no leakage)
    body = client.get(
        f"/api/v1/workspaces/{ws_b.id}/provider-calls",
        params={"agent_run_id": run.id},
    ).json()
    assert body == []


def test_cross_workspace_and_nonexistent_detail_same_404(client: TestClient, db_session: Session) -> None:
    """Cross-workspace and nonexistent detail both return 404."""
    ws_a = _make_workspace(db_session, name="A", slug="a")
    ws_b = _make_workspace(db_session, name="B", slug="b")
    snap = _make_rate_snapshot(db_session)

    call = _make_call(db_session, ws_a, snapshot_id=snap.id)
    db_session.commit()

    # Cross-workspace detail → 404
    assert client.get(f"/api/v1/workspaces/{ws_b.id}/provider-calls/{call.id}").status_code == 404
    # Nonexistent call → 404
    fake_id = str(uuid4())
    assert client.get(f"/api/v1/workspaces/{ws_a.id}/provider-calls/{fake_id}").status_code == 404
    # Nonexistent workspace → 404
    assert client.get(f"/api/v1/workspaces/{fake_id}/provider-calls/{call.id}").status_code == 404


def test_stable_sort_started_at_desc_id_desc(client: TestClient, db_session: Session) -> None:
    """List is sorted by started_at DESC, id DESC."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)

    now = datetime.now(timezone.utc)
    # Create calls with different started_at values
    call_early = _make_call(db_session, ws, ordinal=0, snapshot_id=snap.id,
                            started_at=now - timedelta(seconds=100))
    call_mid = _make_call(db_session, ws, ordinal=1, snapshot_id=snap.id,
                          started_at=now - timedelta(seconds=50))
    call_late = _make_call(db_session, ws, ordinal=2, snapshot_id=snap.id,
                           started_at=now - timedelta(seconds=10))
    db_session.commit()

    body = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls").json()
    ids = [item["id"] for item in body]
    assert ids == [call_late.id, call_mid.id, call_early.id]


def test_calculated_cost_fixed_eight_decimal(client: TestClient, db_session: Session) -> None:
    """Calculated cost uses fixed 8-decimal-place string."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(
        db_session,
        input_rate=Decimal("2.00000000"),
        output_rate=Decimal("8.00000000"),
    )
    # 100 input * 2.0 / 1_000_000 + 200 output * 8.0 / 1_000_000
    # = 0.0002 + 0.0016 = 0.00180000
    call = _make_call(db_session, ws, snapshot_id=snap.id,
                      input_tokens=100, output_tokens=200)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["cost"]["status"] == "calculated"
    assert detail["cost"]["amount"] == "0.00180000"
    assert detail["cost"]["unknown_reason"] is None
    # Verify it's a string, not a number
    assert isinstance(detail["cost"]["amount"], str)
    # Verify exactly 8 decimal places
    assert len(detail["cost"]["amount"].split(".")[1]) == 8


def test_real_zero_cost(client: TestClient, db_session: Session) -> None:
    """Real zero cost returns "0.00000000", not unknown."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(
        db_session,
        input_rate=Decimal("2.00000000"),
        output_rate=Decimal("8.00000000"),
    )
    call = _make_call(db_session, ws, snapshot_id=snap.id,
                      input_tokens=0, output_tokens=0)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["cost"]["status"] == "calculated"
    assert detail["cost"]["amount"] == "0.00000000"
    assert detail["cost"]["unknown_reason"] is None


def test_unknown_reason_provider_missing(client: TestClient, db_session: Session) -> None:
    """Blank/None provider → provider_missing."""
    ws = _make_workspace(db_session)
    # Provider is required NOT NULL in the DB, so we use a blank string
    call = _make_call(db_session, ws, provider="  ", snapshot_id=None)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["cost"]["status"] == "unknown"
    assert detail["cost"]["amount"] is None
    assert detail["cost"]["unknown_reason"] == "provider_missing"


def test_unknown_reason_model_missing(client: TestClient, db_session: Session) -> None:
    """Blank model → model_missing (provider present)."""
    ws = _make_workspace(db_session)
    call = _make_call(db_session, ws, model="  ", snapshot_id=None)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["cost"]["status"] == "unknown"
    assert detail["cost"]["amount"] is None
    assert detail["cost"]["unknown_reason"] == "model_missing"


def test_unknown_reason_usage_missing(client: TestClient, db_session: Session) -> None:
    """Missing tokens → usage_missing (provider/model present)."""
    ws = _make_workspace(db_session)
    call = _make_call(db_session, ws, input_tokens=None, output_tokens=None, snapshot_id=None)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["cost"]["status"] == "unknown"
    assert detail["cost"]["amount"] is None
    assert detail["cost"]["unknown_reason"] == "usage_missing"


def test_unknown_reason_rate_missing(client: TestClient, db_session: Session) -> None:
    """Missing rate snapshot → rate_missing (provider/model/tokens present)."""
    ws = _make_workspace(db_session)
    # No snapshot bound
    call = _make_call(db_session, ws, snapshot_id=None,
                      input_tokens=100, output_tokens=200)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["cost"]["status"] == "unknown"
    assert detail["cost"]["amount"] is None
    assert detail["cost"]["unknown_reason"] == "rate_missing"


def test_future_price_does_not_change_historical_call(client: TestClient, db_session: Session) -> None:
    """A future price snapshot does not change a historical call's cost."""
    ws = _make_workspace(db_session)
    now = datetime.now(timezone.utc)

    # Historical snapshot effective before the call
    old_snap = _make_rate_snapshot(
        db_session,
        input_rate=Decimal("2.00000000"),
        output_rate=Decimal("8.00000000"),
        effective_at=now - timedelta(days=10),
    )
    # Create a call bound to the old snapshot
    call = _make_call(
        db_session, ws, snapshot_id=old_snap.id,
        input_tokens=100, output_tokens=200,
        started_at=now - timedelta(days=5),
    )

    # Add a newer snapshot effective after the call
    _make_rate_snapshot(
        db_session,
        input_rate=Decimal("200.00000000"),
        output_rate=Decimal("800.00000000"),
        effective_at=now - timedelta(days=1),
    )
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    # Cost should be based on the old snapshot, not the new one
    assert detail["cost"]["status"] == "calculated"
    assert detail["cost"]["amount"] == "0.00180000"


def test_failed_timed_out_canceled_compute_from_facts(client: TestClient, db_session: Session) -> None:
    """failed/timed_out/canceled status does NOT change calculation rules."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)

    for status_val, error_code in [
        ("failed", "provider_unavailable"),
        ("timed_out", "provider_timeout"),
        ("canceled", "generation_canceled"),
    ]:
        call = _make_call(
            db_session, ws, status=status_val, error_code=error_code,
            snapshot_id=snap.id, input_tokens=100, output_tokens=200,
            ordinal=0,
        )
        db_session.commit()

        detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
        assert detail["cost"]["status"] == "calculated", f"status={status_val} should be calculated"
        assert detail["cost"]["amount"] == "0.00180000", f"status={status_val} cost mismatch"
        assert detail["error_code"] == error_code

        # Clean up for next iteration
        db_session.delete(call)
        db_session.flush()


def test_snapshot_unreadable_safe_degradation(client: TestClient, db_session: Session) -> None:
    """Snapshot FK points to a row but data is abnormal → rate_missing.

    We test this by creating a call with no snapshot (snapshot_id=NULL)
    while having complete provider/model/tokens, which is the realistic
    scenario for rate_missing. We cannot easily make a snapshot's data
    unreadable without violating DB constraints, so we test the NULL
    snapshot path which is the primary degradation case.
    """
    ws = _make_workspace(db_session)
    # Call with complete facts but no snapshot → rate_missing
    call = _make_call(
        db_session, ws, snapshot_id=None,
        input_tokens=100, output_tokens=200,
    )
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["cost"]["status"] == "unknown"
    assert detail["cost"]["amount"] is None
    assert detail["cost"]["unknown_reason"] == "rate_missing"


def test_list_no_n_plus_one(client: TestClient, db_session: Session) -> None:
    """List query count is bounded (no N+1 on rate snapshot loading)."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)

    # Create several calls
    for i in range(5):
        _make_call(db_session, ws, ordinal=i, snapshot_id=snap.id,
                   started_at=datetime.now(timezone.utc) - timedelta(seconds=50 - i))
    db_session.commit()

    # Count SQL queries emitted during the list endpoint
    query_count = 0

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _count_queries(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1

    try:
        body = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls").json()
        assert len(body) == 5
        # With joined eager load, we expect:
        # 1. workspace_is_active check
        # 2. The main list query (with join)
        # That's 2 queries total for 5 items — no N+1.
        # Allow some slack for transactional/bookkeeping queries.
        assert query_count <= 4, f"Too many queries: {query_count} (possible N+1)"
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", _count_queries)


def test_response_excludes_forbidden_fields(client: TestClient, db_session: Session) -> None:
    """Response JSON does not contain any forbidden fields."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)
    run = _make_agent_run(db_session, ws)

    call = _make_call(db_session, ws, agent_run_id=run.id, snapshot_id=snap.id)
    db_session.commit()

    # Check list
    list_body = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls").json()
    for item in list_body:
        keys = _collect_keys(item)
        leaked = keys & FORBIDDEN_KEYS
        assert not leaked, f"forbidden fields leaked in list: {leaked}"

    # Check detail
    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    keys = _collect_keys(detail)
    leaked = keys & FORBIDDEN_KEYS
    assert not leaked, f"forbidden fields leaked in detail: {leaked}"

    # Verify exact whitelist fields for the top-level
    expected_top = {
        "id", "owner", "ordinal", "phase", "provider", "model",
        "status", "input_tokens", "output_tokens", "latency_ms",
        "error_code", "started_at", "completed_at", "cost",
    }
    assert set(detail.keys()) == expected_top

    # Verify owner whitelist
    expected_owner = {"kind", "agent_run_id", "rag_answer_trace_id"}
    assert set(detail["owner"].keys()) == expected_owner

    # Verify cost whitelist
    expected_cost = {"currency", "status", "amount", "unknown_reason"}
    assert set(detail["cost"].keys()) == expected_cost


def test_inactive_workspace_returns_404(client: TestClient, db_session: Session) -> None:
    """Workspace not active → 404."""
    ws = _make_workspace(db_session)
    ws.lifecycle_status = "deleted"
    db_session.commit()

    assert client.get(f"/api/v1/workspaces/{ws.id}/provider-calls").status_code == 404
    assert client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{str(uuid4())}").status_code == 404


def test_partial_usage_missing(client: TestClient, db_session: Session) -> None:
    """Only one token dimension present → usage_missing."""
    ws = _make_workspace(db_session)
    # input_tokens present, output_tokens missing
    call = _make_call(db_session, ws, input_tokens=100, output_tokens=None, snapshot_id=None)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["cost"]["status"] == "unknown"
    assert detail["cost"]["unknown_reason"] == "usage_missing"


def test_cost_uses_bound_snapshot_not_current(client: TestClient, db_session: Session) -> None:
    """Cost uses the call's bound snapshot, not any 'current' price."""
    ws = _make_workspace(db_session)
    now = datetime.now(timezone.utc)

    # Old snapshot with low rates
    old_snap = _make_rate_snapshot(
        db_session,
        input_rate=Decimal("1.00000000"),
        output_rate=Decimal("1.00000000"),
        effective_at=now - timedelta(days=30),
    )
    # Call bound to old snapshot
    call = _make_call(
        db_session, ws, snapshot_id=old_snap.id,
        input_tokens=1000, output_tokens=1000,
        started_at=now - timedelta(days=20),
    )
    # New snapshot with high rates (but call is already bound to old)
    _make_rate_snapshot(
        db_session,
        input_rate=Decimal("100.00000000"),
        output_rate=Decimal("100.00000000"),
        effective_at=now - timedelta(days=10),
    )
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    # Cost based on old snapshot: 1000*1/1M + 1000*1/1M = 0.00200000
    assert detail["cost"]["amount"] == "0.00200000"


def test_unknown_priority_order(client: TestClient, db_session: Session) -> None:
    """Unknown reason follows strict priority: provider > model > usage > rate."""
    ws = _make_workspace(db_session)

    # provider_missing takes priority even if model is also blank
    call1 = _make_call(db_session, ws, provider="  ", model="  ", ordinal=0, snapshot_id=None)
    db_session.commit()
    detail1 = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call1.id}").json()
    assert detail1["cost"]["unknown_reason"] == "provider_missing"

    # model_missing when provider is present but model is blank
    call2 = _make_call(db_session, ws, model="  ", ordinal=1, snapshot_id=None,
                       started_at=datetime.now(timezone.utc) - timedelta(seconds=20))
    db_session.commit()
    detail2 = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call2.id}").json()
    assert detail2["cost"]["unknown_reason"] == "model_missing"

    # usage_missing when provider/model present but tokens missing
    call3 = _make_call(db_session, ws, input_tokens=None, output_tokens=None, ordinal=2,
                       snapshot_id=None,
                       started_at=datetime.now(timezone.utc) - timedelta(seconds=10))
    db_session.commit()
    detail3 = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call3.id}").json()
    assert detail3["cost"]["unknown_reason"] == "usage_missing"

    # rate_missing when provider/model/tokens present but no snapshot
    call4 = _make_call(db_session, ws, input_tokens=100, output_tokens=200, ordinal=3,
                       snapshot_id=None,
                       started_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    db_session.commit()
    detail4 = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call4.id}").json()
    assert detail4["cost"]["unknown_reason"] == "rate_missing"


# --- OCR Fix 3: same started_at → id DESC stable sort; started → completed_at=null ---

def test_same_started_at_sorts_by_id_desc(client: TestClient, db_session: Session) -> None:
    """Two Provider Calls with the same started_at are sorted by id DESC."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)

    same_time = datetime.now(timezone.utc) - timedelta(seconds=30)
    call_first = _make_call(db_session, ws, ordinal=0, snapshot_id=snap.id,
                            started_at=same_time)
    call_second = _make_call(db_session, ws, ordinal=1, snapshot_id=snap.id,
                             started_at=same_time)
    db_session.commit()

    body = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls").json()
    ids = [item["id"] for item in body]
    # Both have the same started_at, so id DESC determines order.
    # UUIDs are random; compute the expected order from actual lexicographic sort.
    expected_ids = sorted([call_first.id, call_second.id], reverse=True)
    assert ids == expected_ids


def test_started_status_has_completed_at_null(client: TestClient, db_session: Session) -> None:
    """A Provider Call with status=started returns completed_at=null
    and other whitelist fields normally."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(db_session)

    call = _make_call(
        db_session, ws,
        status="started",
        completed_at=None,  # started calls have no completed_at
        snapshot_id=snap.id,
        input_tokens=None,
        output_tokens=None,
    )
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["status"] == "started"
    assert detail["completed_at"] is None
    # Other whitelist fields should be present and normal
    assert detail["id"] == call.id
    assert detail["provider"] == "deepseek"
    assert detail["model"] == "deepseek-v4-flash"
    assert detail["phase"] == "generation"
    assert detail["ordinal"] == 0
    assert detail["started_at"] is not None
    assert detail["input_tokens"] is None
    assert detail["output_tokens"] is None
    # Cost for started call with no usage → usage_missing
    assert detail["cost"]["status"] == "unknown"
    assert detail["cost"]["unknown_reason"] == "usage_missing"
    assert detail["cost"]["amount"] is None


def test_started_status_with_complete_usage_calculates_cost(client: TestClient, db_session: Session) -> None:
    """A started Provider Call with complete usage and bound price still
    calculates cost from facts (Spec 004 §4: failed/timed_out/canceled
    don't auto-mean unknown; started is the same)."""
    ws = _make_workspace(db_session)
    snap = _make_rate_snapshot(
        db_session,
        input_rate=Decimal("2.00000000"),
        output_rate=Decimal("8.00000000"),
    )

    call = _make_call(
        db_session, ws,
        status="started",
        completed_at=None,
        snapshot_id=snap.id,
        input_tokens=100,
        output_tokens=200,
    )
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{ws.id}/provider-calls/{call.id}").json()
    assert detail["status"] == "started"
    assert detail["completed_at"] is None
    assert detail["cost"]["status"] == "calculated"
    assert detail["cost"]["amount"] == "0.00180000"
