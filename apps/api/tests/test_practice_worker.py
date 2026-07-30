"""Worker lifecycle and queue-isolation tests (correction packet §7 + §8).

These drive the real ``run_practice_job`` through its claim/lease/failure/cancel
path on the SQLite test session, plus a source-level check that the Compose
worker boundary keeps the practice queue on its own worker.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from fastapi.testclient import TestClient  # noqa: F401 - kept for parity with sibling tests
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from learn_platform_api.db.models import (
    AgentRun, Course, CourseSection, CourseVersion, CourseVersionSource, DocumentChunk, DocumentVersion,
    Lesson, LessonVersion, PracticeAttempt, PracticeFeedback, PracticeItem, PracticeItemCitation,
    PracticeJob, PracticeSet, SourceDocument, Workspace,
)
from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
from learn_platform_api.services import practice, practice_generation
from learn_platform_api.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[3]


class _SharedSession:
    """Yield the test session to a worker that opens its own ``SessionLocal``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *_exc):
        return False


def _reader(db: Session):
    ws = Workspace(name="w", slug="w"); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g", mime_type="text/markdown", byte_size=1, sha256="a" * 64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id=("c" * 32)[:36], document_version_id=ver.id, ordinal=0, content="Binary search halves a sorted interval.", content_hash="b" * 64, start_offset=0, end_offset=36, page_start=1, page_end=1)
    course = Course(workspace_id=ws.id, title="C", goal="g"); db.add_all([chunk, course]); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="C"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id))
    section = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="s", objective="o"); db.add(section); db.flush()
    lesson = Lesson(course_version_id=cv.id, course_section_id=section.id, workspace_id=ws.id, ordinal=0, title="L", objective="o"); db.add(lesson); db.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1, status="published", title="L", learning_objectives=["o"], blocks=[]); db.add(lv); db.flush(); lesson.current_published_version_id = lv.id; db.commit()
    return ws, course, cv, lesson, lv, chunk, doc, ver


def _gen_payload(item_count, language):
    class _P:
        pass
    _P.item_count = item_count; _P.difficulty = "standard"; _P.output_language = language
    return _P()


def _artifact():
    return {"items": [
        {"target_key": "objective_1", "item_key": "q1", "item_type": "single_choice", "stem": "pick", "citation_ids": ["e1"], "options": [{"option_key": "a", "text": "A", "is_correct": True, "rationale": "r", "citation_ids": ["e1"]}, {"option_key": "b", "text": "B", "is_correct": False, "rationale": "r", "citation_ids": ["e1"]}]},
        {"target_key": "objective_1", "item_key": "q2", "item_type": "short_answer", "stem": "explain", "citation_ids": ["e1"], "rubric": [{"criterion_key": "c1", "description": "d", "weight": 100, "citation_ids": ["e1"]}], "reference_answer": "ref"},
    ]}


def test_worker_claims_and_completes_generation(db_session: Session, monkeypatch) -> None:
    from learn_platform_api import practice_workers
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: ("t", [RetrievalResult(score=0.9, text=chunk.content, citation=CitationRead(document_id=doc.id, document_version_id=ver.id, chunk_id=chunk.id, document_name=doc.display_name, heading_path=[], start_offset=0, end_offset=len(chunk.content)))]))
    provider = iter([({"queries": ["q"]}, {"input_tokens": 2, "output_tokens": 2}), (_artifact(), {"input_tokens": 10, "output_tokens": 20})])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider))
    monkeypatch.setattr(practice_workers, "SessionLocal", lambda: _SharedSession(db_session))

    job = practice.create_generation_job(db_session, get_settings(), ws.id, course.id, cv.id, lesson.id, lv.id, _gen_payload(2, "zh-CN"), "g1")
    practice_workers.run_practice_job(job.id)
    db_session.commit()
    refreshed = db_session.get(PracticeJob, job.id)
    assert refreshed.status == "succeeded"
    sets = list(db_session.query(PracticeSet).filter_by(workspace_id=ws.id))
    assert len(sets) == 1


