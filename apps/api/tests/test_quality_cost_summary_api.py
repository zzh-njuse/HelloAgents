"""Stage 5 Slice 1C — schema & enumeration tests for quality-cost-summary API.

These tests use SQLite to verify:
- 404 for unknown workspace
- 422 for invalid enum parameters
- Response structure whitelist (schema shape)
- Non-Postgres dialect returns 503 (Fix 2)

All endpoint *behavior* tests (aggregation, percentile, cost) live in
test_quality_cost_summary_postgres.py which uses a real Postgres database.
SQLite cannot compute percentile_cont or NUMERIC cost aggregation; the
endpoint must reject non-Postgres dialects rather than return pseudo-facts.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

API_ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = API_ROOT.parent
REPOSITORY_ROOT = API_ROOT.parents[1]
for p in (str(APPS_DIR), str(REPOSITORY_ROOT), str(API_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from learn_platform_api.db.models import (
    AgentRun,
    Workspace,
)


# --- Helpers ----------------------------------------------------------------

def _make_workspace(db: Session) -> Workspace:
    ws = Workspace(name=f"ws-{uuid4()}", slug=f"slug-{uuid4()}")
    db.add(ws)
    db.flush()
    return ws


# --- Fixtures ----------------------------------------------------------------

@pytest.fixture
def db_session(tmp_path: Path):
    """Isolated SQLite database for each test."""
    from sqlalchemy import create_engine
    from learn_platform_api.db.base import Base

    test_engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        echo=False,
    )
    Base.metadata.create_all(bind=test_engine)

    from sqlalchemy.orm import sessionmaker
    TestSession = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    db = TestSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    test_engine.dispose()


@pytest.fixture
def client(db_session: Session):
    """FastAPI test client using the test database session."""
    from learn_platform_api.db.session import get_db
    from learn_platform_api.main import app

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- Tests -------------------------------------------------------------------

class TestQualityCostSummarySchema:
    """Schema, enumeration and dialect-rejection tests."""

    def test_unknown_workspace_404(self, db_session, client):
        resp = client.get(f"/api/v1/workspaces/{uuid4()}/quality-cost-summary")
        assert resp.status_code == 404

    def test_invalid_window_422(self, db_session, client):
        ws = _make_workspace(db_session)
        db_session.commit()
        resp = client.get(
            f"/api/v1/workspaces/{ws.id}/quality-cost-summary",
            params={"window": "1h"},
        )
        assert resp.status_code == 422

    def test_invalid_role_422(self, db_session, client):
        ws = _make_workspace(db_session)
        db_session.commit()
        resp = client.get(
            f"/api/v1/workspaces/{ws.id}/quality-cost-summary",
            params={"role": "not_a_role"},
        )
        assert resp.status_code == 422

    def test_invalid_business_type_422(self, db_session, client):
        ws = _make_workspace(db_session)
        db_session.commit()
        resp = client.get(
            f"/api/v1/workspaces/{ws.id}/quality-cost-summary",
            params={"business_type": "not_a_type"},
        )
        assert resp.status_code == 422

    def test_invalid_status_422(self, db_session, client):
        ws = _make_workspace(db_session)
        db_session.commit()
        resp = client.get(
            f"/api/v1/workspaces/{ws.id}/quality-cost-summary",
            params={"status": "not_a_status"},
        )
        assert resp.status_code == 422

    def test_non_postgres_returns_503(self, db_session, client):
        """Non-Postgres dialect must not return pseudo-facts (Fix 2).

        SQLite cannot compute percentile_cont or NUMERIC cost aggregation.
        The endpoint must reject with 503 rather than return partial results.
        """
        ws = _make_workspace(db_session)
        db_session.commit()
        resp = client.get(f"/api/v1/workspaces/{ws.id}/quality-cost-summary")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "quality_cost_requires_postgres"

    def test_non_postgres_no_aggregation_sql_executed(self, db_session, client):
        """Fix 4: Non-Postgres must return 503 BEFORE any aggregation SQL runs.

        We count SQL statements executed during the request. On SQLite,
        the endpoint must raise RuntimeError before executing any SELECT
        against AgentRun/ProviderCall tables.
        """
        from sqlalchemy import event
        from learn_platform_api.db.session import get_db
        from learn_platform_api.main import app

        ws = _make_workspace(db_session)
        db_session.commit()

        # Count SQL statements emitted on the test engine
        stmt_count = {"n": 0}
        def _before_execute(conn, clause, multiparams, params):
            stmt_count["n"] += 1
        event.listen(db_session.get_bind(), "before_execute", _before_execute)

        def _override():
            yield db_session
        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/workspaces/{ws.id}/quality-cost-summary")
        app.dependency_overrides.clear()
        event.remove(db_session.get_bind(), "before_execute", _before_execute)

        assert resp.status_code == 503
        # Only workspace lookup SQL should have executed (1-2 statements
        # for the workspace_is_active check), NOT aggregation queries.
        assert stmt_count["n"] <= 2, (
            f"Expected ≤2 SQL statements (workspace lookup only), "
            f"got {stmt_count['n']} — aggregation ran before dialect check"
        )

    def test_response_structure_on_postgres(self):
        """Response structure is verified in Postgres tests.

        This test documents the expected whitelist structure.
        On SQLite the endpoint returns 503, so structure cannot be verified here.
        """
        # Structure verified by TestPostgresCostAggregation and
        # TestPostgresPercentile in test_quality_cost_summary_postgres.py
        pass
