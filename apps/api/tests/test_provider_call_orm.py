"""Stage 5 Slice 1B-1 — Provider Call & CNY rate snapshot ORM tests (Spec 002 / ADR 001).

Runs on SQLite via the shared ``db_session`` fixture. SQLite enforces CHECK and
UNIQUE constraints at write time, so these lock the schema contract that the
calculator alone cannot prove:

- currency is locked to CNY;
- rates, tokens, latency and ordinal are non-negative;
- ``status`` is one of the five allowed values;
- (provider, model, effective_at) is append-only unique;
- ordinal is unique within an AgentRun but not across workspace-only calls;
- a Provider Call binds an immutable rate snapshot;
- a newer rate snapshot never rewrites a historical call's meaning;
- no forbidden prompt / message / response / payload column exists.

ON DELETE CASCADE is NOT exercised here — SQLite does not enforce foreign keys,
so it is proven on Postgres in ``test_provider_call_deletion_postgres.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from learn_platform_api.db.models import (
    AgentRun,
    PracticeJob,
    ProviderCall,
    ProviderRateSnapshot,
    Workspace,
)
from learn_platform_api.services.provider_cost import CURRENCY_CNY, calculate_cost


# --- minimal seed helpers -----------------------------------------------------

def _ws(db_session) -> Workspace:
    ws = Workspace(name="ws", slug="ws")
    db_session.add(ws)
    db_session.flush()
    return ws


def _snapshot(
    db_session,
    *,
    provider: str = "anthropic",
    model: str = "claude-fable-5",
    input_rate: str = "40",
    output_rate: str = "120",
    effective_at: datetime | None = None,
) -> ProviderRateSnapshot:
    snap = ProviderRateSnapshot(
        provider=provider,
        model=model,
        input_rate_per_1m=Decimal(input_rate),
        output_rate_per_1m=Decimal(output_rate),
        effective_at=effective_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(snap)
    db_session.flush()
    return snap


def _call(
    db_session,
    ws: Workspace,
    *,
    ordinal: int = 0,
    phase: str = "generate",
    provider: str = "anthropic",
    model: str = "claude-fable-5",
    status: str = "started",
    agent_run_id: str | None = None,
    snapshot_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
) -> ProviderCall:
    pc = ProviderCall(
        workspace_id=ws.id,
        agent_run_id=agent_run_id,
        ordinal=ordinal,
        phase=phase,
        provider=provider,
        model=model,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        provider_rate_snapshot_id=snapshot_id,
    )
    db_session.add(pc)
    db_session.flush()
    return pc


def _run(db_session, ws: Workspace) -> AgentRun:
    """A minimal but valid AgentRun (satisfies ``ck_agent_runs_one_owner``)."""
    pj = PracticeJob(
        workspace_id=ws.id,
        job_type="generate_set",
        output_language="zh-CN",
        difficulty="standard",
        item_count=1,
        request_hash="0" * 64,
        idempotency_key="run-key",
        attempt_count=0,
    )
    db_session.add(pj)
    db_session.flush()
    ar = AgentRun(
        practice_job_id=pj.id,
        workspace_id=ws.id,
        role="exercise_author",
        attempt_number=1,
        status="succeeded",
    )
    db_session.add(ar)
    db_session.flush()
    return ar


# --- defaults & basic shape ---------------------------------------------------

def test_rate_snapshot_defaults_currency_to_cny_and_ids(db_session) -> None:
    snap = _snapshot(db_session)
    db_session.commit()
    db_session.refresh(snap)
    assert snap.currency == CURRENCY_CNY
    assert isinstance(snap.id, str) and len(snap.id) > 0
    assert snap.created_at is not None
    # Rates round-trip as Decimal (ADR 001 §4.4 — Decimal is the money type).
    assert isinstance(snap.input_rate_per_1m, Decimal)
    assert isinstance(snap.output_rate_per_1m, Decimal)


def test_provider_call_defaults_status_to_started(db_session) -> None:
    ws = _ws(db_session)
    pc = _call(db_session, ws)
    db_session.commit()
    db_session.refresh(pc)
    assert pc.status == "started"
    assert pc.started_at is not None
    assert pc.created_at is not None
    # Unstarted call has no usage / completion yet.
    assert pc.input_tokens is None
    assert pc.output_tokens is None
    assert pc.completed_at is None
    assert pc.provider_rate_snapshot_id is None


def test_provider_call_binds_to_rate_snapshot(db_session) -> None:
    ws = _ws(db_session)
    snap = _snapshot(db_session, input_rate="40", output_rate="120")
    pc = _call(db_session, ws, snapshot_id=snap.id, input_tokens=1500, output_tokens=500)
    db_session.commit()
    db_session.refresh(pc)
    assert pc.provider_rate_snapshot_id == snap.id
    # The bound snapshot's rates are the historical cost facts, retrieved as Decimal.
    bound = db_session.get(ProviderRateSnapshot, pc.provider_rate_snapshot_id)
    assert bound.input_rate_per_1m == Decimal("40")
    assert bound.output_rate_per_1m == Decimal("120")


def test_new_rate_snapshot_does_not_rewrite_historical_call(db_session) -> None:
    """Spec 002 §2 / §5 gate: a later snapshot for the same provider/model never
    changes an already-bound call's meaning. The calculator reads the bound
    snapshot's rates, never the current configuration."""
    ws = _ws(db_session)
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 2, 1, tzinfo=timezone.utc)
    # Historical snapshot bound at call time.
    s1 = _snapshot(db_session, input_rate="40", output_rate="120", effective_at=t1)
    pc = _call(db_session, ws, snapshot_id=s1.id, input_tokens=1500, output_tokens=500)
    db_session.commit()
    # A newer, higher-priced snapshot for the same provider/model arrives later.
    _snapshot(
        db_session,
        input_rate="80",
        output_rate="240",
        effective_at=t2,
    )
    db_session.commit()

    db_session.refresh(pc)
    # Binding is unchanged — the call still points at the original snapshot.
    assert pc.provider_rate_snapshot_id == s1.id
    bound = db_session.get(ProviderRateSnapshot, pc.provider_rate_snapshot_id)
    # Historical cost is computed from the BOUND rates, not the new ones.
    historical = calculate_cost(
        provider=pc.provider,
        model=pc.model,
        input_tokens=pc.input_tokens,
        output_tokens=pc.output_tokens,
        input_rate_per_1m=bound.input_rate_per_1m,
        output_rate_per_1m=bound.output_rate_per_1m,
    )
    # 1500*40/1e6 + 500*120/1e6 = 0.12 CNY (s1), NOT 0.24 (s2).
    assert historical.amount == Decimal("0.12")
    assert historical.unknown_reason is None