def test_worker_cancel_requested_marks_canceled_and_commits_nothing(db_session: Session, monkeypatch) -> None:
    from learn_platform_api import practice_workers
    from learn_platform_api.services import jobs as jobs_service
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: ("t", []))
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: ({"queries": ["q"]}, {"input_tokens": 1, "output_tokens": 1}))
    monkeypatch.setattr(practice_workers, "SessionLocal", lambda: _SharedSession(db_session))

    job = practice.create_generation_job(db_session, get_settings(), ws.id, course.id, cv.id, lesson.id, lv.id, _gen_payload(1, "zh-CN"), "g2")
    db_session.get(PracticeJob, job.id).status = "cancel_requested"; db_session.commit()
    # The worker cannot claim a cancel_requested job, so it must leave no set behind.
    practice_workers.run_practice_job(job.id)
    db_session.commit()
    assert list(db_session.query(PracticeSet).filter_by(workspace_id=ws.id)) == []
    # The reconciler owns the cancel_requested -> canceled finalization.
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    jobs_service.reconcile_jobs(db_session, get_settings())
    db_session.commit()
    assert db_session.get(PracticeJob, job.id).status == "canceled"


def test_worker_duplicate_delivery_is_a_noop(db_session: Session, monkeypatch) -> None:
    from learn_platform_api import practice_workers
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    job = practice.create_generation_job(db_session, get_settings(), ws.id, course.id, cv.id, lesson.id, lv.id, _gen_payload(1, "zh-CN"), "g3")
    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: ("t", [RetrievalResult(score=0.9, text=chunk.content, citation=CitationRead(document_id=doc.id, document_version_id=ver.id, chunk_id=chunk.id, document_name=doc.display_name, heading_path=[], start_offset=0, end_offset=5))]))
    # Single persistent iterator (the old lambda recreated iter() each call,
    # always returning plan and never reaching the artifact).
    call_log = []
    _provider = iter([({"queries": ["q"]}, {"input_tokens": 1, "output_tokens": 1}), (_artifact(), {"input_tokens": 1, "output_tokens": 1})])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: (call_log.append(1), next(_provider))[1])
    monkeypatch.setattr(practice_workers, "SessionLocal", lambda: _SharedSession(db_session))
    practice_workers.run_practice_job(job.id); db_session.commit()
    assert db_session.get(PracticeJob, job.id).status == "succeeded"
    assert db_session.query(PracticeSet).filter_by(workspace_id=ws.id).count() == 1
    runs_before = db_session.query(AgentRun).filter_by(practice_job_id=job.id).count()
    calls_before = len(call_log)
    # Second delivery: job is now 'succeeded' -> worker returns immediately.
    practice_workers.run_practice_job(job.id); db_session.commit()
    assert db_session.query(PracticeSet).filter_by(workspace_id=ws.id).count() == 1
    assert len(call_log) == calls_before  # provider NOT called on duplicate delivery
    assert db_session.query(AgentRun).filter_by(practice_job_id=job.id).count() == runs_before


def test_worker_failure_keeps_real_step_count(db_session: Session, monkeypatch) -> None:
    from learn_platform_api import practice_workers
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: ("t", [RetrievalResult(score=0.9, text=chunk.content, citation=CitationRead(document_id=doc.id, document_version_id=ver.id, chunk_id=chunk.id, document_name=doc.display_name, heading_path=[], start_offset=0, end_offset=5))]))
    # Plan + submit succeed (2 tool calls recorded), then artifact validation fails on unknown citation,
    # and repair is denied because provider call budget is still available but repair also invalid.
    bad = {"items": [{"target_key": "objective_1", "item_key": "q1", "item_type": "single_choice", "stem": "s", "citation_ids": ["eX"], "options": [{"option_key": "a", "text": "A", "is_correct": True, "rationale": "r", "citation_ids": ["eX"]}, {"option_key": "b", "text": "B", "is_correct": False, "rationale": "r", "citation_ids": ["eX"]}]}]}
    provider = iter([({"queries": ["q"]}, {"input_tokens": 1, "output_tokens": 1}), (bad, {"input_tokens": 1, "output_tokens": 1}), (bad, {"input_tokens": 1, "output_tokens": 1})])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider))
    monkeypatch.setattr(practice_workers, "SessionLocal", lambda: _SharedSession(db_session))

    job = practice.create_generation_job(db_session, get_settings(), ws.id, course.id, cv.id, lesson.id, lv.id, _gen_payload(1, "zh-CN"), "g4")
    practice_workers.run_practice_job(job.id); db_session.commit()
    failed_runs = list(db_session.query(AgentRun).filter_by(practice_job_id=job.id, status="failed"))
    all_runs = list(db_session.query(AgentRun).filter_by(practice_job_id=job.id))
    assert len(all_runs) == 1, "one delivery attempt must have exactly one AgentRun"
    assert failed_runs and failed_runs[0].step_count == 4, f"failed AgentRun must keep real step count (plan+search+submit+repair=4), got {failed_runs[0].step_count}"
    from learn_platform_api.db.models import AgentToolCall
    assert db_session.query(AgentToolCall).filter_by(agent_run_id=failed_runs[0].id).count() == 3
    assert db_session.query(PracticeSet).filter_by(workspace_id=ws.id).count() == 0


