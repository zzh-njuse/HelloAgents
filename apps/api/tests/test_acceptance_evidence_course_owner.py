"""Stage 5 Part 2 Slice 2A — Course lesson owner commit acceptance evidence.

Replaces the old test_course_lesson_owner_commit_is_minimal which manually
replayed the product's create-AgentRun/commit/create-authorization/rollback
sequence in the test, rather than calling the real service.

New test calls the real _execute_lesson_generation(), monkeypatching only
the low-level external boundaries (capability projection, provider HTTP,
retrieval, evidence search). The service itself creates and commits the
AgentRun owner, then creates JobToolAuthorization.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from learn_platform_api.db.models import (
    AgentRun,
    Course,
    CourseGenerationJob,
    CourseSection,
    CourseVersion,
    JobToolAuthorization,
    Lesson,
    Workspace,
)


# --- ADR 004 helper -----------------------------------------------------------

def _sf(db_session):
    """Return the test session factory for independent recorder sessions."""
    return getattr(db_session, '_test_session_factory', None)


# --- seed helpers -------------------------------------------------------------

def _ws(db_session) -> Workspace:
    ws = Workspace(name="ws", slug=f"ws-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.flush()
    db_session.commit()
    return ws


def _make_settings(**overrides):
    """Build a Settings object with test defaults."""
    from learn_platform_api.settings import Settings
    defaults = dict(
        product_generation_api_key="test-key",
        product_generation_base_url="https://fake.example.com",
        product_generation_model="deepseek-v4-flash",
        product_generation_provider="deepseek",
        wolfram_mcp_enabled=True,
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


# ============================================================================ #
# Course lesson owner via real _execute_lesson_generation()                    #
# ============================================================================ #

def test_course_lesson_owner_commit_via_real_service(db_session) -> None:
    """Fix 3 / ADR 004 S5.1: _execute_lesson_generation() commits the AgentRun
    owner before creating JobToolAuthorization. When the business session
    rolls back after a provider failure, the AgentRun persists but the
    JobToolAuthorization does NOT.

    This test calls the real _execute_lesson_generation(), monkeypatching
    only the low-level external boundaries:
    - _read_capability_projection (capability projection)
    - httpx.post (provider HTTP)
    - retrieve / _lesson_evidence_search (retrieval)

    The provider is made to fail on the first attempt, causing a business
    rollback. The AgentRun owner must survive; the JobToolAuthorization
    must not.
    """
    from learn_platform_api.services.course_generation import _execute_lesson_generation
    from academic_companion.course_agents import CourseAgentRequest

    ws = _ws(db_session)
    settings = _make_settings()

    # Create the course infrastructure needed for a CourseGenerationJob.
    course = Course(workspace_id=ws.id, title="Test", goal="Test",
                    audience="general", lifecycle_status="active")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, workspace_id=ws.id,
                           version_number=1, status="draft",
                           title="Test", summary="Test")
    db_session.add(version)
    db_session.flush()
    section = CourseSection(course_version_id=version.id, workspace_id=ws.id,
                           ordinal=0, title="Test Section",
                           objective="Test objective")
    db_session.add(section)
    db_session.flush()
    lesson = Lesson(course_version_id=version.id, course_section_id=section.id,
                   workspace_id=ws.id, ordinal=0, title="Test Lesson",
                   objective="Test objective")
    db_session.add(lesson)
    db_session.flush()
    db_session.commit()

    # Create a CourseGenerationJob with science_tool_authorized=True.
    job = CourseGenerationJob(
        course_id=course.id, workspace_id=ws.id, job_type="lesson_draft",
        lesson_id=lesson.id, course_version_id=version.id,
        output_language="zh-CN", attempt_count=0,
        idempotency_key=f"acceptance-{uuid4().hex[:8]}",
        science_tool_authorized=True,
        status="running",
    )
    db_session.add(job)
    db_session.flush()
    db_session.commit()

    request = CourseAgentRequest(
        title="Test", goal="Test", audience="general",
        output_language="zh-CN", source_names=(),
    )

    # Monkeypatch: capability projection says science is OK.
    # Provider HTTP always fails → business exception → rollback.
    with patch("learn_platform_api.services.course_generation._recorded_call_provider") as mock_call, \
         patch("learn_platform_api.services.readiness._read_capability_projection") as mock_cap:
        mock_cap.return_value = {"ok": True, "verified_schema_hash": "abc123"}

        # First call (plan) raises a controlled provider failure.
        mock_call.side_effect = ValueError("provider_unavailable")

        with pytest.raises(ValueError, match="provider_unavailable"):
            _execute_lesson_generation(db_session, settings, job, request)

    # After the exception, the business session may be in a bad state.
    # Rollback to clear it.
    db_session.rollback()

    # Verify from a new session:
    sf = _sf(db_session)
    with sf() as verify_db:
        # AgentRun owner was committed BEFORE the provider call,
        # so it must persist even after the rollback.
        run_count = verify_db.scalar(
            select(func.count()).where(
                AgentRun.course_generation_job_id == job.id
            )
        )
        assert run_count == 1, (
            "AgentRun owner must persist after business rollback "
            "(committed in minimal owner transaction before provider call)"
        )

        # JobToolAuthorization was created AFTER the owner commit but
        # only flushed (not committed separately), so it must NOT persist
        # after the rollback.
        auth_count = verify_db.scalar(
            select(func.count()).where(
                JobToolAuthorization.course_generation_job_id == job.id
            )
        )
        assert auth_count == 0, (
            "JobToolAuthorization must NOT persist after business rollback "
            "(created after owner commit, not swept into owner transaction)"
        )


def test_course_lesson_owner_commit_antiexample_via_real_service(db_session) -> None:
    """Anti-example: If JobToolAuthorization were created BEFORE the AgentRun
    commit (the old broken order), it WOULD be swept into the owner commit
    and survive the rollback. This test verifies the CURRENT correct order
    by confirming the authorization does NOT survive.

    This is the same test as above but explicitly documents the anti-example:
    if someone reverts the Fix 3 reordering, this test would fail because
    auth_count would be 1 instead of 0.
    """
    from learn_platform_api.services.course_generation import _execute_lesson_generation
    from academic_companion.course_agents import CourseAgentRequest

    ws = _ws(db_session)
    settings = _make_settings()

    course = Course(workspace_id=ws.id, title="Test", goal="Test",
                    audience="general", lifecycle_status="active")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, workspace_id=ws.id,
                           version_number=1, status="draft",
                           title="Test", summary="Test")
    db_session.add(version)
    db_session.flush()
    section = CourseSection(course_version_id=version.id, workspace_id=ws.id,
                           ordinal=0, title="Test Section",
                           objective="Test objective")
    db_session.add(section)
    db_session.flush()
    lesson = Lesson(course_version_id=version.id, course_section_id=section.id,
                   workspace_id=ws.id, ordinal=0, title="Test Lesson",
                   objective="Test objective")
    db_session.add(lesson)
    db_session.flush()
    db_session.commit()

    job = CourseGenerationJob(
        course_id=course.id, workspace_id=ws.id, job_type="lesson_draft",
        lesson_id=lesson.id, course_version_id=version.id,
        output_language="zh-CN", attempt_count=0,
        idempotency_key=f"anti-{uuid4().hex[:8]}",
        science_tool_authorized=True,
        status="running",
    )
    db_session.add(job)
    db_session.flush()
    db_session.commit()

    request = CourseAgentRequest(
        title="Test", goal="Test", audience="general",
        output_language="zh-CN", source_names=(),
    )

    with patch("learn_platform_api.services.course_generation._recorded_call_provider") as mock_call, \
         patch("learn_platform_api.services.readiness._read_capability_projection") as mock_cap:
        mock_cap.return_value = {"ok": True, "verified_schema_hash": "abc123"}
        mock_call.side_effect = ValueError("provider_unavailable")

        with pytest.raises(ValueError, match="provider_unavailable"):
            _execute_lesson_generation(db_session, settings, job, request)

    db_session.rollback()

    sf = _sf(db_session)
    with sf() as verify_db:
        auth_count = verify_db.scalar(
            select(func.count()).where(
                JobToolAuthorization.course_generation_job_id == job.id
            )
        )
        # If this assertion fails, it means the authorization was swept into
        # the owner commit — i.e., Fix 3 was reverted.
        assert auth_count == 0, (
            "Anti-example: if Fix 3 is reverted and authorization is created "
            "before owner commit, auth_count would be 1. Fix 3 ensures it is 0."
        )
