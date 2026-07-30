"""Postgres support for the Slice 2B Batch A quality baseline.

Provides:
- a random throwaway Postgres database fixture (never the dev DB);
- a Postgres Gate that FAILS (never skips) when Postgres is unreachable or
  ``psycopg`` is missing (Spec 006 §7, Slice 2B packet §4/§10);
- desensitised seed helpers for practice lessons and tutor sessions;
- query helpers that ALWAYS read from a NEW Session (ADR 004 independent
  recorder sessions; Slice 2B packet §10).

No product code is imported for mutation; only the real ORM models and the real
``create_generation_job`` / ``create_session`` / ``create_turn`` service entries
are used to build authoritative seed facts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select

# The ``pg_db`` throwaway-Postgres fixture and the Postgres Gate live in
# ``conftest.py`` (fixtures must be discovered from conftest). This module holds
# only the desensitised seed helpers, settings builder and NEW-session query
# helpers used by the controlled baseline tests.

# --- Settings + tiny builders --------------------------------------------------


def _make_settings(**overrides: Any):
    """Build a Settings instance with controlled-provider defaults.

    All provider/MCP endpoints point at offline controlled stubs; the lowest-level
    seams are monkeypatched per test, so these URLs are never actually contacted.
    """
    from learn_platform_api.settings import Settings

    defaults = dict(
        product_generation_api_key="test-key",
        product_generation_base_url="https://controlled.example.invalid",
        product_generation_model="deepseek-v4-flash",
        product_generation_provider="deepseek",
        practice_generation_model="deepseek-v4-pro",
        practice_generation_provider="deepseek",
        wolfram_mcp_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _future_lease() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=5)


def _ws(pg_db):
    from learn_platform_api.db.models import Workspace

    ws = Workspace(name="ws", slug=f"ws-{uuid4().hex[:8]}")
    pg_db.add(ws)
    pg_db.flush()
    pg_db.commit()
    return ws


# --- Capability projection helper (the only readiness seam we patch) -----------


def make_projection(*, ok: bool = True, schema_hash: str = "c" * 16, status: str = "ready"):
    """A desensitised readiness projection dict for ``_read_capability_projection``.

    ``ok=False`` / empty hash models an unavailable capability so authorization
    creation and type suitability fail honestly.
    """
    return {
        "ok": ok,
        "status": status if ok else "unavailable",
        "detail": "controlled projection",
        "verified_schema_hash": schema_hash if ok else "",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ttl_seconds": 300,
    }


def patch_capability_projection(monkeypatch, *, code_ok=True, science_ok=True):
    """Patch ``readiness._read_capability_projection`` to a controlled map.

    Returns the underlying dict so a test can inspect what each capability saw.
    """
    import learn_platform_api.services.readiness as readiness

    seen: dict[str, dict] = {}

    def fake_projection(db, capability_id, *_a, **_k):
        ok = code_ok if capability_id == "code_execution" else science_ok
        proj = make_projection(ok=ok)
        seen[capability_id] = proj
        return proj

    monkeypatch.setattr(readiness, "_read_capability_projection", fake_projection)
    return seen


# --- Practice lesson seed ------------------------------------------------------


def seed_practice_lesson(pg_db, *, algorithmic=False, math=False, physics=False,
                         chemistry=False, executable=False, computable=False):
    """Seed the authoritative facts a Practice generation Job needs.

    Returns (workspace, course, course_version, section, lesson, lesson_version,
    document, document_version, chunk). The lesson version carries a desensitised
    ``practice_type_hints`` profile so real type suitability is structural, not
    keyword-based (Spec 004 §6.2, ADR 006 §2.6).
    """
    from learn_platform_api.db.models import (
        Course, CourseSection, CourseVersion, CourseVersionSource,
        DocumentChunk, DocumentVersion, Lesson, LessonVersion, SourceDocument,
        Workspace,
    )

    ws = Workspace(name="w", slug=f"w-{uuid4().hex[:8]}")
    pg_db.add(ws); pg_db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="lesson_source.md",
                         lifecycle_status="active")
    pg_db.add(doc); pg_db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready",
                          original_filename="lesson_source.md", mime_type="text/markdown",
                          byte_size=128, sha256="a" * 64, original_storage_uri="file:///controlled")
    pg_db.add(ver); pg_db.flush()
    doc.current_version_id = ver.id
    chunk = DocumentChunk(id=f"chunk-{uuid4().hex[:12]}", document_version_id=ver.id,
                          ordinal=0, content="Evidence text supporting the learning target.",
                          content_hash="b" * 64, start_offset=0, end_offset=48, page_start=1, page_end=1)
    pg_db.add(chunk)
    course = Course(workspace_id=ws.id, title="C", goal="g", audience="general",
                    lifecycle_status="active")
    pg_db.add(course); pg_db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1,
                       status="published", title="C", summary="s")
    pg_db.add(cv); pg_db.flush()
    course.current_active_version_id = cv.id
    pg_db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id,
                                  document_id=doc.id, document_version_id=ver.id))
    section = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0,
                            title="s", objective="o")
    pg_db.add(section); pg_db.flush()
    lesson = Lesson(course_version_id=cv.id, course_section_id=section.id,
                    workspace_id=ws.id, ordinal=0, title="L", objective="o")
    pg_db.add(lesson); pg_db.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id,
                       version_number=1, status="published", title="L",
                       learning_objectives=["objective_1"],
                       blocks=[{"block_key": "b1", "type": "text", "text": "body", "citation_ids": []}],
                       practice_type_hints=[{
                           "objective_key": "objective_1",
                           "evidence_keys": ["e1"],
                           "has_algorithmic_objective": algorithmic,
                           "has_executable_evidence": executable,
                           "has_math_objective": math,
                           "has_physics_objective": physics,
                           "has_chemistry_objective": chemistry,
                           "has_computable_evidence": computable,
                       }])
    pg_db.add(lv); pg_db.flush()
    lesson.current_published_version_id = lv.id
    pg_db.commit()
    return ws, course, cv, section, lesson, lv, doc, ver, chunk


def gen_payload(*, item_count, mode="auto", language=None,
                code_tool_authorized=False, science_tool_authorized=False):
    """Build the payload object ``practice.create_generation_job`` expects."""
    return type("P", (), {
        "item_count": item_count,
        "difficulty": "standard",
        "output_language": "zh-CN",
        "item_type_mode": mode,
        "code_languages": [language] if language else None,
        "code_tool_authorized": code_tool_authorized,
        "science_tool_authorized": science_tool_authorized,
    })()


def create_running_generation_job(pg_db, settings, ws, course, cv, lesson, lv, *, payload, worker="test-worker"):
    """Create a generation Job via the real service entry, then flip it to running.

    ``enqueue_practice_job`` must be patched to a no-op by the caller first.
    """
    from learn_platform_api.services import practice

    job = practice.create_generation_job(
        pg_db, settings, ws.id, course.id, cv.id, lesson.id, lv.id, payload,
        f"2b-{uuid4().hex[:10]}",
    )
    job.status = "running"
    job.worker_id = worker
    job.lease_expires_at = _future_lease()
    job.attempt_count = 1
    pg_db.commit()
    return job


# --- Tutor seed ----------------------------------------------------------------


def seed_tutor_course(pg_db):
    """Seed workspace/course/version/source/chunk for a Tutor session (course scope).

    Returns (workspace, course, course_version, document, document_version, chunk).
    """
    from learn_platform_api.db.models import (
        Course, CourseVersion, CourseVersionSource, DocumentChunk,
        DocumentVersion, SourceDocument, Workspace,
    )

    ws = Workspace(name="tw", slug=f"tw-{uuid4().hex[:8]}")
    pg_db.add(ws); pg_db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="tutor_source.md",
                         lifecycle_status="active")
    pg_db.add(doc); pg_db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready",
                          original_filename="tutor_source.md", mime_type="text/markdown",
                          byte_size=64, sha256="a" * 64, original_storage_uri="file:///controlled")
    pg_db.add(ver); pg_db.flush()
    doc.current_version_id = ver.id
    chunk = DocumentChunk(id=f"tchunk-{uuid4().hex[:12]}", document_version_id=ver.id,
                          ordinal=0, content="Reference material the Tutor may cite.",
                          content_hash="b" * 64, start_offset=0, end_offset=44, page_start=1, page_end=1)
    pg_db.add(chunk)
    course = Course(workspace_id=ws.id, title="TC", goal="g", audience="general",
                    lifecycle_status="active")
    pg_db.add(course); pg_db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1,
                       status="published", title="TC", summary="s")
    pg_db.add(cv); pg_db.flush()
    course.current_active_version_id = cv.id
    pg_db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id,
                                  document_id=doc.id, document_version_id=ver.id))
    pg_db.commit()
    return ws, course, cv, doc, ver, chunk


def tutor_turn_payload(*, question, code_tool_authorized=False, science_tool_authorized=False):
    return type("P", (), {
        "question": question,
        "scope": "course",
        "section_id": None,
        "lesson_id": None,
        "lesson_version_id": None,
        "code_tool_authorized": code_tool_authorized,
        "science_tool_authorized": science_tool_authorized,
        "code_run_id": None,
    })()


# --- Orchestration preparation (shared by the coding/budget/wolfram tests) -----


def patch_evidence(monkeypatch, chunk, doc, ver):
    """Patch ``practice_generation.retrieve`` to return the seeded chunk as e1."""
    from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
    from learn_platform_api.services import practice_generation

    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: (
        "trace", [RetrievalResult(
            score=0.9, text=chunk.content,
            citation=CitationRead(document_id=doc.id, document_version_id=ver.id,
                                  chunk_id=chunk.id, document_name=doc.display_name,
                                  heading_path=[], start_offset=0, end_offset=len(chunk.content))),
        ]))


def prepare_generation(pg_db, monkeypatch, *, sample, code_auth=False, science_auth=False,
                       science_enabled=False):
    """Seed a lesson from a sample's profile and create a running generation Job.

    Patches capability projection + enqueue. Returns
    ``(settings, job, chunk, doc, ver)``. The caller still scripts the provider,
    execution backend and/or science verifier and calls ``execute_generation``.
    """
    from learn_platform_api.services import practice

    p = sample.profile
    ws, course, cv, section, lesson, lv, doc, ver, chunk = seed_practice_lesson(
        pg_db, algorithmic=p.get("algorithmic", False), executable=p.get("executable", False),
        math=p.get("math", False), physics=p.get("physics", False),
        chemistry=p.get("chemistry", False), computable=p.get("computable", False),
    )
    settings = _make_settings(
        mcp_execution_adapter_url="http://controlled.invalid/mcp" if code_auth else None,
        wolfram_mcp_enabled=science_enabled or science_auth,
    )
    patch_capability_projection(monkeypatch, code_ok=code_auth, science_ok=science_auth or science_enabled)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    payload = gen_payload(item_count=sample.item_count, mode=sample.request_mode,
                          language=sample.language, code_tool_authorized=code_auth,
                          science_tool_authorized=science_auth)
    job = create_running_generation_job(pg_db, settings, ws, course, cv, lesson, lv, payload=payload)
    return settings, job, chunk, doc, ver


def prepare_budget_job(pg_db, monkeypatch, *, mode, item_count, language="python",
                       code_auth=False, science_auth=False, science_enabled=False,
                       algorithmic=False, executable=False, math=False, physics=False,
                       chemistry=False, computable=False):
    """Seed a lesson with a chosen profile and create a running generation Job
    for the budget-curve matrix (independent mode/count/language selection)."""
    from learn_platform_api.services import practice

    ws, course, cv, section, lesson, lv, doc, ver, chunk = seed_practice_lesson(
        pg_db, algorithmic=algorithmic, executable=executable, math=math,
        physics=physics, chemistry=chemistry, computable=computable)
    settings = _make_settings(
        mcp_execution_adapter_url="http://controlled.invalid/mcp" if code_auth else None,
        wolfram_mcp_enabled=science_enabled or science_auth,
    )
    patch_capability_projection(monkeypatch, code_ok=code_auth, science_ok=science_auth or science_enabled)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    payload = gen_payload(item_count=item_count, mode=mode, language=language if mode == "require_coding" else None,
                          code_tool_authorized=code_auth, science_tool_authorized=science_auth)
    job = create_running_generation_job(pg_db, settings, ws, course, cv, lesson, lv, payload=payload)
    return settings, job, chunk, doc, ver


# --- Query helpers (always from a NEW session) ---------------------------------


def _sf(pg_db):
    return pg_db._test_session_factory


def q_provider_calls(pg_db, **filters) -> list[dict]:
    from learn_platform_api.db.models import ProviderCall

    with _sf(pg_db)() as v:
        q = select(ProviderCall)
        for col, val in filters.items():
            q = q.where(getattr(ProviderCall, col) == val)
        rows = list(v.scalars(q.order_by(ProviderCall.ordinal)))
        return [{
            "id": r.id, "workspace_id": r.workspace_id, "agent_run_id": r.agent_run_id,
            "rag_answer_trace_id": r.rag_answer_trace_id, "ordinal": r.ordinal,
            "phase": r.phase, "provider": r.provider, "model": r.model,
            "status": r.status, "error_code": r.error_code,
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
            "latency_ms": r.latency_ms,
        } for r in rows]


def q_tool_calls(pg_db, **filters) -> list[dict]:
    from learn_platform_api.db.models import AgentToolCall

    with _sf(pg_db)() as v:
        q = select(AgentToolCall)
        for col, val in filters.items():
            q = q.where(getattr(AgentToolCall, col) == val)
        rows = list(v.scalars(q.order_by(AgentToolCall.ordinal)))
        return [{
            "id": r.id, "agent_run_id": r.agent_run_id, "tool_name": r.tool_name,
            "ordinal": r.ordinal, "status": r.status, "error_code": r.error_code,
            "result_count": r.result_count,
        } for r in rows]


def q_run(pg_db, **filters) -> dict | None:
    from learn_platform_api.db.models import AgentRun

    with _sf(pg_db)() as v:
        q = select(AgentRun)
        for col, val in filters.items():
            q = q.where(getattr(AgentRun, col) == val)
        r = v.scalar(q)
        if r is None:
            return None
        return {
            "id": r.id, "workspace_id": r.workspace_id, "role": r.role,
            "status": r.status, "step_count": r.step_count,
            "practice_job_id": r.practice_job_id, "tutor_turn_id": r.tutor_turn_id,
            "error_code": r.error_code,
        }


def q_practice_job(pg_db, job_id) -> dict | None:
    from learn_platform_api.db.models import PracticeJob

    with _sf(pg_db)() as v:
        r = v.get(PracticeJob, job_id)
        if r is None:
            return None
        return {
            "id": r.id, "status": r.status, "error_code": r.error_code,
            "practice_set_id": r.practice_set_id, "practice_attempt_id": r.practice_attempt_id,
            "item_count": r.item_count, "item_type_mode": r.item_type_mode,
        }


def q_set(pg_db, job_id) -> dict | None:
    from learn_platform_api.db.models import PracticeItem, PracticeSet

    with _sf(pg_db)() as v:
        ps = v.scalar(select(PracticeSet).where(PracticeSet.practice_job_id == job_id))
        if ps is None:
            return None
        items = list(v.scalars(select(PracticeItem).where(PracticeItem.practice_set_id == ps.id).order_by(PracticeItem.ordinal)))
        type_counts: dict[str, int] = {}
        langs: set[str] = set()
        for it in items:
            type_counts[it.item_type] = type_counts.get(it.item_type, 0) + 1
            if it.item_type == "coding" and it.interaction_spec:
                langs.add(it.interaction_spec.get("language"))
        return {
            "id": ps.id, "item_count": ps.item_count, "lifecycle_status": ps.lifecycle_status,
            "generation_config": ps.generation_config,
            "item_count_actual": len(items),
            "item_type_counts": type_counts,
            "specialized_count": sum(1 for it in items if it.item_type in ("coding", "scientific")),
            "coding_languages": sorted(x for x in langs if x),
        }


def q_attempt(pg_db, attempt_id) -> dict | None:
    from learn_platform_api.db.models import PracticeAttempt

    with _sf(pg_db)() as v:
        r = v.get(PracticeAttempt, attempt_id)
        if r is None:
            return None
        return {"id": r.id, "status": r.status, "error_code": r.error_code,
                "practice_job_id": r.practice_job_id}


def q_feedback(pg_db, attempt_id) -> dict | None:
    from learn_platform_api.db.models import PracticeFeedback

    with _sf(pg_db)() as v:
        r = v.scalar(select(PracticeFeedback).where(PracticeFeedback.practice_attempt_id == attempt_id))
        if r is None:
            return None
        return {"verdict": r.verdict, "score": r.score, "is_ai_graded": bool(r.is_ai_graded)}


def q_tutor_turn(pg_db, turn_id) -> dict | None:
    from learn_platform_api.db.models import TutorTurn

    with _sf(pg_db)() as v:
        r = v.get(TutorTurn, turn_id)
        if r is None:
            return None
        return {
            "id": r.id, "status": r.status, "error_code": r.error_code,
            "answer_blocks": r.answer_blocks,
            "code_tool_used": r.code_tool_used, "code_tool_call_count": r.code_tool_call_count,
            "science_tool_used": r.science_tool_used, "science_tool_call_count": r.science_tool_call_count,
        }


def q_tutor_authorizations(pg_db, turn_id) -> list[dict]:
    from learn_platform_api.db.models import TutorTurnToolAuthorization

    with _sf(pg_db)() as v:
        rows = list(v.scalars(select(TutorTurnToolAuthorization).where(TutorTurnToolAuthorization.turn_id == turn_id)))
        return [{"capability_id": r.capability_id, "max_calls": r.max_calls,
                 "used_calls": r.used_calls} for r in rows]
