"""Postgres-only concurrency and database constraints for ADR 006."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from learn_platform_api.db.base import Base
from learn_platform_api.db.models import (
    AgentRun,
    AgentToolCall,
    JobToolAuthorization,
    PracticeJob,
    Workspace,
)
from learn_platform_api.services.remote_tool_call_recorder import (
    RemoteToolCallRecorder,
    TOOL_BUDGET_EXCEEDED,
)


PG_ADMIN = "postgresql://hello_agents:hello_agents@localhost:55432/postgres"
PG_TEMPLATE = "postgresql+psycopg://hello_agents:hello_agents@localhost:55432/{name}"


@pytest.fixture()
def pg_factory():
    name = f"slice2b_tool_{uuid4().hex[:12]}"
    try:
        admin = psycopg.connect(PG_ADMIN, autocommit=True)
    except Exception as exc:
        raise RuntimeError(
            "Postgres is required for durable tool concurrency tests"
        ) from exc
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    admin.close()
    engine = create_engine(PG_TEMPLATE.format(name=name))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()
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


def _seed(factory):
    with factory() as db:
        ws = Workspace(name="pg-tools", slug=f"pg-tools-{uuid4().hex[:8]}")
        db.add(ws)
        db.flush()
        job = PracticeJob(
            workspace_id=ws.id,
            job_type="generate_set",
            output_language="zh-CN",
            difficulty="standard",
            item_count=1,
            request_hash="0" * 64,
            idempotency_key=f"pg-tools-{uuid4().hex[:8]}",
            attempt_count=1,
        )
        db.add(job)
        db.flush()
        run = AgentRun(
            practice_job_id=job.id,
            workspace_id=ws.id,
            role="exercise_author",
            attempt_number=1,
            status="running",
        )
        auth = JobToolAuthorization(
            workspace_id=ws.id,
            capability_id="code_execution",
            practice_job_id=job.id,
            max_calls=1,
            used_calls=0,
        )
        db.add_all([run, auth])
        db.commit()
        return ws.id, run.id, auth.id


def test_concurrent_consumers_cannot_exceed_last_budget(pg_factory) -> None:
    workspace_id, run_id, auth_id = _seed(pg_factory)

    def reserve(ordinal: int) -> str:
        with pg_factory() as caller:
            caller._test_session_factory = pg_factory
            recorder = RemoteToolCallRecorder(
                caller,
                workspace_id=workspace_id,
                agent_run_id=run_id,
                authorization_kind="job",
                authorization_id=auth_id,
                capability_id="code_execution",
                tool_name="ValidateCodingReference",
                ordinal=ordinal,
            )
            try:
                recorder.reserve()
            except ValueError as exc:
                return str(exc)
            return "reserved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, (1, 2)))

    assert outcomes.count("reserved") == 1
    assert outcomes.count(TOOL_BUDGET_EXCEEDED) == 1
    with pg_factory() as check:
        assert check.get(JobToolAuthorization, auth_id).used_calls == 1
        assert len(list(check.scalars(select(AgentToolCall)))) == 1


def test_database_rejects_cross_workspace_tool_call(pg_factory) -> None:
    workspace_id, run_id, _auth_id = _seed(pg_factory)
    with pg_factory() as db:
        other = Workspace(name="other", slug=f"other-{uuid4().hex[:8]}")
        db.add(other)
        db.commit()
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO agent_tool_calls "
                    "(id, agent_run_id, workspace_id, tool_name, ordinal, "
                    "status, created_at) "
                    "VALUES (:id, :run, :workspace, 'Remote', 1, "
                    "'started', now())"
                ),
                {
                    "id": str(uuid4()),
                    "run": run_id,
                    "workspace": other.id,
                },
            )
            db.commit()
        db.rollback()
        assert workspace_id != other.id


def test_agent_run_delete_cascades_tool_call(pg_factory) -> None:
    workspace_id, run_id, auth_id = _seed(pg_factory)
    with pg_factory() as caller:
        caller._test_session_factory = pg_factory
        recorder = RemoteToolCallRecorder(
            caller,
            workspace_id=workspace_id,
            agent_run_id=run_id,
            authorization_kind="job",
            authorization_id=auth_id,
            capability_id="code_execution",
            tool_name="ValidateCodingReference",
            ordinal=1,
        )
        recorder.reserve()
        recorder.succeed()
    with pg_factory() as db:
        db.delete(db.get(AgentRun, run_id))
        db.commit()
        assert list(db.scalars(select(AgentToolCall))) == []
