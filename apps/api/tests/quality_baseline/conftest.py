"""conftest for the Slice 2B Batch A quality baseline package.

Exposes the ``pg_db`` throwaway-Postgres fixture. The Postgres Gate lives inside
the fixture: any test that requests ``pg_db`` FAILS (never skips, never falls
back to SQLite) when Postgres is unreachable or ``psycopg`` is missing
(Spec 006 §7, Slice 2B packet §4/§10). Pure data tests (sample registry, report
contract) do not request ``pg_db`` and therefore do not require Postgres.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

import psycopg  # Postgres Gate: missing psycopg => any pg_db test FAILS, not skip

PG_ADMIN = "postgresql://hello_agents:hello_agents@localhost:55432/postgres"
PG_TEMPLATE = "postgresql+psycopg://hello_agents:hello_agents@localhost:55432/{name}"


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(PG_ADMIN, autocommit=True, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture()
def pg_db():
    """A random throwaway Postgres database with the full schema.

    FAILS (not skip) if Postgres is unreachable. ``_test_session_factory`` is
    attached so ADR-004 independent recorder sessions share this engine.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from learn_platform_api.db.base import Base
    import learn_platform_api.db.models  # noqa: F401 - register metadata

    if not _pg_available():
        raise RuntimeError(
            "local Postgres not reachable at localhost:55432 — Slice 2B Batch A "
            "controlled baseline Gate must FAIL (Spec 006 §7, packet §4/§10: no "
            "SQLite fallback, no skip)"
        )

    name = f"slice2b_batcha_{uuid4().hex[:12]}"
    admin = psycopg.connect(PG_ADMIN, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {name}")
    admin.execute(f"CREATE DATABASE {name}")
    admin.close()

    engine = create_engine(PG_TEMPLATE.format(name=name))
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionFactory()
    session._test_session_factory = SessionFactory
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        admin = psycopg.connect(PG_ADMIN, autocommit=True)
        admin.execute(f"DROP DATABASE IF EXISTS {name}")
        admin.close()
