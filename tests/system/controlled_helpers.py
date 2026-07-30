"""Shared helpers for the Slice 2B Batch B controlled system tests.

Drives the REAL public HTTP API, the REAL Redis workers (out of process), the
REAL Postgres (authoritative facts read from NEW sessions), and the REAL MCP
clients — only the lowest-level external boundaries are controlled fakes (model
stub, fake execution backend, fake Wolfram), reset/counted atomically.

No product code is imported for mutation. Evidence is read from the API or from
a fresh Postgres Session, never from mock call counts alone (Spec 006 §4.2).
"""

from __future__ import annotations

import os
import time
from uuid import uuid4

import httpx
import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from redis import Redis
from rq import Worker
from sqlalchemy import select

from learn_platform_api.db.session import SessionLocal
from learn_platform_api.settings import get_settings
from learn_platform_api.workers import ensure_collection

API_URL = os.environ.get("SYSTEM_TEST_API_URL", "http://api:8000").rstrip("/")
STUB_URL = os.environ.get("SYSTEM_TEST_STUB_URL", "http://model-services-stub:8090").rstrip("/")
FAKE_EXEC_URL = os.environ.get("SYSTEM_TEST_FAKE_EXEC_URL", "http://fake-execution-backend:8110").rstrip("/")
FAKE_WOLFRAM_URL = os.environ.get("SYSTEM_TEST_FAKE_WOLFRAM_URL", "http://fake-wolfram:8120").rstrip("/")

JOB_TERMINAL = {"succeeded", "failed", "canceled", "retry_wait", "queue_failed"}
TURN_TERMINAL = {"succeeded", "failed", "canceled"}


# ---------------------------------------------------------------------------
# Reset / counters (atomic; scenario reset + count are owned by each fake)
# ---------------------------------------------------------------------------

def reset_stub(scenario: str) -> None:
    httpx.post(f"{STUB_URL}/__reset", json={"scenario": scenario}, timeout=5).raise_for_status()


def stub_calls(scenario: str) -> int:
    return int(httpx.get(f"{STUB_URL}/__calls/{scenario}", timeout=5).json()["count"])


def reset_fake_exec(scenario: str = "default") -> None:
    httpx.post(f"{FAKE_EXEC_URL}/__reset", json={"scenario": scenario}, timeout=5).raise_for_status()


def fake_exec_calls(scenario: str = "default") -> int:
    return int(httpx.get(f"{FAKE_EXEC_URL}/__calls/{scenario}", timeout=5).json()["count"])


def reset_fake_wolfram(scenario: str = "success") -> None:
    httpx.post(f"{FAKE_WOLFRAM_URL}/__reset", json={"scenario": scenario}, timeout=5).raise_for_status()


def fake_wolfram_calls(scenario: str = "success") -> int:
    return int(httpx.get(f"{FAKE_WOLFRAM_URL}/__calls/{scenario}", timeout=5).json()["count"])


# ---------------------------------------------------------------------------
# Environment readiness — polls health/status, never a fixed sleep
# ---------------------------------------------------------------------------

def _workers_subscribed(redis_url: str, queue: str) -> bool:
    redis = Redis.from_url(redis_url)
    try:
        return any(queue in w.queue_names() for w in Worker.all(connection=redis))
    finally:
        redis.close()


def wait_for_environment(*, practice: bool = False, tutor: bool = False) -> None:
    """Fail (not skip) if a required service/worker/capability is unavailable."""
    deadline = time.monotonic() + 180
    last = "not started"
    settings = get_settings()
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{API_URL}/ready", timeout=3).status_code != 200:
                raise RuntimeError("api_not_ready")
            if httpx.get(f"{STUB_URL}/readyz", timeout=2).status_code != 200:
                raise RuntimeError("stub_not_ready")
            if httpx.get(f"{FAKE_EXEC_URL}/readyz", timeout=2).status_code != 200:
                raise RuntimeError("fake_exec_not_ready")
            if httpx.get(f"{FAKE_WOLFRAM_URL}/readyz", timeout=2).status_code != 200:
                raise RuntimeError("fake_wolfram_not_ready")
            if practice and not _workers_subscribed(settings.redis_url, settings.practice_queue_name):
                raise RuntimeError("practice_worker_not_subscribed")
            if tutor and not _workers_subscribed(settings.redis_url, settings.tutor_queue_name):
                raise RuntimeError("tutor_worker_not_subscribed")
            # Capability projections (written by the real probe) must be ready.
            ready = httpx.get(f"{API_URL}/ready", timeout=3).json()
            checks = ready.get("checks", {})
            if practice and not checks.get("code_execution", {}).get("ok"):
                raise RuntimeError("code_execution_not_ready")
            if not checks.get("science_tool", {}).get("ok"):
                raise RuntimeError("science_tool_not_ready")
            return
        except Exception as exc:  # retry until deadline
            last = f"{type(exc).__name__}:{exc}"
            time.sleep(2)
    raise AssertionError(f"environment_failed:{last}")


