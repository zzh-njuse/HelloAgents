import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

API_ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = API_ROOT.parent  # apps/ directory — enables "from shared..."
REPOSITORY_ROOT = API_ROOT.parents[1]
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from learn_platform_api.db.base import Base
from learn_platform_api.db.session import get_db
from learn_platform_api.main import create_app


@pytest.fixture
def db_session(tmp_path: Path) -> Generator[Session, None, None]:
    # SQLite is only a legacy test/eval compatibility backend (AGENTS.md,
    # Spec 006). ADR 004's durable independent-transaction contract is the
    # Postgres path, proven by the throwaway-Postgres acceptance tests; this
    # fixture only needs the recorder to *function* on SQLite without locking.
    #
    # The recorder commits ProviderCall facts in an independent Session from
    # this same factory (db._test_session_factory). With the default pool that
    # opens a SECOND connection to the file, SQLite's single-writer model plus
    # WAL cross-snapshot rules deadlock against the caller's open business
    # transaction ("database is locked"). StaticPool pins every Session from
    # this factory to ONE shared connection, so the recorder's independent
    # commits serialize on that connection instead of contending for a second
    # writer lock. This changes only the SQLite test backend; the production
    # Postgres recorder (SessionLocal, independent connection per ADR 004) is
    # untouched, and survive-rollback still holds (verified: a recorder commit
    # while the business session is idle or mid-transaction persists across a
    # later business rollback).
    test_engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=test_engine, autoflush=False, expire_on_commit=False
    )
    Base.metadata.create_all(bind=test_engine)

    db = TestingSessionLocal()
    # Expose the session factory for ADR 004 independent recorder sessions.
    db._test_session_factory = TestingSessionLocal
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
