"""Isolated Postgres round-trip for migration 0026."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import sql


API_ROOT = Path(__file__).resolve().parents[1]
PG_ADMIN = "postgresql://hello_agents:hello_agents@localhost:55432/postgres"
PG_TEMPLATE = "postgresql+psycopg://hello_agents:hello_agents@localhost:55432/{name}"


@pytest.fixture()
def pg_database():
    name = f"slice2b_tool_mig_{uuid4().hex[:12]}"
    try:
        admin = psycopg.connect(PG_ADMIN, autocommit=True)
    except Exception as exc:
        raise RuntimeError(
            "Postgres is required for migration 0026 tests"
        ) from exc
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    admin.close()
    try:
        yield PG_TEMPLATE.format(name=name)
    finally:
        admin = psycopg.connect(PG_ADMIN, autocommit=True)
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(
                sql.Identifier(name)
            )
        )
        admin.close()


def _alembic(url: str, *args: str, check: bool = True):
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_ROOT),
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def test_migration_0026_roundtrip(pg_database: str) -> None:
    _alembic(pg_database, "upgrade", "0025")
    _alembic(pg_database, "upgrade", "0026")

    engine = sa.create_engine(pg_database)
    try:
        with engine.connect() as conn:
            names = {
                row[0]
                for row in conn.execute(
                    sa.text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conname IN ("
                        "'fk_agent_tool_calls_run_workspace',"
                        "'uq_agent_tool_calls_ordinal',"
                        "'ck_agent_tool_calls_status_valid',"
                        "'ck_agent_tool_calls_ordinal_nonneg',"
                        "'ck_job_tool_auth_budget_valid',"
                        "'ck_tutor_turn_tool_auth_budget_valid'"
                        ")"
                    )
                )
            }
            assert names == {
                "fk_agent_tool_calls_run_workspace",
                "uq_agent_tool_calls_ordinal",
                "ck_agent_tool_calls_status_valid",
                "ck_agent_tool_calls_ordinal_nonneg",
                "ck_job_tool_auth_budget_valid",
                "ck_tutor_turn_tool_auth_budget_valid",
            }
            assert conn.execute(
                sa.text(
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conname = 'agent_tool_calls_agent_run_id_fkey'"
                )
            ).scalar() is None
    finally:
        engine.dispose()

    _alembic(pg_database, "downgrade", "0025")
    engine = sa.create_engine(pg_database)
    try:
        with engine.connect() as conn:
            assert conn.execute(
                sa.text(
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conname = 'agent_tool_calls_agent_run_id_fkey'"
                )
            ).scalar() == 1
            assert conn.execute(
                sa.text(
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conname = 'fk_agent_tool_calls_run_workspace'"
                )
            ).scalar() is None
    finally:
        engine.dispose()


def test_migration_0026_rejects_invalid_existing_budget(pg_database: str) -> None:
    _alembic(pg_database, "upgrade", "0025")
    engine = sa.create_engine(pg_database)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO workspaces "
                "(id,name,slug,lifecycle_status,created_at,updated_at) "
                "VALUES ('w','w','w','active',now(),now())"
            ))
            conn.execute(sa.text(
                "INSERT INTO practice_jobs "
                "(id,workspace_id,job_type,output_language,difficulty,item_count,"
                "request_hash,status,idempotency_key,attempt_count,"
                "artifact_contract_version,created_at,updated_at) "
                "VALUES ('j','w','generate_set','zh-CN','standard',1,"
                f"'{('0' * 64)}','running','k',1,'practice_artifact_v1',now(),now())"
            ))
            conn.execute(sa.text(
                "INSERT INTO agent_runs "
                "(id,practice_job_id,workspace_id,role,attempt_number,status,"
                "step_count,created_at) "
                "VALUES ('r','j','w','exercise_author',1,'running',0,now())"
            ))
            conn.execute(sa.text(
                "INSERT INTO job_tool_authorizations "
                "(id,workspace_id,capability_id,practice_job_id,max_calls,"
                "used_calls,authorized_at) "
                "VALUES ('a','w','code_execution','j',1,2,now())"
            ))
    finally:
        engine.dispose()

    result = _alembic(pg_database, "upgrade", "0026", check=False)
    assert result.returncode != 0
    assert "invalid budgets" in (result.stderr + result.stdout)