# ---------------------------------------------------------------------------
# Seeding — authoritative workspace/course/lesson/source/chunk facts
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def seed_practice_lesson(*, algorithmic=False, executable=False, math=False,
                         physics=False, chemistry=False, computable=False) -> dict:
    """Seed a workspace/course/version/section/lesson + source/chunk and embed
    the chunk in Qdrant so the REAL retrieval returns it as evidence e1."""
    from learn_platform_api.db.models import (
        Course, CourseSection, CourseVersion, CourseVersionSource,
        DocumentChunk, DocumentVersion, Lesson, LessonVersion, SourceDocument, Workspace,
    )

    with SessionLocal() as db:
        ws = Workspace(name=f"Practice {uuid4().hex[:6]}", slug=f"practice-{uuid4().hex[:8]}")
        db.add(ws); db.flush()
        doc = SourceDocument(workspace_id=ws.id, display_name="lesson_source.md", lifecycle_status="active")
        db.add(doc); db.flush()
        ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready",
                              original_filename="lesson_source.md", mime_type="text/markdown",
                              byte_size=128, sha256="a" * 64, original_storage_uri="file:///controlled")
        db.add(ver); db.flush()
        doc.current_version_id = ver.id
        chunk_id = str(uuid4())
        chunk = DocumentChunk(id=chunk_id, document_version_id=ver.id, ordinal=0,
                              content="Evidence text supporting the learning target.",
                              content_hash="b" * 64, start_offset=0, end_offset=48, page_start=1, page_end=1)
        db.add(chunk)
        course = Course(workspace_id=ws.id, title=f"C{uuid4().hex[:4]}", goal="g", audience="general", lifecycle_status="active")
        db.add(course); db.flush()
        cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active",
                           title=course.title, summary="s")
        db.add(cv); db.flush()
        course.current_active_version_id = cv.id
        db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id,
                                   document_id=doc.id, document_version_id=ver.id))
        section = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="s", objective="o")
        db.add(section); db.flush()
        lesson = Lesson(course_version_id=cv.id, course_section_id=section.id, workspace_id=ws.id,
                        ordinal=0, title="L", objective="o")
        db.add(lesson); db.flush()
        lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1,
                           status="published", title="L", learning_objectives=["objective_1"],
                           blocks=[{"block_key": "b1", "type": "text", "text": "body", "citation_ids": []}],
                           practice_type_hints=[{
                               "objective_key": "objective_1", "evidence_keys": ["e1"],
                               "has_algorithmic_objective": algorithmic,
                               "has_executable_evidence": executable,
                               "has_math_objective": math,
                               "has_physics_objective": physics,
                               "has_chemistry_objective": chemistry,
                               "has_computable_evidence": computable,
                           }])
        db.add(lv); db.flush()
        lesson.current_published_version_id = lv.id
        db.commit()
        fixture = {"workspace_id": ws.id, "course_id": course.id, "course_version_id": cv.id,
                   "section_id": section.id, "lesson_id": lesson.id, "lesson_version_id": lv.id,
                   "document_id": doc.id, "chunk_id": chunk_id}

    settings = get_settings()
    qdrant = QdrantClient(url=settings.qdrant_url)
    try:
        ensure_collection(qdrant, settings)
        qdrant.upsert(collection_name=settings.product_collection_name, wait=True, points=[
            PointStruct(id=chunk_id, vector=[1.0, 0.0, 0.0, 0.0],
                        payload={"workspace_id": fixture["workspace_id"],
                                 "document_id": fixture["document_id"], "chunk_id": chunk_id})])
    finally:
        qdrant.close()
    return fixture