# --- CHECK constraints (enforced by SQLite) -----------------------------------

def test_currency_locked_to_cny_non_cny_rejected(db_session) -> None:
    with pytest.raises(IntegrityError):
        db_session.add(
            ProviderRateSnapshot(
                provider="anthropic",
                model="claude-fable-5",
                currency="USD",  # locked to CNY by ck_provider_rate_snapshots_currency_cny
                input_rate_per_1m=Decimal("1"),
                output_rate_per_1m=Decimal("1"),
                effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        db_session.flush()
    db_session.rollback()


def test_negative_input_rate_rejected(db_session) -> None:
    with pytest.raises(IntegrityError):
        _snapshot(db_session, input_rate="-0.01")
    db_session.rollback()


def test_negative_output_rate_rejected(db_session) -> None:
    with pytest.raises(IntegrityError):
        _snapshot(db_session, output_rate="-1")
    db_session.rollback()


def test_duplicate_provider_model_effective_at_rejected(db_session) -> None:
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _snapshot(db_session, effective_at=at)
    db_session.flush()
    with pytest.raises(IntegrityError):
        _snapshot(db_session, effective_at=at)
    db_session.rollback()


def test_negative_ordinal_rejected(db_session) -> None:
    ws = _ws(db_session)
    with pytest.raises(IntegrityError):
        _call(db_session, ws, ordinal=-1)
    db_session.rollback()


def test_invalid_status_rejected(db_session) -> None:
    ws = _ws(db_session)
    with pytest.raises(IntegrityError):
        _call(db_session, ws, status="pending")
    db_session.rollback()


def test_negative_input_tokens_rejected(db_session) -> None:
    ws = _ws(db_session)
    with pytest.raises(IntegrityError):
        _call(db_session, ws, input_tokens=-1)
    db_session.rollback()


def test_negative_output_tokens_rejected(db_session) -> None:
    ws = _ws(db_session)
    with pytest.raises(IntegrityError):
        _call(db_session, ws, output_tokens=-5)
    db_session.rollback()


def test_negative_latency_rejected(db_session) -> None:
    ws = _ws(db_session)
    with pytest.raises(IntegrityError):
        _call(db_session, ws, latency_ms=-10)
    db_session.rollback()


def test_zero_tokens_and_zero_latency_are_valid(db_session) -> None:
    """0 is a valid real fact, not a constraint violation (packet 4.3)."""
    ws = _ws(db_session)
    pc = _call(db_session, ws, input_tokens=0, output_tokens=0, latency_ms=0)
    db_session.commit()
    db_session.refresh(pc)
    assert pc.input_tokens == 0
    assert pc.output_tokens == 0
    assert pc.latency_ms == 0


# --- within-run ordinal uniqueness (partial unique index) ---------------------

def test_ordinal_unique_within_run(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    _call(db_session, ws, agent_run_id=run.id, ordinal=0)
    db_session.flush()
    with pytest.raises(IntegrityError):
        _call(db_session, ws, agent_run_id=run.id, ordinal=0)
    db_session.rollback()


def test_different_ordinals_within_run_are_allowed(db_session) -> None:
    ws = _ws(db_session)
    run = _run(db_session, ws)
    _call(db_session, ws, agent_run_id=run.id, ordinal=0)
    _call(db_session, ws, agent_run_id=run.id, ordinal=1)
    db_session.commit()  # no IntegrityError


def test_workspace_only_calls_may_share_ordinal(db_session) -> None:
    """Calls with no AgentRun (workspace-owned) are excluded from the partial
    unique index, so they do not clash on ordinal."""
    ws = _ws(db_session)
    _call(db_session, ws, agent_run_id=None, ordinal=0)
    _call(db_session, ws, agent_run_id=None, ordinal=0)
    db_session.commit()  # no IntegrityError


# --- forbidden columns (Spec 002 §2: no sensitive payload) --------------------

_FORBIDDEN_PROVIDER_CALL_COLUMNS = {
    "prompt", "message", "messages", "evidence", "answer", "answers",
    "response", "raw_response", "raw_error", "error_message", "error_text",
    "payload", "content", "body", "text", "question", "completion",
    "output_text", "raw_payload",
}


def test_provider_call_has_no_forbidden_payload_columns() -> None:
    columns = {c.name for c in ProviderCall.__table__.columns}
    leaked = columns & _FORBIDDEN_PROVIDER_CALL_COLUMNS
    assert not leaked, f"ProviderCall must not store sensitive payload columns: {leaked}"
    # A stable error CODE is allowed; a free-text error MESSAGE is not.
    assert "error_code" in columns
    assert "error_message" not in columns


def test_rate_snapshot_has_no_forbidden_payload_columns() -> None:
    columns = {c.name for c in ProviderRateSnapshot.__table__.columns}
    leaked = columns & _FORBIDDEN_PROVIDER_CALL_COLUMNS
    assert not leaked, f"ProviderRateSnapshot must not store sensitive payload columns: {leaked}"
