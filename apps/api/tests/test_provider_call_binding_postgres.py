"""Real Postgres counter-example tests for Provider Call -> rate snapshot
binding (Spec 002 §2 / ADR 001; Issue 2 of the Slice 1B-1 independent review).

SQLite does not enforce foreign keys, so the composite foreign key that pins a
bound snapshot's ``provider``/``model`` to the call's own ``provider``/``model``
can only be proven on Postgres. These build a throwaway database, seed real
rows and issue DB-level (raw SQL) inserts to show that:

- a call that binds a snapshot whose provider/model DIFFER from the call's is
  rejected at the DB layer (no wrong-price binding), even via raw SQL;
- a call that binds a snapshot whose provider/model MATCHE is accepted;
- a call with no snapshot (``provider_rate_snapshot_id`` NULL) is accepted
  regardless of its provider/model — the composite FK is MATCH SIMPLE and is
  skipped when the nullable leading column is NULL.

They skip automatically when the local Postgres used for development is not
reachable, and never touch the user's existing database or volume (a fresh,
randomly-named database is created and dropped per test).
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
    reason="local Postgres not reachable for Provider Call binding counter-example tests",
)


@pytest.fixture()
def pg_db():
    name = f"slice1b1_bind_{uuid4().hex[:12]}"
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


def _seed_workspace_snapshot(pg_db, *, provider="anthropic", model="claude-fable-5"):
    from learn_platform_api.db.models import ProviderRateSnapshot, Workspace

    ws = Workspace(name="ws", slug="ws")
    pg_db.add(ws)
    pg_db.flush()
    snap = ProviderRateSnapshot(
        provider=provider,
        model=model,
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=Decimal("120"),
        effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    pg_db.add(snap)
    pg_db.commit()
    return ws, snap


def _count_calls(pg_db) -> int:
    from learn_platform_api.db.models import ProviderCall

    return int(pg_db.execute(select(func.count(ProviderCall.id))).scalar() or 0)


# --- counter-examples: wrong provider/model snapshot binding is rejected -------

def test_wrong_provider_snapshot_binding_rejected(pg_db) -> None:
    """A call may not bind a snapshot whose provider differs from its own."""
    ws, snap = _seed_workspace_snapshot(pg_db, provider="anthropic", model="claude-fable-5")
    # Snapshot is anthropic/claude-fable-5; the call claims openai/gpt-4o.
    with pytest.raises(Exception):
        pg_db.execute(
            text(
                "INSERT INTO provider_calls "
                "(id, workspace_id, provider_rate_snapshot_id, ordinal, phase, provider, model, status, started_at, created_at) "
                "VALUES (:id, :ws, :snap, 0, 'generate', 'openai', 'gpt-4o', 'started', now(), now())"
            ),
            {"id": f"c-{uuid4().hex[:8]}", "ws": ws.id, "snap": snap.id},
        )
        pg_db.commit()
    pg_db.rollback()
    assert _count_calls(pg_db) == 0


def test_wrong_model_snapshot_binding_rejected(pg_db) -> None:
    """A call may not bind a snapshot whose model differs from its own, even
    when the provider matches."""
    ws, snap = _seed_workspace_snapshot(pg_db, provider="anthropic", model="claude-fable-5")
    # Provider matches; only the model is wrong -> still rejected.
    with pytest.raises(Exception):
        pg_db.execute(
            text(
                "INSERT INTO provider_calls "
                "(id, workspace_id, provider_rate_snapshot_id, ordinal, phase, provider, model, status, started_at, created_at) "
                "VALUES (:id, :ws, :snap, 0, 'generate', 'anthropic', 'claude-haiku', 'started', now(), now())"
            ),
            {"id": f"c-{uuid4().hex[:8]}", "ws": ws.id, "snap": snap.id},
        )
        pg_db.commit()
    pg_db.rollback()
    assert _count_calls(pg_db) == 0


# --- controls: matching binding and unbound calls are accepted ----------------

def test_matching_provider_model_snapshot_binding_allowed(pg_db) -> None:
    """When provider AND model match the bound snapshot, the call is accepted."""
    ws, snap = _seed_workspace_snapshot(pg_db, provider="anthropic", model="claude-fable-5")
    pg_db.execute(
        text(
            "INSERT INTO provider_calls "
            "(id, workspace_id, provider_rate_snapshot_id, ordinal, phase, provider, model, status, started_at, created_at) "
            "VALUES (:id, :ws, :snap, 0, 'generate', 'anthropic', 'claude-fable-5', 'succeeded', now(), now())"
        ),
        {"id": f"c-{uuid4().hex[:8]}", "ws": ws.id, "snap": snap.id},
    )
    pg_db.commit()
    assert _count_calls(pg_db) == 1


def test_unbound_call_ignores_snapshot_constraint(pg_db) -> None:
    """A call with no snapshot (provider_rate_snapshot_id NULL) is accepted with
    any provider/model: the composite FK is MATCH SIMPLE and is skipped when the
    nullable leading column is NULL."""
    ws, _snap = _seed_workspace_snapshot(pg_db)
    # No snapshot bound; arbitrary provider/model -> accepted.
    pg_db.execute(
        text(
            "INSERT INTO provider_calls "
            "(id, workspace_id, ordinal, phase, provider, model, status, started_at, created_at) "
            "VALUES (:id, :ws, 0, 'generate', 'openai', 'gpt-4o', 'started', now(), now())"
        ),
        {"id": f"c-{uuid4().hex[:8]}", "ws": ws.id},
    )
    pg_db.commit()
    assert _count_calls(pg_db) == 1