def seed_tutor_course() -> dict:
    """Seed a workspace/course/version + source/chunk for a course-scope Tutor turn."""
    from learn_platform_api.db.models import (
        Course, CourseVersion, CourseVersionSource, DocumentChunk, DocumentVersion,
        Lesson, LessonVersion, SourceDocument, Workspace,
    )
    with SessionLocal() as db:
        ws = Workspace(name=f"Tutor {uuid4().hex[:6]}", slug=f"tutor-{uuid4().hex[:8]}")
        db.add(ws); db.flush()
        doc = SourceDocument(workspace_id=ws.id, display_name="tutor_source.md", lifecycle_status="active")
        db.add(doc); db.flush()
        ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready",
                              original_filename="tutor_source.md", mime_type="text/markdown",
                              byte_size=64, sha256="a" * 64, original_storage_uri="file:///controlled")
        db.add(ver); db.flush()
        doc.current_version_id = ver.id
        chunk_id = str(uuid4())
        chunk = DocumentChunk(id=chunk_id, document_version_id=ver.id, ordinal=0,
                              content="Binary search halves the remaining sorted interval.",
                              content_hash="b" * 64, start_offset=0, end_offset=44, page_start=1, page_end=1)
        db.add(chunk)
        course = Course(workspace_id=ws.id, title=f"TC{uuid4().hex[:4]}", goal="g", audience="general", lifecycle_status="active")
        db.add(course); db.flush()
        cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active",
                           title=course.title, summary="s")
        db.add(cv); db.flush()
        course.current_active_version_id = cv.id
        db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id,
                                   document_id=doc.id, document_version_id=ver.id))
        db.commit()
        fixture = {"workspace_id": ws.id, "course_id": course.id, "course_version_id": cv.id,
                   "document_id": doc.id, "chunk_id": chunk_id}

    settings = get_settings()
    qdrant = QdrantClient(url=settings.qdrant_url)
    try:
        ensure_collection(qdrant, settings)
        qdrant.upsert(collection_name=settings.product_collection_name, wait=True, points=[
            PointStruct(id=chunk_id, vector=[1.0, 0.0, 0.0, 0.0],
                        payload={"workspace_id": fixture["workspace_id"],
                                 "document_id": fixture["document_id"], "chunk_id": chunk_id})])
    finally:
        qdrant.close()
    return fixture


# ---------------------------------------------------------------------------
# Practice API driver
# ---------------------------------------------------------------------------

def create_practice_set(client: httpx.Client, fx: dict, *, item_count: int, mode: str,
                        language: str | None = None, code_auth: bool = False,
                        science_auth: bool = False) -> dict:
    body = {
        "item_count": item_count, "difficulty": "standard", "output_language": "zh-CN",
        "external_processing_ack": True, "item_type_mode": mode,
        "code_tool_authorized": code_auth, "science_tool_authorized": science_auth,
    }
    if language:
        body["code_languages"] = [language]
    r = client.post(
        f"/api/v1/workspaces/{fx['workspace_id']}/courses/{fx['course_id']}/versions/"
        f"{fx['course_version_id']}/lessons/{fx['lesson_id']}/versions/{fx['lesson_version_id']}/practice-sets",
        headers={"Idempotency-Key": f"sys-{uuid4()}"}, json=body, timeout=10)
    assert r.status_code == 202, f"create_practice_set failed: {r.status_code} {r.text[:300]}"
    return r.json()


def poll_job(client: httpx.Client, workspace_id: str, job_id: str, timeout: int = 90) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        r = client.get(f"/api/v1/workspaces/{workspace_id}/practice-jobs/{job_id}", timeout=5)
        r.raise_for_status()
        last = r.json()
        if last["status"] in JOB_TERMINAL:
            return last
        time.sleep(0.5)
    raise AssertionError(f"timed_out:job={job_id}:last={last.get('status')}")


def get_set(client: httpx.Client, workspace_id: str, set_id: str) -> dict:
    r = client.get(f"/api/v1/workspaces/{workspace_id}/practice-sets/{set_id}", timeout=5)
    r.raise_for_status()
    return r.json()


