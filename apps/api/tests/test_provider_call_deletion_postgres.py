"""Real Postgres cascade-deletion tests for Provider Call ownership (Spec 002 §3/§5).

SQLite does not enforce foreign keys, so the Workspace/AgentRun -> Provider Call
``ON DELETE CASCADE`` can only be proven on Postgres. These build a throwaway
database, seed real rows, issue DB-level deletes and assert no orphaned Provider
Call survives. They skip automatically when the local Postgres used for
development is not reachable, and never touch the user's existing database or
volume (a fresh, randomly-named database is created and dropped per test).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

psycopg = pytest.importorskip("psycopg")

PG_ADMIN = "postgresql://hello_agents:hello_agents@localhost:55432/postgres"
PG_TEMPLATE = "postgresql+psycopg://hello_agents:hello_agents@localhost:55432/{name}"


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(PG_ADMIN, autocommit=True)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason="local Postgres not reachable for Provider Call cascade-deletion tests",
)


@pytest.fixture()
def pg_db():
    name = f"slice1b1_del_{uuid4().hex[:12]}"
    admin = psycopg.connect(PG_ADMIN, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {name}")
    admin.execute(f"CREATE DATABASE {name}")
    admin.close()

    from learn_platform_api.db.base import Base
    import learn_platform_api.db.models  # noqa: F401 - register metadata

    engine = create_engine(PG_TEMPLATE.format(name=name))
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        admin = psycopg.connect(PG_ADMIN, autocommit=True)
        admin.execute(f"DROP DATABASE IF EXISTS {name}")
        admin.close()


def _count(pg_db, model) -> int:
    return int(pg_db.execute(select(func.count(model.id))).scalar() or 0)


def _seed_workspace_call(pg_db):
    from learn_platform_api.db.models import ProviderCall, Workspace

    ws = Workspace(name="ws", slug="ws")
    pg_db.add(ws)
    pg_db.flush()
    pc = ProviderCall(
        workspace_id=ws.id,
        ordinal=0,
        phase="generate",
        provider="anthropic",
        model="claude-fable-5",
        status="started",
    )
    pg_db.add(pc)
    pg_db.commit()
    return ws, pc


def _seed_run_call(pg_db):
    """Workspace + practice_job (AgentRun owner) + agent_run + bound provider_call."""
    from learn_platform_api.db.models import AgentRun, PracticeJob, ProviderCall, Workspace

    ws = Workspace(name="ws", slug="ws")
    pg_db.add(ws)
    pg_db.flush()
    pj = PracticeJob(
        workspace_id=ws.id,
        job_type="generate_set",
        output_language="zh-CN",
        difficulty="standard",
        item_count=1,
        request_hash="0" * 64,
        idempotency_key="del-run",
        attempt_count=0,
    )
    pg_db.add(pj)
    pg_db.flush()
    ar = AgentRun(
        practice_job_id=pj.id,
        workspace_id=ws.id,
        role="exercise_author",
        attempt_number=1,
        status="succeeded",
    )
    pg_db.add(ar)
    pg_db.flush()
    pc = ProviderCall(
        workspace_id=ws.id,
        agent_run_id=ar.id,
        ordinal=0,
        phase="generate",
        provider="anthropic",
        model="claude-fable-5",
        status="succeeded",
        input_tokens=10,
        output_tokens=20,
        latency_ms=123,
    )
    pg_db.add(pc)
    pg_db.commit()
    return ws, pj, ar, pc


def test_workspace_delete_cascades_to_provider_calls(pg_db) -> None:
    from learn_platform_api.db.models import ProviderCall

    ws, _pc = _seed_workspace_call(pg_db)
    assert _count(pg_db, ProviderCall) == 1
    # DB-level delete of the workspace must cascade every owned Provider Call.
    pg_db.execute(text("DELETE FROM workspaces WHERE id = :id"), {"id": ws.id})
    pg_db.commit()
    assert _count(pg_db, ProviderCall) == 0


def test_agent_run_delete_cascades_to_bound_provider_calls(pg_db) -> None:
    from learn_platform_api.db.models import AgentRun, PracticeJob, ProviderCall, Workspace

    ws, pj, ar, _pc = _seed_run_call(pg_db)
    assert _count(pg_db, ProviderCall) == 1
    # Deleting only the AgentRun cascades its bound Provider Call away.
    pg_db.execute(text("DELETE FROM agent_runs WHERE id = :id"), {"id": ar.id})
    pg_db.commit()
    assert _count(pg_db, ProviderCall) == 0
    # The owning practice_job and workspace are untouched by the run's deletion.
    assert _count(pg_db, PracticeJob) == 1
    assert _count(pg_db, Workspace) == 1
    assert _count(pg_db, AgentRun) == 0


def test_rate_snapshot_survives_call_deletion(pg_db) -> None:
    """Deleting a call does not delete its bound (append-only) rate snapshot."""
    from learn_platform_api.db.models import ProviderCall, ProviderRateSnapshot, Workspace

    ws = Workspace(name="ws", slug="ws")
    pg_db.add(ws)
    pg_db.flush()
    snap = ProviderRateSnapshot(
        provider="anthropic",
        model="claude-fable-5",
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=Decimal("120"),
        effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    pg_db.add(snap)
    pg_db.flush()
    pc = ProviderCall(
        workspace_id=ws.id,
        provider_rate_snapshot_id=snap.id,
        ordinal=0,
        phase="generate",
        provider="anthropic",
        model="claude-fable-5",
        status="succeeded",
    )
    pg_db.add(pc)
    pg_db.commit()
    pg_db.delete(pc)
    pg_db.commit()
    assert _count(pg_db, ProviderCall) == 0
    assert _count(pg_db, ProviderRateSnapshot) == 1


def test_postgres_enforces_provider_call_foreign_keys(pg_db) -> None:
    """Sanity: the throwaway database really enforces FKs (else the above prove nothing)."""
    with pytest.raises(Exception):
        pg_db.execute(
            text(
                "INSERT INTO provider_calls "
                "(id, workspace_id, ordinal, phase, provider, model, status, started_at, created_at) "
                "VALUES ('c', 'no-such-workspace', 0, 'generate', 'anthropic', 'claude-fable-5', 'started', now(), now())"
            )
        )
        pg_db.commit()
