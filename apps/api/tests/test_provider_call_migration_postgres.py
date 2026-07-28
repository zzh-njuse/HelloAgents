"""Stage 5 Slice 1B-1 — isolated Postgres migration round-trip test (Spec 002 / ADR 001).

Verifies migration ``0024`` against a REAL, ISOLATED Postgres database:

- ``upgrade head`` (0023 -> 0024) creates ``provider_calls`` and
  ``provider_rate_snapshots`` with their CHECK/UNIQUE constraints intact;
- ``downgrade 0023`` drops both tables and nothing else, leaving all prior
  history untouched.

Per the packet this is the only schema delta for the slice. The test NEVER runs
against the development Postgres volume and NEVER performs a downgrade there. It
auto-creates a fresh, randomly-named throwaway database and drops it afterwards.
When local Postgres is not reachable the round-trip skips with an explicit
reason — it does not fall back to SQLite (SQLite ORM does not exercise the
alembic migration and must not masquerade as a Postgres result).

The static additive-source guard runs unconditionally (no Postgres needed) so
the migration staying purely additive is checked on every run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

psycopg = pytest.importorskip("psycopg")

API_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = API_ROOT / "alembic" / "versions"

PG_ADMIN = "postgresql://hello_agents:hello_agents@localhost:55432/postgres"
PG_TEMPLATE = "postgresql+psycopg://hello_agents:hello_agents@localhost:55432/{name}"


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(PG_ADMIN, autocommit=True)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture()
def pg_database():
    name = f"slice1b1_mig_{uuid4().hex[:12]}"
    admin = psycopg.connect(PG_ADMIN, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {name}")
    admin.execute(f"CREATE DATABASE {name}")
    admin.close()
    try:
        yield PG_TEMPLATE.format(name=name)
    finally:
        admin = psycopg.connect(PG_ADMIN, autocommit=True)
        admin.execute(f"DROP DATABASE IF EXISTS {name}")
        admin.close()


def _alembic_env(url: str) -> dict[str, str]:
    # alembic/env.py reads get_settings().database_url; pydantic-settings lets the
    # DATABASE_URL env var override .env, so pointing the subprocess at the
    # throwaway DB is just setting one variable.
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    return env


def _alembic(url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_ROOT),
        env=_alembic_env(url),
        check=True,
    )


def _public_tables(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                row[0]
                for row in conn.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            }
    finally:
        engine.dispose()


# --- static additive-source guard (always runs) -------------------------------

def test_migration_0024_source_is_purely_additive() -> None:
    migration = (VERSIONS_DIR / "0024_add_provider_call_cost_foundation.py").read_text(encoding="utf-8")
    assert 'revision = "0024"' in migration
    assert 'down_revision = "0023"' in migration
    assert "provider_calls" in migration
    assert "provider_rate_snapshots" in migration
    # Additive only: upgrade creates tables/indexes; downgrade drops the same.
    assert "create_table" in migration
    assert "drop_table" in migration
    # It must never mutate existing tables or backfill rows.
    assert "op.alter_column" not in migration
    assert "op.add_column" not in migration
    assert "op.drop_column" not in migration


# --- isolated Postgres round-trip (skips when local PG is absent) -------------

@pytest.mark.skipif(
    not _pg_available(),
    reason="local Postgres not reachable for migration round-trip (packet §6: no SQLite fallback)",
)
def test_migration_0024_roundtrip_on_isolated_postgres(pg_database: str) -> None:
    url = pg_database

    # Bring the isolated DB to the pre-0024 head, then apply 0024.
    _alembic(url, "upgrade", "0023")
    _alembic(url, "upgrade", "head")

    engine = sa.create_engine(url)
    try:
        # Both new tables exist.
        tables = _public_tables(url)
        assert "provider_calls" in tables
        assert "provider_rate_snapshots" in tables

        def _expect_reject(sql: str) -> None:
            # Each check runs in its own transaction so one CHECK violation
            # cannot poison the connection for the next (Postgres aborts the
            # whole transaction on a constraint failure).
            with engine.connect() as conn:
                with pytest.raises(Exception):
                    conn.execute(sa.text(sql))
                    conn.commit()

        # currency is locked to CNY at the DB level.
        _expect_reject(
            "INSERT INTO provider_rate_snapshots "
            "(id, provider, model, currency, input_rate_per_1m, output_rate_per_1m, "
            "effective_at, created_at) "
            "VALUES ('s1', 'p', 'm', 'USD', 1, 1, '2026-01-01T00:00:00+00:00', now())"
        )
        # Non-negative rate CHECK fires.
        _expect_reject(
            "INSERT INTO provider_rate_snapshots "
            "(id, provider, model, currency, input_rate_per_1m, output_rate_per_1m, "
            "effective_at, created_at) "
            "VALUES ('s2', 'p', 'm', 'CNY', -1, 1, '2026-01-01T00:00:00+00:00', now())"
        )

        # A valid workspace so the provider_calls FK passes, isolating the
        # status CHECK as the only reason the next insert fails.
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO workspaces (id, name, slug, lifecycle_status, created_at, updated_at) "
                    "VALUES ('w1', 'w', 'w', 'active', now(), now())"
                )
            )
        _expect_reject(
            "INSERT INTO provider_calls "
            "(id, workspace_id, ordinal, phase, provider, model, status, started_at, created_at) "
            "VALUES ('c0', 'w1', 0, 'generate', 'anthropic', 'claude-fable-5', 'pending', now(), now())"
        )

        # Append-only (provider, model, effective_at) uniqueness: a valid row,
        # then a duplicate at the same effective_at, must be rejected.
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO provider_rate_snapshots "
                    "(id, provider, model, currency, input_rate_per_1m, output_rate_per_1m, "
                    "effective_at, created_at) "
                    "VALUES ('a', 'anthropic', 'claude-fable-5', 'CNY', 40, 120, "
                    "'2026-01-01T00:00:00+00:00', now())"
                )
            )
        _expect_reject(
            "INSERT INTO provider_rate_snapshots "
            "(id, provider, model, currency, input_rate_per_1m, output_rate_per_1m, "
            "effective_at, created_at) "
            "VALUES ('b', 'anthropic', 'claude-fable-5', 'CNY', 50, 150, "
            "'2026-01-01T00:00:00+00:00', now())"
        )

        # Issue 2 (binding integrity): the migration must emit the composite FK
        # that pins a bound snapshot's provider/model to the call's. Snapshot
        # 'a' is anthropic/claude-fable-5; this call claims openai/gpt-4o ->
        # rejected at the DB layer (no wrong-price binding).
        _expect_reject(
            "INSERT INTO provider_calls "
            "(id, workspace_id, provider_rate_snapshot_id, ordinal, phase, provider, model, status, started_at, created_at) "
            "VALUES ('c2', 'w1', 'a', 0, 'generate', 'openai', 'gpt-4o', 'started', now(), now())"
        )
        # Matching provider/model binds fine -> the composite FK is enforced,
        # not over-rejecting.
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO provider_calls "
                    "(id, workspace_id, provider_rate_snapshot_id, ordinal, phase, provider, model, status, started_at, created_at) "
                    "VALUES ('c3', 'w1', 'a', 0, 'generate', 'anthropic', 'claude-fable-5', 'started', now(), now())"
                )
            )

        # Issue 1 (Workspace isolation): the migration must create the redundant
        # UNIQUE(id, workspace_id) on the existing agent_runs table and the
        # composite FK on provider_calls. (Behavioral cross-workspace rejection
        # is proven in test_provider_call_workspace_postgres.py via create_all.)
        with engine.connect() as conn:
            assert conn.execute(
                sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_agent_runs_id_workspace'")
            ).scalar() == 1
            assert conn.execute(
                sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'fk_provider_calls_run_workspace'")
            ).scalar() == 1
    finally:
        engine.dispose()

    # Downgrade by one revision: both new tables are gone, nothing else changed.
    _alembic(url, "downgrade", "0023")
    tables_after = _public_tables(url)
    assert "provider_calls" not in tables_after
    assert "provider_rate_snapshots" not in tables_after
    # Core history is untouched by the round-trip.
    assert "workspaces" in tables_after
    assert "agent_runs" in tables_after
    # Issue 1: the agent_runs unique constraint added by 0024 is removed on
    # downgrade (provider_calls and its composite FK are already gone with the
    # table); agent_runs itself remains, minus this slice's hardening.
    post_engine = sa.create_engine(url)
    try:
        with post_engine.connect() as conn:
            assert conn.execute(
                sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_agent_runs_id_workspace'")
            ).scalar() is None
            # Composite FK on provider_calls is gone (table dropped).
            assert conn.execute(
                sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'fk_provider_calls_run_workspace'")
            ).scalar() is None
    finally:
        post_engine.dispose()
