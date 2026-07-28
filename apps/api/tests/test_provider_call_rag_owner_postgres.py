"""Stage 5 Slice 1B-2 — migration 0025 and RAG owner Postgres tests.

Verifies migration 0025 (RAG owner) against a REAL, ISOLATED Postgres database
and tests RAG owner constraints that SQLite cannot enforce (composite FK,
cascade deletion, cross-workspace rejection).

When local Postgres is not reachable the tests skip with an explicit reason.
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
    name = f"slice1b2_mig_{uuid4().hex[:12]}"
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

def test_migration_0025_source_is_valid() -> None:
    migration = (VERSIONS_DIR / "0025_add_rag_provider_call_owner.py").read_text(encoding="utf-8")
    assert 'revision = "0025"' in migration
    assert 'down_revision = "0024"' in migration
    assert "rag_answer_trace_id" in migration
    assert "ck_provider_calls_one_owner" in migration
    assert "fk_provider_calls_rag_trace_workspace" in migration
    assert "uq_provider_calls_rag_trace_ordinal" in migration


# --- isolated Postgres round-trip (skips when local PG is absent) -------------

@pytest.mark.skipif(
    not _pg_available(),
    reason="local Postgres not reachable for migration round-trip (packet §6: no SQLite fallback)",
)
def test_migration_0025_roundtrip_on_isolated_postgres(pg_database: str) -> None:
    url = pg_database

    # Bring the isolated DB to head (includes 0025)
    _alembic(url, "upgrade", "head")

    engine = sa.create_engine(url)
    try:
        tables = _public_tables(url)
        assert "provider_calls" in tables
        assert "rag_answer_traces" in tables

        def _expect_reject(sql: str) -> None:
            with engine.connect() as conn:
                with pytest.raises(Exception):
                    conn.execute(sa.text(sql))
                    conn.commit()

        # Setup: workspace, rag_answer_trace
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO workspaces (id, name, slug, lifecycle_status, created_at, updated_at) "
                "VALUES ('w1', 'w', 'w', 'active', now(), now())"
            ))
            conn.execute(sa.text(
                "INSERT INTO rag_answer_traces "
                "(id, workspace_id, question_hash, status, prompt_template_version, "
                "evidence_chunk_ids, citation_ids, created_at) "
                "VALUES ('t1', 'w1', '0', 'succeeded', 'v1', '[]', '[]', now())"
            ))

        # Owner mutual exclusion: both agent_run_id and rag_answer_trace_id non-null rejected
        # Need a valid agent_run first
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO courses "
                "(id, workspace_id, title, goal, lifecycle_status, created_at, updated_at) "
                "VALUES ('c1', 'w1', 'c', 'g', 'active', now(), now())"
            ))
            conn.execute(sa.text(
                "INSERT INTO course_generation_jobs "
                "(id, workspace_id, course_id, job_type, output_language, status, idempotency_key, attempt_count, created_at, updated_at) "
                "VALUES ('cj1', 'w1', 'c1', 'course_outline', 'zh-CN', 'succeeded', 'k1', 0, now(), now())"
            ))
            conn.execute(sa.text(
                "INSERT INTO agent_runs "
                "(id, workspace_id, course_generation_job_id, role, attempt_number, status, step_count, created_at) "
                "VALUES ('ar1', 'w1', 'cj1', 'course_architect', 1, 'succeeded', 0, now())"
            ))

        _expect_reject(
            "INSERT INTO provider_calls "
            "(id, workspace_id, agent_run_id, rag_answer_trace_id, ordinal, phase, provider, model, status, started_at, created_at) "
            "VALUES ('pc1', 'w1', 'ar1', 't1', 0, 'generation', 'deepseek', 'deepseek-v4-flash', 'started', now(), now())"
        )

        # RAG owner with correct workspace succeeds
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO provider_calls "
                "(id, workspace_id, rag_answer_trace_id, ordinal, phase, provider, model, status, started_at, created_at) "
                "VALUES ('pc2', 'w1', 't1', 0, 'answer', 'deepseek', 'deepseek-v4-flash', 'started', now(), now())"
            ))

        # RAG owner ordinal uniqueness: duplicate ordinal rejected
        _expect_reject(
            "INSERT INTO provider_calls "
            "(id, workspace_id, rag_answer_trace_id, ordinal, phase, provider, model, status, started_at, created_at) "
            "VALUES ('pc3', 'w1', 't1', 0, 'repair', 'deepseek', 'deepseek-v4-flash', 'started', now(), now())"
        )

        # Cross-workspace RAG owner rejected
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO workspaces (id, name, slug, lifecycle_status, created_at, updated_at) "
                "VALUES ('w2', 'w2', 'w2', 'active', now(), now())"
            ))
        _expect_reject(
            "INSERT INTO provider_calls "
            "(id, workspace_id, rag_answer_trace_id, ordinal, phase, provider, model, status, started_at, created_at) "
            "VALUES ('pc4', 'w2', 't1', 0, 'answer', 'deepseek', 'deepseek-v4-flash', 'started', now(), now())"
        )

        # RagAnswerTrace deletion cascades to Provider Calls
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM rag_answer_traces WHERE id = 't1'"))
        with engine.connect() as conn:
            count = conn.execute(sa.text(
                "SELECT COUNT(*) FROM provider_calls WHERE rag_answer_trace_id = 't1'"
            )).scalar()
            assert count == 0

    finally:
        engine.dispose()

    # Downgrade by one revision: 0025 changes are undone
    _alembic(url, "downgrade", "0024")
    engine2 = sa.create_engine(url)
    try:
        with engine2.connect() as conn:
            # rag_answer_trace_id column should be gone
            cols = {
                row[0]
                for row in conn.execute(sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'provider_calls'"
                ))
            }
            assert "rag_answer_trace_id" not in cols
            # RagAnswerTrace redundant unique constraint should be gone
            assert conn.execute(sa.text(
                "SELECT 1 FROM pg_constraint WHERE conname = 'uq_rag_answer_traces_id_workspace'"
            )).scalar() is None
            # 0024 constraints still intact
            assert conn.execute(sa.text(
                "SELECT 1 FROM pg_constraint WHERE conname = 'fk_provider_calls_run_workspace'"
            )).scalar() == 1
    finally:
        engine2.dispose()


# --- RAG owner cascade deletion via ORM (create_all, not alembic) ---------------

@pytest.mark.skipif(
    not _pg_available(),
    reason="local Postgres not reachable",
)
def test_rag_trace_deletion_cascades_provider_calls() -> None:
    """When a RagAnswerTrace is deleted, all its Provider Calls are deleted too."""
    from sqlalchemy import select, func
    from sqlalchemy.orm import sessionmaker
    from learn_platform_api.db.base import Base
    from learn_platform_api.db.models import ProviderCall, RagAnswerTrace, Workspace

    name = f"slice1b2_cascade_{uuid4().hex[:12]}"
    admin = psycopg.connect(PG_ADMIN, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {name}")
    admin.execute(f"CREATE DATABASE {name}")
    admin.close()

    engine = sa.create_engine(PG_TEMPLATE.format(name=name))
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    try:
        ws = Workspace(name="ws", slug="ws")
        session.add(ws)
        session.flush()
        trace = RagAnswerTrace(
            workspace_id=ws.id, question_hash="0" * 64, status="succeeded",
            prompt_template_version="v1", evidence_chunk_ids=[], citation_ids=[],
        )
        session.add(trace)
        session.flush()
        pc = ProviderCall(
            workspace_id=ws.id, rag_answer_trace_id=trace.id,
            ordinal=0, phase="answer", provider="deepseek", model="deepseek-v4-flash",
            status="succeeded", input_tokens=10, output_tokens=5,
        )
        session.add(pc)
        session.commit()

        # Delete the trace
        session.delete(trace)
        session.commit()

        # ProviderCall should be gone
        remaining = session.scalar(
            select(func.count()).select_from(ProviderCall).where(ProviderCall.rag_answer_trace_id == trace.id)
        )
        assert remaining == 0
    finally:
        session.close()
        engine.dispose()
        admin = psycopg.connect(PG_ADMIN, autocommit=True)
        admin.execute(f"DROP DATABASE IF EXISTS {name}")
        admin.close()
