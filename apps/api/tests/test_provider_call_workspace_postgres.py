"""Real Postgres tests for Provider Call -> AgentRun Workspace isolation
(Spec 002 §3 / ADR 001; Issue 1 of the Slice 1B-1 independent review).

SQLite does not enforce foreign keys, so the composite foreign key that pins a
bound AgentRun's ``workspace_id`` to the Provider Call's own ``workspace_id``
can only be proven on Postgres. These build a throwaway database, seed real
rows and issue DB-level operations to show that:

- a call bound to a run in the SAME workspace is accepted;
- a call bound to a run in a DIFFERENT workspace is rejected at the DB layer
  (raw SQL too), i.e. cross-Workspace calls cannot be written;
- a workspace-only call (``agent_run_id`` NULL) is accepted in any workspace —
  the composite FK is MATCH SIMPLE and is skipped when the nullable leading
  column is NULL;
- deleting the AgentRun still cascades the bound Provider Call away through
  the composite FK's explicit ON DELETE CASCADE.

They skip automatically when the local Postgres used for development is not
reachable, and never touch the user's existing database or volume (a fresh,
randomly-named database is created and dropped per test).
"""

from __future__ import annotations

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
    reason="local Postgres not reachable for Provider Call workspace-isolation tests",
)


@pytest.fixture()
def pg_db():
    name = f"slice1b1_ws_{uuid4().hex[:12]}"
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


def _seed_two_workspaces_with_run_in_a(pg_db):
    """Workspace A + B, plus a valid AgentRun (practice_job owner) in A."""
    from learn_platform_api.db.models import AgentRun, PracticeJob, Workspace

    ws_a = Workspace(name="ws-a", slug="ws-a")
    ws_b = Workspace(name="ws-b", slug="ws-b")
    pg_db.add_all([ws_a, ws_b])
    pg_db.flush()
    pj = PracticeJob(
        workspace_id=ws_a.id,
        job_type="generate_set",
        output_language="zh-CN",
        difficulty="standard",
        item_count=1,
        request_hash="0" * 64,
        idempotency_key="ws-run",
        attempt_count=0,
    )
    pg_db.add(pj)
    pg_db.flush()
    ar = AgentRun(
        practice_job_id=pj.id,
        workspace_id=ws_a.id,
        role="exercise_author",
        attempt_number=1,
        status="succeeded",
    )
    pg_db.add(ar)
    pg_db.commit()
    return ws_a, ws_b, ar


def _count_calls(pg_db) -> int:
    from learn_platform_api.db.models import ProviderCall

    return int(pg_db.execute(select(func.count(ProviderCall.id))).scalar() or 0)


def test_same_workspace_agent_run_binding_allowed(pg_db) -> None:
    """A call bound to a run in the SAME workspace is accepted."""
    ws_a, _ws_b, ar = _seed_two_workspaces_with_run_in_a(pg_db)
    pg_db.execute(
        text(
            "INSERT INTO provider_calls "
            "(id, workspace_id, agent_run_id, ordinal, phase, provider, model, status, started_at, created_at) "
            "VALUES (:id, :ws, :run, 0, 'generate', 'anthropic', 'claude-fable-5', 'started', now(), now())"
        ),
        {"id": f"c-{uuid4().hex[:8]}", "ws": ws_a.id, "run": ar.id},
    )
    pg_db.commit()
    assert _count_calls(pg_db) == 1


def test_cross_workspace_agent_run_binding_rejected(pg_db) -> None:
    """A call may not bind a run that lives in a DIFFERENT workspace. Raw SQL is
    rejected at the DB layer (Workspace isolation, Issue 1)."""
    _ws_a, ws_b, ar = _seed_two_workspaces_with_run_in_a(pg_db)
    # run is in workspace A; the call claims workspace B -> rejected.
    with pytest.raises(Exception):
        pg_db.execute(
            text(
                "INSERT INTO provider_calls "
                "(id, workspace_id, agent_run_id, ordinal, phase, provider, model, status, started_at, created_at) "
                "VALUES (:id, :ws, :run, 0, 'generate', 'anthropic', 'claude-fable-5', 'started', now(), now())"
            ),
            {"id": f"c-{uuid4().hex[:8]}", "ws": ws_b.id, "run": ar.id},
        )
        pg_db.commit()
    pg_db.rollback()
    assert _count_calls(pg_db) == 0


def test_workspace_only_call_ignores_run_constraint(pg_db) -> None:
    """A workspace-only call (agent_run_id NULL) is accepted in any workspace:
    the composite FK is MATCH SIMPLE and is skipped when agent_run_id IS NULL."""
    _ws_a, ws_b, _ar = _seed_two_workspaces_with_run_in_a(pg_db)
    # No run bound; the call lives in workspace B (where there is no run) -> OK.
    pg_db.execute(
        text(
            "INSERT INTO provider_calls "
            "(id, workspace_id, ordinal, phase, provider, model, status, started_at, created_at) "
            "VALUES (:id, :ws, 0, 'generate', 'openai', 'gpt-4o', 'started', now(), now())"
        ),
        {"id": f"c-{uuid4().hex[:8]}", "ws": ws_b.id},
    )
    pg_db.commit()
    assert _count_calls(pg_db) == 1


def test_agent_run_delete_still_cascades_with_workspace_fk(pg_db) -> None:
    """The composite workspace FK preserves deletion semantics: deleting the
    AgentRun removes its bound Provider Call through ON DELETE CASCADE."""
    from learn_platform_api.db.models import AgentRun, ProviderCall

    ws_a, _ws_b, ar = _seed_two_workspaces_with_run_in_a(pg_db)
    pc = ProviderCall(
        workspace_id=ws_a.id,
        agent_run_id=ar.id,
        ordinal=0,
        phase="generate",
        provider="anthropic",
        model="claude-fable-5",
        status="succeeded",
    )
    pg_db.add(pc)
    pg_db.commit()
    assert _count_calls(pg_db) == 1

    pg_db.execute(text("DELETE FROM agent_runs WHERE id = :id"), {"id": ar.id})
    pg_db.commit()

    assert _count_calls(pg_db) == 0
    # The composite FK never cascade-deleted the snapshot-less call's workspace;
    # the run row is gone.
    assert int(pg_db.execute(select(func.count(AgentRun.id))).scalar() or 0) == 0
