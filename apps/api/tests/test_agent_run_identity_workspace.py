"""Stage 5 Slice 1C — Practice grading identity workspace validation (Fix 5).

Verifies that _identity() safely degrades when intermediate objects
(PracticeAttempt, PracticeItem) belong to a different workspace.
Uses isolated Postgres with real ORM rows.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
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
    Workspace,
    Course,
    CourseVersion,
    CourseSection,
    Lesson,
    LessonVersion,
    PracticeJob,
    PracticeAttempt,
    PracticeItem,
    PracticeSet,
)
from learn_platform_api.services.agent_runs import _identity

# --- Postgres connection -------------------------------------------------------

PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
PG_PORT = os.environ.get("POSTGRES_PORT", "55432")
PG_USER = os.environ.get("POSTGRES_USER", "hello_agents")
PG_PASS = os.environ.get("POSTGRES_PASSWORD", "hello_agents")
PG_DB_TEMPLATE = os.environ.get("POSTGRES_DB", "hello_agents")


def _create_throwaway_db() -> tuple[str, str]:
    db_name = f"test_id_{uuid4().hex[:12]}"
    admin_url = f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB_TEMPLATE}"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()
    test_url = f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{db_name}"
    return db_name, test_url


def _drop_throwaway_db(db_name: str) -> None:
    admin_url = f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB_TEMPLATE}"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    engine.dispose()


@pytest.fixture(scope="module")
def pg_db():
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
    c = Course(workspace_id=workspace_id, title="Test", goal="test", lifecycle_status="active")
    db.add(c)
    db.flush()
    return c


def _make_course_version(db: Session, workspace_id: str, course_id: str) -> CourseVersion:
    v = CourseVersion(course_id=course_id, workspace_id=workspace_id, version_number=1, status="active", title="v1")
    db.add(v)
    db.flush()
    return v


def _make_lesson(db: Session, workspace_id: str, course_version_id: str, course_section_id: str) -> Lesson:
    lesson = Lesson(
        workspace_id=workspace_id, course_version_id=course_version_id,
        course_section_id=course_section_id, title="Test Lesson",
        ordinal=1, objective="test",
    )
    db.add(lesson)
    db.flush()
    return lesson


def _make_course_section(db: Session, workspace_id: str, course_version_id: str) -> CourseSection:
    cs = CourseSection(
        workspace_id=workspace_id, course_version_id=course_version_id,
        title="Test Section", ordinal=1, objective="test",
    )
    db.add(cs)
    db.flush()
    return cs


def _make_lesson_version(db: Session, workspace_id: str, lesson_id: str, course_version_id: str) -> LessonVersion:
    lv = LessonVersion(
        lesson_id=lesson_id, workspace_id=workspace_id,
        course_version_id=course_version_id, version_number=1,
        status="active", title="lv1",
        learning_objectives=[], blocks=[],
    )
    db.add(lv)
    db.flush()
    return lv


# --- Tests -------------------------------------------------------------------

class TestPracticeGradingIdentityWorkspace:
    """Fix 5: Practice grading identity must validate intermediate workspace."""

    def test_attempt_wrong_workspace_safe_degrade(self, db_session):
        """PracticeAttempt in different workspace → identity safely degrades."""
        ws1 = _make_workspace(db_session)
        ws2 = _make_workspace(db_session)
        c1 = _make_course(db_session, ws1.id)
        v1 = _make_course_version(db_session, ws1.id, c1.id)
        cs1 = _make_course_section(db_session, ws1.id, v1.id)
        c2 = _make_course(db_session, ws2.id)
        v2 = _make_course_version(db_session, ws2.id, c2.id)
        cs2 = _make_course_section(db_session, ws2.id, v2.id)

        # PracticeSet + PracticeItem in ws2
        lesson2 = _make_lesson(db_session, ws2.id, v2.id, cs2.id)
        lv2 = _make_lesson_version(db_session, ws2.id, lesson2.id, v2.id)
        ps = PracticeSet(
            workspace_id=ws2.id, course_id=c2.id,
            course_version_id=v2.id,
            lesson_id=lesson2.id, lesson_version_id=lv2.id,
            output_language="zh-CN", difficulty="medium",
            item_count=1, generation_config={},
        )
        db_session.add(ps)
        db_session.flush()
        pi = PracticeItem(
            workspace_id=ws2.id, practice_set_id=ps.id,
            item_type="multiple_choice", ordinal=1,
            stem="q", options=["a", "b"], answer_spec="a",
        )
        db_session.add(pi)
        db_session.flush()
        # PracticeAttempt in ws2
        attempt = PracticeAttempt(
            workspace_id=ws2.id, practice_item_id=pi.id,
            ordinal=1, item_type="multiple_choice",
            answer_payload={"answer": "a"},
            idempotency_key=f"attempt-{uuid4()}", status="submitted",
        )
        db_session.add(attempt)
        db_session.flush()

        # PracticeJob in ws1 with practice_attempt_id pointing to ws2's attempt
        pjob = PracticeJob(
            workspace_id=ws1.id, course_id=None,
            job_type="grade_attempt", practice_set_id=None,
            practice_attempt_id=attempt.id,
            output_language="zh-CN", difficulty="medium",
            item_count=1, request_hash="0" * 64,
            idempotency_key=f"pjob-{uuid4()}",
        )
        db_session.add(pjob)
        db_session.flush()

        # AgentRun in ws1 with practice_job_id
        run = AgentRun(
            workspace_id=ws1.id, role="answer_grader", status="succeeded",
            attempt_number=1, step_count=1,
            practice_job_id=pjob.id,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(run)
        db_session.commit()

        identity = _identity(db_session, run)
        assert identity["kind"] == "practice"
        assert identity["course_deleted"] is True
        assert identity["course_title"] is None

    def test_item_wrong_workspace_safe_degrade(self, db_session):
        """PracticeItem in different workspace → identity safely degrades."""
        ws1 = _make_workspace(db_session)
        ws2 = _make_workspace(db_session)
        c1 = _make_course(db_session, ws1.id)
        v1 = _make_course_version(db_session, ws1.id, c1.id)
        cs1 = _make_course_section(db_session, ws1.id, v1.id)
        c2 = _make_course(db_session, ws2.id)
        v2 = _make_course_version(db_session, ws2.id, c2.id)
        cs2 = _make_course_section(db_session, ws2.id, v2.id)

        # PracticeSet in ws2
        lesson2 = _make_lesson(db_session, ws2.id, v2.id, cs2.id)
        lv2 = _make_lesson_version(db_session, ws2.id, lesson2.id, v2.id)
        ps = PracticeSet(
            workspace_id=ws2.id, course_id=c2.id,
            course_version_id=v2.id,
            lesson_id=lesson2.id, lesson_version_id=lv2.id,
            output_language="zh-CN", difficulty="medium",
            item_count=1, generation_config={},
        )
        db_session.add(ps)
        db_session.flush()
        # PracticeItem in ws2
        pi = PracticeItem(
            workspace_id=ws2.id, practice_set_id=ps.id,
            item_type="multiple_choice", ordinal=1,
            stem="q", options=["a", "b"], answer_spec="a",
        )
        db_session.add(pi)
        db_session.flush()
        # PracticeAttempt in ws1 (correct ws) but item is in ws2
        attempt = PracticeAttempt(
            workspace_id=ws1.id, practice_item_id=pi.id,
            ordinal=1, item_type="multiple_choice",
            answer_payload={"answer": "a"},
            idempotency_key=f"attempt-{uuid4()}", status="submitted",
        )
        db_session.add(attempt)
        db_session.flush()

        pjob = PracticeJob(
            workspace_id=ws1.id, course_id=None,
            job_type="grade_attempt", practice_set_id=None,
            practice_attempt_id=attempt.id,
            output_language="zh-CN", difficulty="medium",
            item_count=1, request_hash="0" * 64,
            idempotency_key=f"pjob-{uuid4()}",
        )
        db_session.add(pjob)
        db_session.flush()

        run = AgentRun(
            workspace_id=ws1.id, role="answer_grader", status="succeeded",
            attempt_number=1, step_count=1,
            practice_job_id=pjob.id,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(run)
        db_session.commit()

        identity = _identity(db_session, run)
        assert identity["kind"] == "practice"
        assert identity["course_deleted"] is True
        assert identity["course_title"] is None