def test_worker_retryable_grading_failure_sets_attempt_retry_wait(db_session: Session, monkeypatch) -> None:
    from learn_platform_api import practice_workers
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    practice_set = PracticeSet(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, output_language="zh-CN", difficulty="standard", item_count=1, generation_config={}, lifecycle_status="active")
    db_session.add(practice_set); db_session.flush()
    from learn_platform_api.db.models import PracticeItem, PracticeItemCitation
    item = PracticeItem(practice_set_id=practice_set.id, workspace_id=ws.id, ordinal=0, item_type="short_answer", stem="s", options=None, answer_spec={"reference_answer": "r", "rubric": [{"criterion_key": "c1", "description": "d", "weight": 100, "citation_ids": ["e1"]}], "citation_ids": ["e1"]})
    db_session.add(item); db_session.flush()
    db_session.add(PracticeItemCitation(practice_item_id=item.id, workspace_id=ws.id, citation_key="e1", document_id=doc.id, document_version_id=ver.id, document_chunk_id=chunk.id)); db_session.commit()

    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_workers, "SessionLocal", lambda: _SharedSession(db_session))
    attempt = practice.submit_attempt(db_session, get_settings(), ws.id, item.id, _short_payload("ans"), "s1")
    job = db_session.get(PracticeJob, attempt.practice_job_id)
    # Transient provider failure is retryable; attempt must follow the job into retry_wait.
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: (_raise_provider(), {})[1])
    monkeypatch.setattr(practice_generation, "call_provider", _raise_provider)
    practice_workers.run_practice_job(job.id); db_session.commit()
    assert db_session.get(PracticeJob, job.id).status == "retry_wait"
    assert db_session.get(PracticeAttempt, attempt.id).status == "retry_wait"


def _short_payload(text):
    class _P:
        pass
    _P.external_processing_ack = True; _P.option_key = None; _P.text = text
    return _P()


def _raise_provider(*_a, **_k):
    raise ValueError("provider_unavailable")


def test_compose_worker_queue_isolation() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    worker_queues = compose["services"]["worker"]["command"]
    practice_worker_queues = compose["services"]["practice-worker"]["command"]
    assert "learn-platform-practice" not in worker_queues, "general worker must not drain the practice queue"
    assert practice_worker_queues == ["rq", "worker", "--with-scheduler", "--url", "redis://redis:6379/0", "learn-platform-practice"]
    assert "learn-platform-tutor" in worker_queues
    assert "learn-platform-tutor" not in practice_worker_queues


def test_queue_functions_target_isolated_queues() -> None:
    from learn_platform_api.services import queue
    settings = get_settings()
    assert settings.practice_queue_name == "learn-platform-practice"
    assert settings.tutor_queue_name == "learn-platform-tutor"
    assert settings.practice_queue_name != settings.tutor_queue_name
    assert queue.enqueue_practice_job.__name__ == "enqueue_practice_job"
    assert queue.enqueue_tutor_turn.__name__ == "enqueue_tutor_turn"


def test_practice_queue_timeout_exceeds_product_wall_budget(monkeypatch) -> None:
    from learn_platform_api.services import queue

    captured = {}

    class _Connection:
        def close(self):
            captured["closed"] = True

    class _Queue:
        def __init__(self, name, connection):
            captured["queue"] = name

        def enqueue(self, function, job_id, **kwargs):
            captured.update(function=function, job_id=job_id, **kwargs)

    monkeypatch.setattr(queue.Redis, "from_url", lambda *_a, **_k: _Connection())
    monkeypatch.setattr(queue, "Queue", _Queue)
    settings = get_settings().model_copy(update={
        "practice_generation_max_wall_seconds": 600,
        "practice_grading_max_wall_seconds": 180,
    })

    queue.enqueue_practice_job(settings, "job-1")

    assert captured["job_timeout"] == 660
    assert captured["function"] == "learn_platform_api.practice_workers.run_practice_job"
    assert captured["closed"] is True
