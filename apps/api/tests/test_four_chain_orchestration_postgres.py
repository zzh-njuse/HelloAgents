"""Stage 5 Part 2 Slice 2A — Four-chain Provider Call Orchestration Postgres tests.

Verifies Course generation, Practice generation, Practice grading, and RAG Answer
chains produce correct ProviderCall facts in a REAL, ISOLATED Postgres database.

Each test enters through the real business service orchestration entry point,
monkeypatching only the lowest-level external boundaries (provider HTTP,
retrieval, MCP/code execution, capability projection). The service itself
creates AgentRun / RagAnswerTrace owners and calls record_provider_call()
through _recorded_call_provider or the direct wrapper.

All final evidence is queried from a NEW Postgres Session — never from the
business session, never from SQLite, never from mock call counts alone.

When local Postgres is not reachable, the Gate FAILS (does not skip), per
Spec 006 §7 and the Slice 2A four-chain test packet §4.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import psycopg  # Postgres Gate: import directly — missing psycopg => FAIL, not skip

# --- Postgres connection constants (same as existing Postgres tests) ------------

PG_ADMIN = "postgresql://hello_agents:hello_agents@localhost:55432/postgres"
PG_TEMPLATE = "postgresql+psycopg://hello_agents:hello_agents@localhost:55432/{name}"


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(PG_ADMIN, autocommit=True)
        conn.close()
        return True
    except Exception:
        return False


# Per packet §4: Postgres not reachable => Gate FAILS, not skip.
if not _pg_available():
    raise RuntimeError(
        "local Postgres not reachable — four-chain orchestration Gate must FAIL "
        "(Spec 006 §7, Slice 2A packet §4: no SQLite fallback, no skip)"
    )


# --- Throwaway Postgres database fixture -----------------------------------------

@pytest.fixture()
def pg_db():
    """Create a random throwaway Postgres database with full schema,
    yield a Session, then drop the database after the test."""
    from learn_platform_api.db.base import Base
    import learn_platform_api.db.models  # noqa: F401 - register metadata

    name = f"slice2a_4chain_{uuid4().hex[:12]}"
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


# --- Query helpers (always from a NEW session) -----------------------------------

def _query_calls(pg_db, **filters) -> list:
    """Query ProviderCall rows from a NEW session, applying filters."""
    from learn_platform_api.db.models import ProviderCall
    sf = pg_db._test_session_factory
    with sf() as verify_db:
        q = select(ProviderCall)
        for col, val in filters.items():
            q = q.where(getattr(ProviderCall, col) == val)
        rows = list(verify_db.scalars(q.order_by(ProviderCall.ordinal)))
        result = []
        for r in rows:
            result.append({
                "id": r.id,
                "workspace_id": r.workspace_id,
                "agent_run_id": r.agent_run_id,
                "rag_answer_trace_id": r.rag_answer_trace_id,
                "ordinal": r.ordinal,
                "phase": r.phase,
                "provider": r.provider,
                "model": r.model,
                "status": r.status,
                "error_code": r.error_code,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "latency_ms": r.latency_ms,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
            })
    return result


def _query_run(pg_db, **filters) -> dict | None:
    """Query a single AgentRun from a NEW session."""
    from learn_platform_api.db.models import AgentRun
    sf = pg_db._test_session_factory
    with sf() as verify_db:
        q = select(AgentRun)
        for col, val in filters.items():
            q = q.where(getattr(AgentRun, col) == val)
        r = verify_db.scalar(q)
        if r is None:
            return None
        return {
            "id": r.id,
            "workspace_id": r.workspace_id,
            "role": r.role,
            "status": r.status,
            "step_count": r.step_count,
        }


def _query_trace(pg_db, **filters) -> dict | None:
    """Query a single RagAnswerTrace from a NEW session."""
    from learn_platform_api.db.models import RagAnswerTrace
    sf = pg_db._test_session_factory
    with sf() as verify_db:
        q = select(RagAnswerTrace)
        for col, val in filters.items():
            q = q.where(getattr(RagAnswerTrace, col) == val)
        r = verify_db.scalar(q.order_by(RagAnswerTrace.created_at.desc()))
        if r is None:
            return None
        return {
            "id": r.id,
            "workspace_id": r.workspace_id,
            "status": r.status,
            "error_code": r.error_code,
        }


def _query_job(pg_db, job_id) -> dict | None:
    """Query a CourseGenerationJob from a NEW session."""
    from learn_platform_api.db.models import CourseGenerationJob
    sf = pg_db._test_session_factory
    with sf() as verify_db:
        r = verify_db.get(CourseGenerationJob, job_id)
        if r is None:
            return None
        return {
            "id": r.id,
            "status": r.status,
            "course_version_id": r.course_version_id,
        }


def _query_practice_job(pg_db, job_id) -> dict | None:
    """Query a PracticeJob from a NEW session."""
    from learn_platform_api.db.models import PracticeJob
    sf = pg_db._test_session_factory
    with sf() as verify_db:
        r = verify_db.get(PracticeJob, job_id)
        if r is None:
            return None
        return {
            "id": r.id,
            "status": r.status,
            "practice_set_id": r.practice_set_id,
        }


def _query_attempt(pg_db, attempt_id) -> dict | None:
    """Query a PracticeAttempt from a NEW session."""
    from learn_platform_api.db.models import PracticeAttempt
    sf = pg_db._test_session_factory
    with sf() as verify_db:
        r = verify_db.get(PracticeAttempt, attempt_id)
        if r is None:
            return None
        return {
            "id": r.id,
            "status": r.status,
            "error_code": r.error_code,
        }


# --- Seed helpers ---------------------------------------------------------------

def _ws(pg_db) -> "Workspace":
    from learn_platform_api.db.models import Workspace
    ws = Workspace(name="ws", slug=f"ws-{uuid4().hex[:8]}")
    pg_db.add(ws)
    pg_db.flush()
    pg_db.commit()
    return ws


def _make_settings(**overrides):
    from learn_platform_api.settings import Settings
    defaults = dict(
        product_generation_api_key="test-key",
        product_generation_base_url="https://fake.example.com",
        product_generation_model="deepseek-v4-flash",
        product_generation_provider="deepseek",
        practice_generation_model="deepseek-v4-pro",
        practice_generation_provider="deepseek",
        wolfram_mcp_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _fake_provider_response(usage_input=100, usage_output=50, content=None):
    """Build a fake httpx.Response that looks like a provider JSON response."""
    if content is None:
        content = json.dumps({"queries": ["q1"]})
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": usage_input, "completion_tokens": usage_output},
    }
    resp.raise_for_status = MagicMock()
    return resp


def _fake_retrieval_result(text="Evidence text", chunk_id="chunk-1",
                            document_id="doc-1", version_id="ver-1",
                            document_name="Test Doc", heading_path=None,
                            score=0.95):
    """Build a fake RetrievalResult that answer_question() will accept."""
    from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
    return RetrievalResult(
        score=score,
        text=text,
        citation=CitationRead(
            document_id=document_id,
            document_version_id=version_id,
            chunk_id=chunk_id,
            document_name=document_name,
            heading_path=heading_path or [],
            start_offset=0,
            end_offset=len(text),
        ),
    )


# --- Course generation seed ------------------------------------------------------

def _seed_course_job(pg_db, ws):
    """Create a Course, CourseVersion, CourseSection, Lesson and
    CourseGenerationJob for course_outline generation, plus a
    CourseGenerationJobSource with active SourceDocument so
    snapshot_rows() passes."""
    from learn_platform_api.db.models import (
        Course, CourseVersion, CourseSection, Lesson, CourseGenerationJob,
        CourseGenerationJobSource, SourceDocument, DocumentVersion,
    )
    course = Course(
        workspace_id=ws.id, title="Test", goal="Test",
        audience="general", lifecycle_status="active",
    )
    pg_db.add(course)
    pg_db.flush()
    version = CourseVersion(
        course_id=course.id, workspace_id=ws.id,
        version_number=1, status="draft", title="Test", summary="Test",
    )
    pg_db.add(version)
    pg_db.flush()
    section = CourseSection(
        course_version_id=version.id, workspace_id=ws.id,
        ordinal=0, title="S1", objective="Obj",
    )
    pg_db.add(section)
    pg_db.flush()
    lesson = Lesson(
        course_version_id=version.id, course_section_id=section.id,
        workspace_id=ws.id, ordinal=0, title="L1", objective="Obj",
    )
    pg_db.add(lesson)
    pg_db.flush()
    job = CourseGenerationJob(
        course_id=course.id, workspace_id=ws.id, job_type="course_outline",
        output_language="zh-CN", attempt_count=0,
        idempotency_key=f"4chain-{uuid4().hex[:8]}",
        status="running",
    )
    pg_db.add(job)
    pg_db.flush()

    # Source document so snapshot_rows() passes
    doc = SourceDocument(
        workspace_id=ws.id, display_name="course_source.pdf",
        lifecycle_status="active",
    )
    pg_db.add(doc)
    pg_db.flush()
    dver = DocumentVersion(
        document_id=doc.id, version_number=1, processing_status="ready",
        original_filename="course_source.pdf", mime_type="application/pdf",
        byte_size=1024, sha256="0" * 64, original_storage_uri="file:///tmp/fake",
    )
    pg_db.add(dver)
    pg_db.flush()
    doc.current_version_id = dver.id
    pg_db.flush()

    source = CourseGenerationJobSource(
        course_generation_job_id=job.id, workspace_id=ws.id,
        document_id=doc.id, document_version_id=dver.id,
    )
    pg_db.add(source)
    pg_db.flush()

    # DocumentChunk so evidence_search can find it
    from learn_platform_api.db.models import DocumentChunk
    chunk = DocumentChunk(
        id=f"chunk-course-{uuid4().hex[:8]}",
        document_version_id=dver.id, ordinal=0,
        content="Evidence text for course generation test.",
        content_hash="0" * 64, start_offset=0, end_offset=40,
    )
    pg_db.add(chunk)
    pg_db.flush()
    pg_db.commit()
    return job, chunk


# --- Practice generation seed ----------------------------------------------------

def _seed_practice_job(pg_db, ws):
    """Create the full infrastructure needed for a PracticeJob:
    Course, CourseVersion, Lesson, LessonVersion (published), PracticeJob
    with artifact_contract_version v2, and a PracticeJobSource."""
    from learn_platform_api.db.models import (
        Course, CourseVersion, CourseSection, Lesson, LessonVersion,
        PracticeJob, SourceDocument, DocumentVersion, PracticeJobSource,
        DocumentChunk,
    )
    from academic_companion.practice_agents import ARTIFACT_CONTRACT_V2

    course = Course(
        workspace_id=ws.id, title="PTest", goal="PTest",
        audience="general", lifecycle_status="active",
    )
    pg_db.add(course)
    pg_db.flush()
    cv = CourseVersion(
        course_id=course.id, workspace_id=ws.id,
        version_number=1, status="draft", title="PTest", summary="PTest",
    )
    pg_db.add(cv)
    pg_db.flush()
    section = CourseSection(
        course_version_id=cv.id, workspace_id=ws.id,
        ordinal=0, title="PS1", objective="PObj",
    )
    pg_db.add(section)
    pg_db.flush()
    lesson = Lesson(
        course_version_id=cv.id, course_section_id=section.id,
        workspace_id=ws.id, ordinal=0, title="PL1", objective="PObj",
    )
    pg_db.add(lesson)
    pg_db.flush()

    lv = LessonVersion(
        lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id,
        version_number=1, status="published", title="PL1",
        learning_objectives=["objective_1"],
        blocks=[{"block_key": "b1", "type": "text", "text": "Test content", "citation_ids": []}],
    )
    pg_db.add(lv)
    pg_db.flush()
    lesson.current_published_version_id = lv.id
    cv.status = "published"
    course.current_active_version_id = cv.id
    pg_db.flush()

    doc = SourceDocument(
        workspace_id=ws.id, display_name="test.pdf",
        lifecycle_status="active",
    )
    pg_db.add(doc)
    pg_db.flush()
    dver = DocumentVersion(
        document_id=doc.id, version_number=1, processing_status="ready",
        original_filename="test.pdf", mime_type="application/pdf",
        byte_size=2048, sha256="0" * 64, original_storage_uri="file:///tmp/fake",
    )
    pg_db.add(dver)
    pg_db.flush()
    doc.current_version_id = dver.id
    pg_db.flush()

    chunk = DocumentChunk(
        id=f"chunk-prac-{uuid4().hex[:8]}",
        document_version_id=dver.id, ordinal=0,
        content="Evidence text for practice generation test.",
        content_hash="0" * 64, start_offset=0, end_offset=42,
    )
    pg_db.add(chunk)
    pg_db.flush()

    job = PracticeJob(
        course_id=course.id, workspace_id=ws.id,
        course_version_id=cv.id, lesson_id=lesson.id,
        lesson_version_id=lv.id,
        job_type="generate_set", output_language="zh-CN",
        difficulty="standard", item_count=2,
        request_hash="0" * 64,
        artifact_contract_version=ARTIFACT_CONTRACT_V2,
        idempotency_key=f"4chain-prac-{uuid4().hex[:8]}",
        attempt_count=0, status="running",
        worker_id="test-worker",
        lease_expires_at=datetime.now(timezone.utc).replace(
            year=datetime.now(timezone.utc).year + 1),
    )
    pg_db.add(job)
    pg_db.flush()
    pjs = PracticeJobSource(
        practice_job_id=job.id, workspace_id=ws.id,
        document_id=doc.id, document_version_id=dver.id,
    )
    pg_db.add(pjs)
    pg_db.flush()
    pg_db.commit()
    return job


# --- Practice grading seed -------------------------------------------------------

def _seed_grading_job(pg_db, ws):
    """Create the full infrastructure needed for a grading PracticeJob:
    Course, CourseVersion, Lesson, LessonVersion, PracticeSet, PracticeItem,
    PracticeAttempt, PracticeJob for grading. Includes CourseVersionSource
    with active SourceDocument so _course_version_degraded() returns False."""
    from learn_platform_api.db.models import (
        Course, CourseVersion, CourseSection, Lesson, LessonVersion,
        PracticeSet, PracticeItem, PracticeAttempt, PracticeJob,
        CourseVersionSource, SourceDocument, DocumentVersion,
    )

    course = Course(
        workspace_id=ws.id, title="GTest", goal="GTest",
        audience="general", lifecycle_status="active",
    )
    pg_db.add(course)
    pg_db.flush()
    cv = CourseVersion(
        course_id=course.id, workspace_id=ws.id,
        version_number=1, status="published", title="GTest", summary="GTest",
    )
    pg_db.add(cv)
    pg_db.flush()
    course.current_active_version_id = cv.id
    pg_db.flush()

    # SourceDocument + DocumentVersion + CourseVersionSource so
    # _course_version_degraded() returns False (source snapshot is fresh).
    doc = SourceDocument(
        workspace_id=ws.id, display_name="grading_source.pdf",
        lifecycle_status="active",
    )
    pg_db.add(doc)
    pg_db.flush()
    dver = DocumentVersion(
        document_id=doc.id, version_number=1, processing_status="ready",
        original_filename="grading_source.pdf", mime_type="application/pdf",
        byte_size=512, sha256="0" * 64, original_storage_uri="file:///tmp/fake",
    )
    pg_db.add(dver)
    pg_db.flush()
    doc.current_version_id = dver.id
    pg_db.flush()
    cvs = CourseVersionSource(
        course_version_id=cv.id, workspace_id=ws.id,
        document_id=doc.id, document_version_id=dver.id,
    )
    pg_db.add(cvs)
    pg_db.flush()

    section = CourseSection(
        course_version_id=cv.id, workspace_id=ws.id,
        ordinal=0, title="GS1", objective="GObj",
    )
    pg_db.add(section)
    pg_db.flush()
    lesson = Lesson(
        course_version_id=cv.id, course_section_id=section.id,
        workspace_id=ws.id, ordinal=0, title="GL1", objective="GObj",
    )
    pg_db.add(lesson)
    pg_db.flush()
    lv = LessonVersion(
        lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id,
        version_number=1, status="published", title="GL1",
        learning_objectives=["objective_1"],
        blocks=[{"block_key": "b1", "type": "text", "text": "Test content", "citation_ids": []}],
    )
    pg_db.add(lv)
    pg_db.flush()
    lesson.current_published_version_id = lv.id
    pg_db.flush()

    ps = PracticeSet(
        workspace_id=ws.id, course_id=course.id,
        course_version_id=cv.id, lesson_id=lesson.id,
        lesson_version_id=lv.id,
        output_language="zh-CN", difficulty="standard",
        item_count=1, lifecycle_status="active",
        generation_config={"item_count": 1, "difficulty": "standard"},
    )
    pg_db.add(ps)
    pg_db.flush()

    item = PracticeItem(
        practice_set_id=ps.id, workspace_id=ws.id,
        ordinal=0, item_type="short_answer",
        stem="What is X?",
        answer_spec={
            "reference_answer": "42",
            "rubric": [{"criterion_key": "c1", "description": "Correctness", "weight": 100}],
            "citation_ids": [],
            "_learning_target_key": "objective_1",
        },
    )
    pg_db.add(item)
    pg_db.flush()

    attempt = PracticeAttempt(
        practice_item_id=item.id, practice_job_id=None,
        workspace_id=ws.id,
        ordinal=0, item_type="short_answer",
        answer_payload={"text": "42"},
        idempotency_key=f"4chain-attempt-{uuid4().hex[:8]}",
        status="grading",
    )
    pg_db.add(attempt)
    pg_db.flush()

    job = PracticeJob(
        course_id=course.id, workspace_id=ws.id,
        course_version_id=cv.id, lesson_id=lesson.id,
        lesson_version_id=lv.id,
        practice_attempt_id=attempt.id,
        job_type="grade_attempt", output_language="zh-CN",
        difficulty="standard", item_count=1,
        request_hash="0" * 64,
        idempotency_key=f"4chain-grade-{uuid4().hex[:8]}",
        attempt_count=0, status="running",
        worker_id="test-worker",
        lease_expires_at=datetime.now(timezone.utc).replace(
            year=datetime.now(timezone.utc).year + 1),
    )
    pg_db.add(job)
    pg_db.flush()
    attempt.practice_job_id = job.id
    pg_db.flush()
    pg_db.commit()
    return job, attempt.id


# --- Sensitive field check -------------------------------------------------------

def _assert_no_sensitive_fields(pg_db) -> None:
    """Verify ProviderCall table does not contain prompt, answer, user answer,
    exception body, API key, internal URL or absolute path columns."""
    from learn_platform_api.db.models import ProviderCall
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(ProviderCall)
    column_names = {col.key for col in mapper.columns}
    forbidden = {
        "prompt", "question", "answer", "response", "evidence",
        "error_message", "error_body", "exception_body",
        "api_key", "authorization", "internal_url", "absolute_path",
        "user_answer", "raw_error",
    }
    found = column_names & forbidden
    assert not found, f"ProviderCall has forbidden columns: {found}"


# ============================================================================ #
# 1. Course generation — normal + repair (parameterized)                        #
# ============================================================================ #

EXPECTED_COURSE_CALLS = {"normal": 2, "repair": 3}


@pytest.mark.parametrize("scenario", ["normal", "repair"])
def test_course_generation_orchestration(pg_db, scenario: str) -> None:
    """Course generation chain: real execute_generation() produces ProviderCall
    facts with correct workspace, owner (AgentRun), phase, ordinal, usage.

    - normal: plan + generation phases (2 calls)
    - repair: plan + generation (invalid) + repair phases (3 calls)

    No exception swallowing — if orchestration fails, the test fails.
    Worker contract: service sets status but does not commit; we commit.
    """
    from learn_platform_api.services.course_generation import execute_generation

    ws = _ws(pg_db)
    settings = _make_settings()
    job, chunk = _seed_course_job(pg_db, ws)

    valid_outline = json.dumps({
        "title": "Test Course",
        "summary": "A test course",
        "sections": [{
            "title": "Section 1",
            "objective": "Obj 1",
            "citation_ids": ["e1"],
            "lessons": [{"title": "Lesson 1", "objective": "Obj 1", "citation_ids": ["e1"]}],
        }],
    })

    if scenario == "normal":
        plan_content = json.dumps({"queries": ["search query 1"]})
        side_effects = [
            _fake_provider_response(content=plan_content, usage_input=200, usage_output=100),
            _fake_provider_response(content=valid_outline, usage_input=500, usage_output=300),
        ]
    else:
        plan_content = json.dumps({"queries": ["search query 1"]})
        invalid_outline = json.dumps({"not": "a valid outline"})
        side_effects = [
            _fake_provider_response(content=plan_content, usage_input=200, usage_output=100),
            _fake_provider_response(content=invalid_outline, usage_input=400, usage_output=200),
            _fake_provider_response(content=valid_outline, usage_input=600, usage_output=350),
        ]

    with patch("learn_platform_api.services.course_generation.httpx.post") as mock_post, \
         patch("learn_platform_api.services.course_generation.retrieve") as mock_retrieve:
        mock_post.side_effect = side_effects
        from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
        mock_retrieve.return_value = ("qt-1", [
            RetrievalResult(
                score=0.9, text=chunk.content,
                citation=CitationRead(
                    document_id=chunk.document_version_id,
                    document_version_id=chunk.document_version_id,
                    chunk_id=chunk.id,
                    document_name="Doc",
                    heading_path=[], start_offset=0, end_offset=len(chunk.content),
                ),
            ),
        ])
        # No try/except — orchestration must succeed normally
        execute_generation(pg_db, settings, job)

    # Worker contract: service sets status but does not commit
    pg_db.commit()

    expected_count = EXPECTED_COURSE_CALLS[scenario]

    # Assert mock call_count matches expected
    assert mock_post.call_count == expected_count, \
        f"mock_post.call_count={mock_post.call_count}, expected {expected_count}"

    # Assert AgentRun owner exists and succeeded
    run_data = _query_run(pg_db, course_generation_job_id=job.id)
    assert run_data is not None, "AgentRun owner must exist"
    assert run_data["workspace_id"] == ws.id
    assert run_data["status"] == "succeeded", \
        f"AgentRun must be succeeded, got {run_data['status']}"

    # Assert CourseGenerationJob succeeded and produced a CourseVersion
    job_data = _query_job(pg_db, job.id)
    assert job_data is not None
    assert job_data["status"] == "succeeded", \
        f"CourseGenerationJob must be succeeded, got {job_data['status']}"
    assert job_data["course_version_id"] is not None, \
        "CourseGenerationJob must have produced a course_version_id"

    # Assert ProviderCall count exactly matches mock call_count
    calls = _query_calls(pg_db, agent_run_id=run_data["id"])
    assert len(calls) == expected_count, \
        f"Expected exactly {expected_count} ProviderCalls, got {len(calls)}"

    for c in calls:
        assert c["workspace_id"] == ws.id
        assert c["agent_run_id"] == run_data["id"]
        assert c["rag_answer_trace_id"] is None

    ordinals = [c["ordinal"] for c in calls]
    assert ordinals == list(range(expected_count)), \
        f"Ordinals must be 0..{expected_count - 1}, got {ordinals}"

    if scenario == "normal":
        assert calls[0]["phase"] == "plan"
        assert calls[1]["phase"] == "generation"
        assert all(c["status"] == "succeeded" for c in calls)
    else:
        assert calls[0]["phase"] == "plan"
        assert calls[1]["phase"] == "generation"
        assert calls[2]["phase"] == "repair"
        assert all(c["status"] == "succeeded" for c in calls)

    for c in calls:
        assert c["provider"] == "deepseek"
        assert c["model"] == "deepseek-v4-flash"
        assert c["input_tokens"] is not None
        assert c["output_tokens"] is not None

    _assert_no_sensitive_fields(pg_db)


# ============================================================================ #
# 2. Practice generation — normal + repair (parameterized)                      #
# ============================================================================ #

EXPECTED_PRACTICE_GEN_CALLS = {"normal": 2, "repair": 3}


@pytest.mark.parametrize("scenario", ["normal", "repair"])
def test_practice_generation_orchestration(pg_db, scenario: str) -> None:
    """Practice generation chain: real execute_generation() produces ProviderCall
    facts with correct workspace, owner (AgentRun with role exercise_author),
    phase, ordinal, usage.

    - normal: plan + generation (2 calls)
    - repair: plan + generation (invalid) + repair (3 calls)

    No exception swallowing — if orchestration fails, the test fails.
    Worker contract: service sets status but does not commit; we commit.
    """
    from learn_platform_api.services.practice_generation import execute_generation

    ws = _ws(pg_db)
    settings = _make_settings()
    job = _seed_practice_job(pg_db, ws)

    valid_practice = json.dumps({
        "items": [{
            "item_key": "i1",
            "target_key": "objective_1",
            "item_type": "short_answer",
            "stem": "What is 2+2?",
            "reference_answer": "4",
            "rubric": [{"criterion_key": "c1", "description": "Correctness", "weight": 100}],
            "citation_ids": ["e1"],
        }, {
            "item_key": "i2",
            "target_key": "objective_1",
            "item_type": "single_choice",
            "stem": "Choose the even number",
            "options": [
                {"option_key": "A", "text": "1", "is_correct": False, "rationale": "Odd", "citation_ids": []},
                {"option_key": "B", "text": "2", "is_correct": True, "rationale": "Even", "citation_ids": ["e1"]},
            ],
            "citation_ids": ["e1"],
        }],
    })

    plan_content = json.dumps({"queries": ["practice search query"]})

    if scenario == "normal":
        side_effects = [
            (json.loads(plan_content), {"input_tokens": 200, "output_tokens": 100, "finish_reason": "stop"}),
            (json.loads(valid_practice), {"input_tokens": 800, "output_tokens": 400, "finish_reason": "stop"}),
        ]
    else:
        invalid_practice = json.dumps({"not": "valid"})
        side_effects = [
            (json.loads(plan_content), {"input_tokens": 200, "output_tokens": 100, "finish_reason": "stop"}),
            (json.loads(invalid_practice), {"input_tokens": 600, "output_tokens": 300, "finish_reason": "stop"}),
            (json.loads(valid_practice), {"input_tokens": 900, "output_tokens": 500, "finish_reason": "stop"}),
        ]

    with patch("learn_platform_api.services.practice_generation.call_practice_provider") as mock_call, \
         patch("learn_platform_api.services.practice_generation.retrieve") as mock_retrieve, \
         patch("learn_platform_api.services.readiness._read_capability_projection") as mock_cap, \
         patch("learn_platform_api.services.practice_generation._sources") as mock_sources:
        mock_call.side_effect = side_effects
        mock_cap.return_value = {"ok": False}

        from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
        from learn_platform_api.db.models import DocumentChunk
        chunk = pg_db.scalar(select(DocumentChunk).limit(1))
        mock_retrieve.return_value = ("qt-1", [
            RetrievalResult(
                score=0.9, text=chunk.content if chunk else "Evidence",
                citation=CitationRead(
                    document_id="d1", document_version_id="v1",
                    chunk_id=chunk.id if chunk else "c1",
                    document_name="Doc", heading_path=[],
                    start_offset=0, end_offset=20,
                ),
            ),
        ])

        from learn_platform_api.db.models import PracticeJobSource, SourceDocument, DocumentVersion
        rows = list(pg_db.execute(
            select(PracticeJobSource, SourceDocument, DocumentVersion)
            .join(SourceDocument, PracticeJobSource.document_id == SourceDocument.id)
            .join(DocumentVersion, PracticeJobSource.document_version_id == DocumentVersion.id)
            .where(PracticeJobSource.practice_job_id == job.id)
        ).all())
        mock_sources.return_value = rows

        # No try/except — orchestration must succeed normally
        execute_generation(pg_db, settings, job, worker_id="test-worker")

    # Worker contract: service sets status but does not commit
    pg_db.commit()

    expected_count = EXPECTED_PRACTICE_GEN_CALLS[scenario]

    # Assert mock call_count matches expected
    assert mock_call.call_count == expected_count, \
        f"mock_call.call_count={mock_call.call_count}, expected {expected_count}"

    # Assert AgentRun owner exists and succeeded
    run_data = _query_run(pg_db, practice_job_id=job.id, role="exercise_author")
    assert run_data is not None, "AgentRun owner (exercise_author) must exist"
    assert run_data["workspace_id"] == ws.id
    assert run_data["status"] == "succeeded", \
        f"AgentRun must be succeeded, got {run_data['status']}"

    # Assert PracticeJob succeeded and produced a PracticeSet
    pjob_data = _query_practice_job(pg_db, job.id)
    assert pjob_data is not None
    assert pjob_data["status"] == "succeeded", \
        f"PracticeJob must be succeeded, got {pjob_data['status']}"
    assert pjob_data["practice_set_id"] is not None, \
        "PracticeJob must have produced a practice_set_id"

    # Assert ProviderCall count exactly matches mock call_count
    calls = _query_calls(pg_db, agent_run_id=run_data["id"])
    assert len(calls) == expected_count, \
        f"Expected exactly {expected_count} ProviderCalls, got {len(calls)}"

    for c in calls:
        assert c["workspace_id"] == ws.id
        assert c["agent_run_id"] == run_data["id"]
        assert c["rag_answer_trace_id"] is None

    ordinals = [c["ordinal"] for c in calls]
    assert ordinals == list(range(expected_count)), \
        f"Ordinals must be 0..{expected_count - 1}, got {ordinals}"

    if scenario == "normal":
        assert calls[0]["phase"] == "plan"
        assert calls[1]["phase"] == "generation"
    else:
        assert calls[0]["phase"] == "plan"
        assert calls[1]["phase"] == "generation"
        assert calls[2]["phase"] == "repair"

    for c in calls:
        assert c["status"] == "succeeded"
        assert c["provider"] == "deepseek"
        assert c["input_tokens"] is not None
        assert c["output_tokens"] is not None

    _assert_no_sensitive_fields(pg_db)


# ============================================================================ #
# 3. Practice grading — normal + repair (parameterized)                         #
# ============================================================================ #

EXPECTED_PRACTICE_GRADE_CALLS = {"normal": 1, "repair": 2}


@pytest.mark.parametrize("scenario", ["normal", "repair"])
def test_practice_grading_orchestration(pg_db, scenario: str) -> None:
    """Practice grading chain: real execute_grading() produces ProviderCall
    facts with correct workspace, owner (AgentRun with role answer_grader),
    phase, ordinal, usage. Uses short_answer path (no Judge0/Wolfram).

    - normal: grading (1 call)
    - repair: grading (invalid) + repair (2 calls)

    No exception swallowing — if orchestration fails, the test fails.
    Worker contract: service sets status but does not commit; we commit.
    """
    from learn_platform_api.services.practice_generation import execute_grading

    ws = _ws(pg_db)
    settings = _make_settings()
    job, attempt_id = _seed_grading_job(pg_db, ws)

    valid_feedback = json.dumps({
        "verdict": "correct",
        "score": 100,
        "criterion_results": [{"criterion_key": "c1", "score": 100, "feedback": "Correct", "met": "full", "note": "Well done"}],
        "blocks": [{"block_key": "b1", "type": "explanation", "text": "Correct answer", "citation_ids": []}],
    })

    if scenario == "normal":
        side_effects = [
            (json.loads(valid_feedback), {"input_tokens": 300, "output_tokens": 150, "finish_reason": "stop"}),
        ]
    else:
        invalid_feedback = json.dumps({"not": "valid feedback"})
        side_effects = [
            (json.loads(invalid_feedback), {"input_tokens": 300, "output_tokens": 150, "finish_reason": "stop"}),
            (json.loads(valid_feedback), {"input_tokens": 400, "output_tokens": 200, "finish_reason": "stop"}),
        ]

    with patch("learn_platform_api.services.practice_generation.call_provider") as mock_call:
        mock_call.side_effect = side_effects
        # No try/except — orchestration must succeed normally
        execute_grading(pg_db, settings, job, worker_id="test-worker")

    # Worker contract: service sets status but does not commit
    pg_db.commit()

    expected_count = EXPECTED_PRACTICE_GRADE_CALLS[scenario]

    # Assert mock call_count matches expected
    assert mock_call.call_count == expected_count, \
        f"mock_call.call_count={mock_call.call_count}, expected {expected_count}"

    # Assert AgentRun owner exists and succeeded
    run_data = _query_run(pg_db, practice_job_id=job.id, role="answer_grader")
    assert run_data is not None, "AgentRun owner (answer_grader) must exist"
    assert run_data["workspace_id"] == ws.id
    assert run_data["status"] == "succeeded", \
        f"AgentRun must be succeeded, got {run_data['status']}"

    # Assert PracticeJob succeeded
    pjob_data = _query_practice_job(pg_db, job.id)
    assert pjob_data is not None
    assert pjob_data["status"] == "succeeded", \
        f"PracticeJob must be succeeded, got {pjob_data['status']}"

    # Assert PracticeAttempt succeeded
    attempt_data = _query_attempt(pg_db, attempt_id)
    assert attempt_data is not None
    assert attempt_data["status"] == "succeeded", \
        f"PracticeAttempt must be succeeded, got {attempt_data['status']}"

    # Assert ProviderCall count exactly matches mock call_count
    calls = _query_calls(pg_db, agent_run_id=run_data["id"])
    assert len(calls) == expected_count, \
        f"Expected exactly {expected_count} ProviderCalls, got {len(calls)}"

    for c in calls:
        assert c["workspace_id"] == ws.id
        assert c["agent_run_id"] == run_data["id"]
        assert c["rag_answer_trace_id"] is None

    ordinals = [c["ordinal"] for c in calls]
    assert ordinals == list(range(expected_count)), \
        f"Ordinals must be 0..{expected_count - 1}, got {ordinals}"

    if scenario == "normal":
        assert calls[0]["phase"] == "grading"
    else:
        assert calls[0]["phase"] == "grading"
        assert calls[1]["phase"] == "repair"

    for c in calls:
        assert c["status"] == "succeeded", \
            f"Call ordinal={c['ordinal']} phase={c['phase']} status={c['status']} error_code={c['error_code']}"
        assert c["provider"] == "deepseek"
        assert c["model"] == "deepseek-v4-flash"
        assert c["input_tokens"] is not None
        assert c["output_tokens"] is not None

    _assert_no_sensitive_fields(pg_db)


# ============================================================================ #
# 4. RAG Answer — normal + repair (parameterized)                               #
# ============================================================================ #

EXPECTED_RAG_CALLS = {"normal": 1, "repair": 2}


@pytest.mark.parametrize("scenario", ["normal", "repair"])
def test_rag_answer_orchestration(pg_db, scenario: str) -> None:
    """RAG Answer chain: real answer_question() produces ProviderCall
    facts with correct workspace, owner (RagAnswerTrace), phase, ordinal, usage.

    - normal: answer (1 call)
    - repair: answer (invalid) + repair (2 calls)

    answer_question() commits internally; no additional commit needed.
    """
    from learn_platform_api.services.answers import answer_question

    ws = _ws(pg_db)
    settings = _make_settings()

    valid_answer = json.dumps({
        "claims": [{"text": "X is 42", "citation_ids": ["c1"]}],
        "limitations": [],
    })

    if scenario == "normal":
        side_effects = [
            _fake_provider_response(content=valid_answer, usage_input=300, usage_output=150),
        ]
    else:
        invalid_answer = json.dumps({"not": "valid claims format"})
        side_effects = [
            _fake_provider_response(content=invalid_answer, usage_input=300, usage_output=150),
            _fake_provider_response(content=valid_answer, usage_input=400, usage_output=200),
        ]

    fake_result = _fake_retrieval_result()

    with patch("learn_platform_api.services.answers.retrieve") as mock_retrieve, \
         patch("learn_platform_api.services.answers.httpx.post") as mock_post:
        mock_retrieve.return_value = (None, [fake_result])
        mock_post.side_effect = side_effects

        result = answer_question(
            pg_db, settings, ws.id, "What is X?", top_k=5,
            document_ids=None,
        )

    assert result["status"] == "succeeded"
    trace_id = result["trace_id"]

    expected_count = EXPECTED_RAG_CALLS[scenario]

    # Assert mock call_count matches expected
    assert mock_post.call_count == expected_count, \
        f"mock_post.call_count={mock_post.call_count}, expected {expected_count}"

    # Assert RagAnswerTrace succeeded
    trace_data = _query_trace(pg_db, id=trace_id)
    assert trace_data is not None
    assert trace_data["workspace_id"] == ws.id
    assert trace_data["status"] == "succeeded", \
        f"RagAnswerTrace must be succeeded, got {trace_data['status']}"

    # Assert ProviderCall count exactly matches mock call_count
    calls = _query_calls(pg_db, rag_answer_trace_id=trace_id)
    assert len(calls) == expected_count, \
        f"Expected exactly {expected_count} ProviderCalls, got {len(calls)}"

    for c in calls:
        assert c["workspace_id"] == ws.id
        assert c["rag_answer_trace_id"] == trace_id
        assert c["agent_run_id"] is None

    ordinals = [c["ordinal"] for c in calls]
    assert ordinals == list(range(expected_count)), \
        f"Ordinals must be 0..{expected_count - 1}, got {ordinals}"

    if scenario == "normal":
        assert calls[0]["phase"] == "answer"
    else:
        assert calls[0]["phase"] == "answer"
        assert calls[1]["phase"] == "repair"

    for c in calls:
        assert c["status"] == "succeeded"
        assert c["provider"] == "deepseek"
        assert c["model"] == "deepseek-v4-flash"
        assert c["input_tokens"] is not None
        assert c["output_tokens"] is not None

    _assert_no_sensitive_fields(pg_db)


# ============================================================================ #
# 5. RAG Answer — timeout                                                       #
# ============================================================================ #

def test_rag_answer_timeout_orchestration(pg_db) -> None:
    """RAG Answer timeout: answer_question() with httpx.TimeoutException
    produces exactly 1 timed_out ProviderCall with error_code=provider_timeout.
    The RagAnswerTrace must be in failed status with a stable error code.
    The ProviderCall must survive (ADR 004) and be queryable from a new session."""
    import httpx
    from learn_platform_api.services.answers import answer_question
    from learn_platform_api.services.provider_call_recorder import (
        STATUS_TIMED_OUT, PROVIDER_TIMEOUT,
    )

    ws = _ws(pg_db)
    settings = _make_settings()
    fake_result = _fake_retrieval_result()

    with patch("learn_platform_api.services.answers.retrieve") as mock_retrieve, \
         patch("learn_platform_api.services.answers.httpx.post") as mock_post:
        mock_retrieve.return_value = (None, [fake_result])
        mock_post.side_effect = httpx.TimeoutException("read timeout")

        with pytest.raises(ValueError, match="generation_provider_unavailable"):
            answer_question(
                pg_db, settings, ws.id, "What is X?", top_k=5,
                document_ids=None,
            )

    # Assert mock was called exactly once
    assert mock_post.call_count == 1, \
        f"mock_post.call_count={mock_post.call_count}, expected 1"

    trace_data = _query_trace(pg_db, workspace_id=ws.id)
    assert trace_data is not None
    assert trace_data["status"] == "failed"
    assert trace_data["error_code"] is not None

    calls = _query_calls(pg_db, rag_answer_trace_id=trace_data["id"])
    assert len(calls) == 1, f"Expected exactly 1 ProviderCall, got {len(calls)}"

    assert calls[0]["status"] == STATUS_TIMED_OUT
    assert calls[0]["error_code"] == PROVIDER_TIMEOUT
    assert calls[0]["phase"] == "answer"
    assert calls[0]["ordinal"] == 0
    assert calls[0]["workspace_id"] == ws.id
    assert calls[0]["rag_answer_trace_id"] == trace_data["id"]
    assert calls[0]["agent_run_id"] is None

    _assert_no_sensitive_fields(pg_db)


# ============================================================================ #
# 6. Owner mutual exclusion — all four chains                                   #
# ============================================================================ #

def test_owner_mutual_exclusion_across_chains(pg_db) -> None:
    """After running Course generation and RAG Answer in the same workspace,
    verify that no ProviderCall has both agent_run_id and rag_answer_trace_id
    set (owner mutual exclusion, Spec 003 §4)."""
    from learn_platform_api.services.course_generation import execute_generation
    from learn_platform_api.services.answers import answer_question

    ws = _ws(pg_db)
    settings = _make_settings()

    # --- Course generation ---
    job, chunk = _seed_course_job(pg_db, ws)
    plan_content = json.dumps({"queries": ["q1"]})
    valid_outline = json.dumps({
        "title": "T", "summary": "S",
        "sections": [{"title": "S1", "objective": "O1", "citation_ids": ["e1"],
                      "lessons": [{"title": "L1", "objective": "O1", "citation_ids": ["e1"]}]}],
    })

    with patch("learn_platform_api.services.course_generation.httpx.post") as mock_post, \
         patch("learn_platform_api.services.course_generation.retrieve") as mock_retrieve:
        mock_post.side_effect = [
            _fake_provider_response(content=plan_content),
            _fake_provider_response(content=valid_outline),
        ]
        from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
        mock_retrieve.return_value = ("qt-1", [
            RetrievalResult(
                score=0.9, text=chunk.content,
                citation=CitationRead(
                    document_id=chunk.document_version_id,
                    document_version_id=chunk.document_version_id,
                    chunk_id=chunk.id,
                    document_name="D",
                    heading_path=[], start_offset=0, end_offset=len(chunk.content),
                ),
            ),
        ])
        execute_generation(pg_db, settings, job)

    pg_db.commit()

    # --- RAG Answer ---
    valid_answer = json.dumps({
        "claims": [{"text": "fact", "citation_ids": ["c1"]}],
        "limitations": [],
    })
    fake_result = _fake_retrieval_result()

    with patch("learn_platform_api.services.answers.retrieve") as mock_retrieve, \
         patch("learn_platform_api.services.answers.httpx.post") as mock_post:
        mock_retrieve.return_value = (None, [fake_result])
        mock_post.return_value = _fake_provider_response(content=valid_answer)

        result = answer_question(
            pg_db, settings, ws.id, "What is Y?", top_k=5,
            document_ids=None,
        )

    assert result["status"] == "succeeded"

    all_calls = _query_calls(pg_db, workspace_id=ws.id)
    assert len(all_calls) == 3, f"Expected exactly 3 ProviderCalls, got {len(all_calls)}"

    for c in all_calls:
        has_run = c["agent_run_id"] is not None
        has_trace = c["rag_answer_trace_id"] is not None
        assert not (has_run and has_trace), \
            f"ProviderCall {c['id']} has both owners set — violates mutual exclusion"

    course_calls = [c for c in all_calls if c["agent_run_id"] is not None]
    rag_calls = [c for c in all_calls if c["rag_answer_trace_id"] is not None]
    assert len(course_calls) == 2
    assert len(rag_calls) == 1

    _assert_no_sensitive_fields(pg_db)


# ============================================================================ #
# 7. Course generation — provider failure (timeout)                              #
# ============================================================================ #

def test_course_generation_provider_failure_orchestration(pg_db) -> None:
    """Course generation with provider timeout: execute_generation() raises,
    but the AgentRun owner and exactly 1 timed_out ProviderCall persist (ADR 004)."""
    import httpx
    from learn_platform_api.services.course_generation import execute_generation
    from learn_platform_api.services.provider_call_recorder import (
        STATUS_TIMED_OUT, PROVIDER_TIMEOUT,
    )

    ws = _ws(pg_db)
    settings = _make_settings()
    job, _chunk = _seed_course_job(pg_db, ws)

    with patch("learn_platform_api.services.course_generation.httpx.post") as mock_post:
        mock_post.side_effect = httpx.TimeoutException("read timeout")

        # Course provider timeout surfaces as the stable ValueError error code
        # raised by call_provider() — matches RAG timeout + recorder course tests.
        with pytest.raises(ValueError, match="generation_provider_unavailable"):
            execute_generation(pg_db, settings, job)

    # Assert mock was called exactly once
    assert mock_post.call_count == 1, \
        f"mock_post.call_count={mock_post.call_count}, expected 1"

    pg_db.rollback()

    run_data = _query_run(pg_db, course_generation_job_id=job.id)
    assert run_data is not None, "AgentRun owner must persist after timeout (ADR 004)"

    calls = _query_calls(pg_db, agent_run_id=run_data["id"])
    assert len(calls) == 1, f"Expected exactly 1 ProviderCall, got {len(calls)}"

    assert calls[0]["status"] == STATUS_TIMED_OUT
    assert calls[0]["error_code"] == PROVIDER_TIMEOUT
    assert calls[0]["phase"] == "plan"
    assert calls[0]["ordinal"] == 0
    assert calls[0]["workspace_id"] == ws.id

    _assert_no_sensitive_fields(pg_db)