def submit_attempt(client: httpx.Client, workspace_id: str, item_id: str, *, source_code: str | None = None,
                   text: str | None = None, science_auth: bool = False) -> dict:
    body = {"external_processing_ack": True, "science_tool_authorized": science_auth}
    if source_code is not None:
        body["source_code"] = source_code
    if text is not None:
        body["text"] = text
    r = client.post(f"/api/v1/workspaces/{workspace_id}/practice-items/{item_id}/attempts",
                    headers={"Idempotency-Key": f"sys-{uuid4()}"}, json=body, timeout=10)
    assert r.status_code in (200, 201, 202), f"submit_attempt failed: {r.status_code} {r.text[:300]}"
    return r.json()


def poll_attempt(client: httpx.Client, workspace_id: str, attempt_id: str, timeout: int = 90) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        r = client.get(f"/api/v1/workspaces/{workspace_id}/practice-attempts/{attempt_id}", timeout=5)
        r.raise_for_status()
        last = r.json()
        if last["status"] in JOB_TERMINAL:
            return last
        time.sleep(0.5)
    raise AssertionError(f"timed_out:attempt={attempt_id}:last={last.get('status')}")


# ---------------------------------------------------------------------------
# Tutor API driver
# ---------------------------------------------------------------------------

def create_tutor_turn(client: httpx.Client, fx: dict, *, question: str,
                      code_auth: bool = False, science_auth: bool = False) -> dict:
    session_r = client.post(
        f"/api/v1/workspaces/{fx['workspace_id']}/courses/{fx['course_id']}/tutor-sessions",
        json={"course_version_id": fx["course_version_id"], "external_processing_ack": True}, timeout=10)
    assert session_r.status_code == 201, f"tutor session failed: {session_r.status_code} {session_r.text[:300]}"
    session_id = session_r.json()["id"]
    turn_r = client.post(
        f"/api/v1/workspaces/{fx['workspace_id']}/tutor-sessions/{session_id}/turns",
        headers={"Idempotency-Key": f"sys-{uuid4()}"},
        json={"question": question, "scope": "course",
              "code_tool_authorized": code_auth, "science_tool_authorized": science_auth}, timeout=10)
    assert turn_r.status_code == 202, f"tutor turn failed: {turn_r.status_code} {turn_r.text[:300]}"
    return turn_r.json()


def poll_turn(client: httpx.Client, workspace_id: str, turn_id: str, timeout: int = 90) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        r = client.get(f"/api/v1/workspaces/{workspace_id}/tutor-turns/{turn_id}", timeout=5)
        r.raise_for_status()
        last = r.json()
        if last["status"] in TURN_TERMINAL:
            return last
        time.sleep(0.5)
    raise AssertionError(f"timed_out:turn={turn_id}:last={last.get('status')}")


# ---------------------------------------------------------------------------
# Observability reads (new Postgres Session) — the authoritative evidence
# ---------------------------------------------------------------------------

def runs_for(filters: dict) -> list[dict]:
    from learn_platform_api.db.models import AgentRun
    with SessionLocal() as db:
        q = select(AgentRun)
        for col, val in filters.items():
            q = q.where(getattr(AgentRun, col) == val)
        rows = list(db.scalars(q.order_by(AgentRun.created_at)))
        return [{"id": r.id, "role": r.role, "status": r.status, "workspace_id": r.workspace_id,
                 "practice_job_id": r.practice_job_id, "tutor_turn_id": r.tutor_turn_id,
                 "step_count": r.step_count, "error_code": r.error_code} for r in rows]


def provider_calls(agent_run_id: str) -> list[dict]:
    from learn_platform_api.db.models import ProviderCall
    with SessionLocal() as db:
        rows = list(db.scalars(select(ProviderCall).where(
            ProviderCall.agent_run_id == agent_run_id).order_by(ProviderCall.ordinal)))
        return [{"ordinal": r.ordinal, "phase": r.phase, "status": r.status,
                 "error_code": r.error_code, "input_tokens": r.input_tokens,
                 "output_tokens": r.output_tokens} for r in rows]


def tool_calls(agent_run_id: str) -> list[dict]:
    from learn_platform_api.db.models import AgentToolCall
    with SessionLocal() as db:
        rows = list(db.scalars(select(AgentToolCall).where(
            AgentToolCall.agent_run_id == agent_run_id).order_by(AgentToolCall.ordinal)))
        return [{"tool_name": r.tool_name, "status": r.status, "error_code": r.error_code,
                 "result_count": r.result_count} for r in rows]


def count_tool_calls(agent_run_id: str, prefix: str) -> int:
    return sum(1 for t in tool_calls(agent_run_id) if t["tool_name"].startswith(prefix))
