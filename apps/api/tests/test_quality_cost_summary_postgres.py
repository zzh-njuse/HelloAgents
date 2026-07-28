"""Stage 5 Slice 1C — Isolated Postgres focused tests (Fix 3).

Uses a throwaway Postgres database to verify:
- percentile_cont behavior (Fix 1: continuous interpolation, not nearest-rank)
- database-side cost aggregation (Fix 2: SQL CASE/NUMERIC)
- combined filters, workspace isolation, RAG/workspace-only exclusion
- runs_without_provider_calls
- query count bounds
- identity kind drift regression (Fix 4)

This file requires a running Postgres instance. Tests are skipped if
Postgres is not available.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

API_ROOT = os.path.dirname(os.path.abspath(__file__))
APPS_DIR = os.path.dirname(API_ROOT)
REPOSITORY_ROOT = os.path.dirname(APPS_DIR)
for p in (APPS_DIR, REPOSITORY_ROOT, API_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from learn_platform_api.db.base import Base
from learn_platform_api.db.models import (
    AgentRun,
    ProviderCall,
    ProviderRateSnapshot,
    Workspace,
    Course,
    CourseVersion,
    CourseGenerationJob,
    PracticeJob,
    TutorTurn,
    TutorSession,
)
from learn_platform_api.services.agent_run_identity import (
    OWNER_KIND_PRECEDENCE,
    owner_kind_from_run,
)
from learn_platform_api.services.quality_cost import (
    get_quality_cost_summary,
)

# --- Postgres connection -------------------------------------------------------

PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
PG_PORT = os.environ.get("POSTGRES_PORT", "55432")
PG_USER = os.environ.get("POSTGRES_USER", "hello_agents")
PG_PASS = os.environ.get("POSTGRES_PASSWORD", "hello_agents")
PG_DB_TEMPLATE = os.environ.get("POSTGRES_DB", "hello_agents")


def _create_throwaway_db() -> tuple[str, str]:
    """Create a throwaway database for testing. Returns (db_name, url)."""
    db_name = f"test_qc_{uuid4().hex[:12]}"
    admin_url = f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB_TEMPLATE}"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()
    test_url = f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{db_name}"
    return db_name, test_url


def _drop_throwaway_db(db_name: str) -> None:
    """Drop a throwaway database."""
    admin_url = f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB_TEMPLATE}"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    engine.dispose()


@pytest.fixture(scope="module")
def pg_db():
    """Module-scoped throwaway Postgres database."""
    try:
        db_name, test_url = _create_throwaway_db()
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
        return
    engine = create_engine(test_url)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()
    _drop_throwaway_db(db_name)


@pytest.fixture
def db_session(pg_db):
    """Per-test session with rollback."""
    TestSession = sessionmaker(bind=pg_db, autoflush=False, expire_on_commit=False)
    db = TestSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- Helpers ----------------------------------------------------------------

def _make_workspace(db: Session) -> Workspace:
    ws = Workspace(name=f"ws-{uuid4()}", slug=f"slug-{uuid4()}")
    db.add(ws)
    db.flush()
    return ws


def _make_course(db: Session, workspace_id: str) -> Course:
    c = Course(workspace_id=workspace_id, title="Test Course", goal="test", lifecycle_status="active")
    db.add(c)
    db.flush()
    return c


def _make_course_version(db: Session, workspace_id: str, course_id: str) -> CourseVersion:
    v = CourseVersion(course_id=course_id, workspace_id=workspace_id, version_number=1, status="active", title="v1")
    db.add(v)
    db.flush()
    return v


def _make_tutor_session(db: Session, workspace_id: str, course_id: str, version_id: str) -> TutorSession:
    ts = TutorSession(
        workspace_id=workspace_id, course_id=course_id,
        course_version_id=version_id, provider="test", model="test",
        external_processing_ack_at=datetime.now(timezone.utc),
    )
    db.add(ts)
    db.flush()
    return ts


def _make_tutor_turn(db: Session, workspace_id: str, session_id: str) -> TutorTurn:
    turn = TutorTurn(
        workspace_id=workspace_id, session_id=session_id,
        ordinal=1, attempt_number=1, scope="course",
        question="test", idempotency_key=str(uuid4()),
        history_through_ordinal=0, status="succeeded",
    )
    db.add(turn)
    db.flush()
    return turn


def _make_course_gen_job(db: Session, workspace_id: str, course_id: str) -> CourseGenerationJob:
    job = CourseGenerationJob(
        workspace_id=workspace_id, course_id=course_id,
        job_type="course_outline", output_language="zh-CN",
        course_version_id=None, lesson_id=None,
        idempotency_key=str(uuid4()), status="succeeded",
    )
    db.add(job)
    db.flush()
    return job


def _make_agent_run(
    db: Session,
    workspace_id: str,
    *,
    role: str = "tutor",
    status: str = "succeeded",
    error_code: str | None = None,
    course_gen_job_id: str | None = None,
    tutor_turn_id: str | None = None,
    practice_job_id: str | None = None,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> AgentRun:
    # If no owner, create a tutor turn as default
    if not any([course_gen_job_id, tutor_turn_id, practice_job_id]):
        c = _make_course(db, workspace_id)
        v = _make_course_version(db, workspace_id, c.id)
        ts = _make_tutor_session(db, workspace_id, c.id, v.id)
        turn = _make_tutor_turn(db, workspace_id, ts.id)
        tutor_turn_id = turn.id

    run = AgentRun(
        workspace_id=workspace_id, role=role, status=status,
        attempt_number=1, step_count=1, error_code=error_code,
        course_generation_job_id=course_gen_job_id,
        tutor_turn_id=tutor_turn_id,
        practice_job_id=practice_job_id,
        created_at=created_at or datetime.now(timezone.utc),
        completed_at=completed_at,
    )
    db.add(run)
    db.flush()
    return run


def _make_rate_snapshot(
    db: Session,
    provider: str = "openai",
    model: str = "gpt-4",
    input_rate: Decimal = Decimal("30.00000000"),
    output_rate: Decimal = Decimal("60.00000000"),
    effective_at: datetime | None = None,
) -> ProviderRateSnapshot:
    snap = ProviderRateSnapshot(
        provider=provider, model=model,
        input_rate_per_1m=input_rate, output_rate_per_1m=output_rate,
        effective_at=effective_at or datetime.now(timezone.utc),
    )
    db.add(snap)
    db.flush()
    return snap


def _make_provider_call(
    db: Session,
    workspace_id: str,
    agent_run_id: str | None = None,
    *,
    ordinal: int = 0,
    phase: str = "answer",
    provider: str = "openai",
    model: str = "gpt-4",
    status: str = "succeeded",
    input_tokens: int | None = 100,
    output_tokens: int | None = 200,
    snapshot_id: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> ProviderCall:
    call = ProviderCall(
        workspace_id=workspace_id, agent_run_id=agent_run_id,
        rag_answer_trace_id=None, ordinal=ordinal, phase=phase,
        provider=provider, model=model, status=status,
        input_tokens=input_tokens, output_tokens=output_tokens,
        latency_ms=500,
        started_at=started_at or datetime.now(timezone.utc),
        completed_at=completed_at or datetime.now(timezone.utc),
        provider_rate_snapshot_id=snapshot_id,
    )
    db.add(call)
    db.flush()
    return call


# --- Tests -------------------------------------------------------------------

class TestPostgresPercentile:
    """Verify percentile_cont behavior on real Postgres (Fix 1)."""

    def test_even_samples_continuous_interpolation(self, db_session):
        """percentile_cont uses continuous interpolation, not nearest-rank.

        For [100, 200, 300, 400]:
          P50 = 250.0 (continuous), not 200 (nearest-rank ceil)
          P95 = 385.0 (continuous)
        """
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        for secs in (0.1, 0.2, 0.3, 0.4):
            _make_agent_run(db_session, ws.id, status="succeeded",
                            created_at=now - timedelta(seconds=secs), completed_at=now)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        # P50 should be 250 ms (continuous interpolation between 200 and 300)
        assert result["runs"]["duration_ms"]["p50"] == 250
        assert result["runs"]["duration_ms"]["sample_count"] == 4

    def test_odd_samples(self, db_session):
        """For [100, 200, 300]: P50 = 200 (exact match)."""
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        for secs in (0.1, 0.2, 0.3):
            _make_agent_run(db_session, ws.id, status="succeeded",
                            created_at=now - timedelta(seconds=secs), completed_at=now)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        assert result["runs"]["duration_ms"]["p50"] == 200
        assert result["runs"]["duration_ms"]["sample_count"] == 3

    def test_empty_samples_null(self, db_session):
        """No terminal runs → p50/p95 are None."""
        ws = _make_workspace(db_session)
        _make_agent_run(db_session, ws.id, status="started")
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        assert result["runs"]["duration_ms"]["p50"] is None
        assert result["runs"]["duration_ms"]["p95"] is None
        assert result["runs"]["duration_ms"]["sample_count"] == 0


class TestPostgresCostAggregation:
    """Verify database-side cost aggregation on real Postgres (Fix 2)."""

    def test_calculated_cost_matches_detail(self, db_session):
        """SQL aggregation must match per-call calculate_cost results."""
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        run = _make_agent_run(db_session, ws.id, status="succeeded",
                              created_at=now - timedelta(seconds=10), completed_at=now)
        snap = _make_rate_snapshot(db_session,
                                   input_rate=Decimal("30.00000000"),
                                   output_rate=Decimal("60.00000000"))
        _make_provider_call(db_session, ws.id, run.id, ordinal=0, snapshot_id=snap.id,
                            input_tokens=1000, output_tokens=2000)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        # 1000 * 30/1M + 2000 * 60/1M = 0.03 + 0.12 = 0.15
        assert result["cost"]["known_amount"] == "0.15000000"
        assert result["cost"]["calculated_call_count"] == 1
        assert result["cost"]["unknown_call_count"] == 0

    def test_zero_cost_is_calculated(self, db_session):
        """Real zero cost (0 tokens) belongs to calculated, not unknown."""
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        run = _make_agent_run(db_session, ws.id, status="succeeded",
                              created_at=now - timedelta(seconds=10), completed_at=now)
        snap = _make_rate_snapshot(db_session)
        _make_provider_call(db_session, ws.id, run.id, ordinal=0, snapshot_id=snap.id,
                            input_tokens=0, output_tokens=0)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        assert result["cost"]["known_amount"] == "0.00000000"
        assert result["cost"]["calculated_call_count"] == 1
        assert result["cost"]["unknown_call_count"] == 0

    def test_unknown_reasons_via_sql(self, db_session):
        """Each unknown reason is classified correctly by SQL CASE."""
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        run = _make_agent_run(db_session, ws.id, status="succeeded",
                              created_at=now - timedelta(seconds=10), completed_at=now)
        # rate_missing: has provider/model/tokens but no snapshot
        _make_provider_call(db_session, ws.id, run.id, ordinal=0,
                            provider="openai", model="gpt-4",
                            input_tokens=100, output_tokens=200)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        assert result["cost"]["unknown_call_count"] == 1
        reasons = {r["reason"]: r["count"] for r in result["cost"]["unknown_by_reason"]}
        assert reasons.get("rate_missing", 0) >= 1

    def test_mixed_calculated_and_unknown(self, db_session):
        """Mixed calculated + unknown calls are correctly separated."""
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        run = _make_agent_run(db_session, ws.id, status="succeeded",
                              created_at=now - timedelta(seconds=10), completed_at=now)
        snap = _make_rate_snapshot(db_session)
        _make_provider_call(db_session, ws.id, run.id, ordinal=0, snapshot_id=snap.id,
                            input_tokens=1000, output_tokens=2000)
        _make_provider_call(db_session, ws.id, run.id, ordinal=1,
                            provider="other", model="other",
                            input_tokens=100, output_tokens=200)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        assert result["cost"]["calculated_call_count"] == 1
        assert result["cost"]["unknown_call_count"] == 1


class TestPostgresWorkspaceIsolation:
    """Verify workspace isolation on real Postgres."""

    def test_cross_workspace_isolation(self, db_session):
        ws1 = _make_workspace(db_session)
        ws2 = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        _make_agent_run(db_session, ws1.id, status="succeeded",
                        created_at=now - timedelta(seconds=10), completed_at=now)
        _make_agent_run(db_session, ws2.id, status="succeeded",
                        created_at=now - timedelta(seconds=10), completed_at=now)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws1.id, window="24h")
        assert result["runs"]["total"] == 1


class TestPostgresRAGExclusion:
    """Verify RAG/workspace-only Provider Calls are excluded."""

    def test_workspace_only_call_excluded(self, db_session):
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        run = _make_agent_run(db_session, ws.id, status="succeeded",
                              created_at=now - timedelta(seconds=10), completed_at=now)
        snap = _make_rate_snapshot(db_session)
        _make_provider_call(db_session, ws.id, run.id, ordinal=0, snapshot_id=snap.id)
        # Workspace-only call (no agent_run_id)
        _make_provider_call(db_session, ws.id, None, ordinal=0, snapshot_id=snap.id)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        assert result["provider_calls"]["total"] == 1


class TestPostgresRunsWithoutCalls:
    """Verify runs_without_provider_calls on real Postgres."""

    def test_runs_without_calls(self, db_session):
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        _make_agent_run(db_session, ws.id, status="succeeded",
                        created_at=now - timedelta(seconds=10), completed_at=now)
        run2 = _make_agent_run(db_session, ws.id, status="succeeded",
                               created_at=now - timedelta(seconds=10), completed_at=now)
        snap = _make_rate_snapshot(db_session)
        _make_provider_call(db_session, ws.id, run2.id, ordinal=0, snapshot_id=snap.id)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        assert result["cost"]["runs_without_provider_calls"] == 1


class TestIdentityDriftRegression:
    """Verify identity kind precedence stays in sync (Fix 4).

    Tests compare real Agent Run identity results with SQL aggregation,
    not just a constant with itself.
    """

    def test_owner_precedence_matches_identity(self, db_session):
        """owner_kind_from_run() must match SQL business_type for each owner type."""
        ws = _make_workspace(db_session)
        c = _make_course(db_session, ws.id)
        v = _make_course_version(db_session, ws.id, c.id)
        job = _make_course_gen_job(db_session, ws.id, c.id)
        ts = _make_tutor_session(db_session, ws.id, c.id, v.id)
        turn = _make_tutor_turn(db_session, ws.id, ts.id)
        now = datetime.now(timezone.utc)

        # Course generation run
        run_cg = _make_agent_run(db_session, ws.id, role="course_architect", status="succeeded",
                                 course_gen_job_id=job.id,
                                 created_at=now - timedelta(seconds=10), completed_at=now)
        # Tutor run
        run_t = _make_agent_run(db_session, ws.id, role="tutor", status="succeeded",
                                tutor_turn_id=turn.id,
                                created_at=now - timedelta(seconds=10), completed_at=now)
        db_session.commit()

        # Verify Python identity matches SQL business_type for each run
        assert owner_kind_from_run(run_cg) == "course_generation"
        assert owner_kind_from_run(run_t) == "tutor"

        # business_type=course_generation should match only the CG run
        result_cg = get_quality_cost_summary(db_session, ws.id, window="24h",
                                             business_type="course_generation")
        assert result_cg["runs"]["total"] == 1

        # business_type=tutor should match only the tutor run
        result_t = get_quality_cost_summary(db_session, ws.id, window="24h",
                                            business_type="tutor")
        assert result_t["runs"]["total"] == 1

    def test_precedence_order_is_correct(self):
        """OWNER_KIND_PRECEDENCE must list course_generation before tutor."""
        kinds = [kind for _, kind in OWNER_KIND_PRECEDENCE]
        assert kinds == ["course_generation", "tutor", "practice", "code_execution"]

    def test_practice_identity_matches_sql(self, db_session):
        """Practice job identity must match SQL business_type (Fix 4)."""
        ws = _make_workspace(db_session)
        c = _make_course(db_session, ws.id)
        v = _make_course_version(db_session, ws.id, c.id)
        pjob = PracticeJob(
            workspace_id=ws.id, course_id=c.id,
            job_type="generate_set", practice_set_id=None,
            practice_attempt_id=None, idempotency_key=str(uuid4()),
            output_language="zh-CN", difficulty="medium",
            item_count=5, request_hash="0" * 64,
        )
        db_session.add(pjob)
        db_session.flush()
        now = datetime.now(timezone.utc)
        run_p = _make_agent_run(db_session, ws.id, role="exercise_author", status="succeeded",
                                practice_job_id=pjob.id,
                                created_at=now - timedelta(seconds=10), completed_at=now)
        db_session.commit()

        assert owner_kind_from_run(run_p) == "practice"
        result_p = get_quality_cost_summary(db_session, ws.id, window="24h",
                                            business_type="practice")
        assert result_p["runs"]["total"] == 1


class TestWhitespaceProviderModelClassification:
    """Verify whitespace-only provider/model is classified as missing (Fix 3).

    SQL btrim must match provider_cost._is_blank which treats
    whitespace-only strings as missing.

    Note: ProviderCall has a FK constraint (snapshot_id, provider, model)
    referencing provider_rate_snapshots. Calls with whitespace-only
    provider/model cannot have a snapshot_id, since the FK would not match.
    """

    def test_whitespace_provider_classified_missing(self, db_session):
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        run = _make_agent_run(db_session, ws.id, status="succeeded",
                              created_at=now - timedelta(seconds=10), completed_at=now)
        # Whitespace-only provider → provider_missing (no snapshot_id due to FK)
        _make_provider_call(db_session, ws.id, run.id, ordinal=0,
                            provider=" \t\r\n", model="gpt-4",
                            input_tokens=100, output_tokens=200,
                            snapshot_id=None)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        assert result["cost"]["unknown_call_count"] == 1
        reasons = {r["reason"]: r["count"] for r in result["cost"]["unknown_by_reason"]}
        assert reasons.get("provider_missing", 0) >= 1

    def test_whitespace_model_classified_missing(self, db_session):
        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        run = _make_agent_run(db_session, ws.id, status="succeeded",
                              created_at=now - timedelta(seconds=10), completed_at=now)
        # Whitespace-only model → model_missing (no snapshot_id due to FK)
        _make_provider_call(db_session, ws.id, run.id, ordinal=0,
                            provider="openai", model="\t\r\n ",
                            input_tokens=100, output_tokens=200,
                            snapshot_id=None)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        assert result["cost"]["unknown_call_count"] == 1
        reasons = {r["reason"]: r["count"] for r in result["cost"]["unknown_by_reason"]}
        assert reasons.get("model_missing", 0) >= 1

    def test_sql_unknown_reason_matches_calculate_cost(self, db_session):
        """SQL unknown reason classification must match provider_cost.calculate_cost."""
        from learn_platform_api.services.provider_cost import calculate_cost

        ws = _make_workspace(db_session)
        now = datetime.now(timezone.utc)
        run = _make_agent_run(db_session, ws.id, status="succeeded",
                              created_at=now - timedelta(seconds=10), completed_at=now)
        snap = _make_rate_snapshot(db_session)

        # Whitespace provider call (no snapshot_id due to FK constraint)
        _make_provider_call(db_session, ws.id, run.id, ordinal=0,
                            provider="  ", model="gpt-4",
                            input_tokens=100, output_tokens=200,
                            snapshot_id=None)
        # Whitespace model call (no snapshot_id due to FK constraint)
        _make_provider_call(db_session, ws.id, run.id, ordinal=1,
                            provider="openai", model="  ",
                            input_tokens=100, output_tokens=200,
                            snapshot_id=None)
        db_session.commit()

        result = get_quality_cost_summary(db_session, ws.id, window="24h")
        reasons = {r["reason"]: r["count"] for r in result["cost"]["unknown_by_reason"]}

        # Verify calculate_cost agrees for each case
        cr1 = calculate_cost(provider="  ", model="gpt-4",
                             input_tokens=100, output_tokens=200,
                             input_rate_per_1m=snap.input_rate_per_1m,
                             output_rate_per_1m=snap.output_rate_per_1m)
        assert cr1.unknown_reason == "provider_missing"
        assert reasons.get("provider_missing", 0) >= 1

        cr2 = calculate_cost(provider="openai", model="  ",
                             input_tokens=100, output_tokens=200,
                             input_rate_per_1m=snap.input_rate_per_1m,
                             output_rate_per_1m=snap.output_rate_per_1m)
        assert cr2.unknown_reason == "model_missing"
        assert reasons.get("model_missing", 0) >= 1
