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

from learn_platform_api.db.models import (
    AgentRun,
    Course,
    CourseSection,
    CourseVersion,
    CourseVersionSource,
    DocumentChunk,
    DocumentVersion,
    Lesson,
    LessonCitation,
    LessonVersion,
    ProviderCall,
    SourceDocument,
    Workspace,
)
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.settings import get_settings
from learn_platform_api.workers import ensure_collection


API_URL = os.environ.get("SYSTEM_TEST_API_URL", "http://api:8000").rstrip("/")
STUB_URL = os.environ.get(
    "SYSTEM_TEST_STUB_URL", "http://model-services-stub:8090"
).rstrip("/")
TERMINAL = {"succeeded", "failed", "canceled", "retry_wait"}


@pytest.fixture(scope="module", autouse=True)
def environment_ready() -> None:
    _wait_for_environment()


def _wait_for_environment() -> None:
    deadline = time.monotonic() + 60
    last_error = "not started"
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{API_URL}/ready", timeout=2).status_code != 200:
                raise RuntimeError("api_not_ready")
            if httpx.get(f"{STUB_URL}/readyz", timeout=2).status_code != 200:
                raise RuntimeError("stub_not_ready")
            settings = get_settings()
            redis = Redis.from_url(settings.redis_url)
            try:
                workers = Worker.all(connection=redis)
                if not any(
                    settings.tutor_queue_name in worker.queue_names()
                    for worker in workers
                ):
                    raise RuntimeError("tutor_worker_not_subscribed")
            finally:
                redis.close()
            return
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{exc}"
            time.sleep(1)
    raise AssertionError(f"environment_failed:{last_error}")


def _seed_reader_fixture() -> dict[str, str]:
    suffix = uuid4().hex[:10]
    chunk_id = str(uuid4())
    with SessionLocal() as db:
        workspace = Workspace(
            name=f"System Tutor {suffix}",
            slug=f"system-tutor-{suffix}",
        )
        db.add(workspace)
        db.flush()
        document = SourceDocument(
            workspace_id=workspace.id,
            display_name="binary-search.md",
        )
        db.add(document)
        db.flush()
        document_version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            processing_status="ready",
            original_filename="binary-search.md",
            mime_type="text/markdown",
            byte_size=52,
            sha256="a" * 64,
            original_storage_uri=f"system-test/{suffix}",
            embedding_model="stub-embedding",
            embedding_dimension=4,
        )
        db.add(document_version)
        db.flush()
        document.current_version_id = document_version.id
        chunk = DocumentChunk(
            id=chunk_id,
            document_version_id=document_version.id,
            ordinal=0,
            content="Binary search halves the remaining sorted search interval.",
            content_hash="b" * 64,
            heading_path="Search / Binary search",
            start_offset=0,
            end_offset=58,
            token_count=10,
        )
        course = Course(
            workspace_id=workspace.id,
            title="Algorithms",
            goal="Understand binary search",
        )
        db.add_all([chunk, course])
        db.flush()
        version = CourseVersion(
            course_id=course.id,
            workspace_id=workspace.id,
            version_number=1,
            status="active",
            title=course.title,
        )
        db.add(version)
        db.flush()
        course.current_active_version_id = version.id
        db.add(
            CourseVersionSource(
                course_version_id=version.id,
                workspace_id=workspace.id,
                document_id=document.id,
                document_version_id=document_version.id,
            )
        )
        section = CourseSection(
            course_version_id=version.id,
            workspace_id=workspace.id,
            ordinal=0,
            title="Search",
            objective="Understand interval reduction",
        )
        db.add(section)
        db.flush()
        lesson = Lesson(
            course_version_id=version.id,
            course_section_id=section.id,
            workspace_id=workspace.id,
            ordinal=0,
            title="Binary search",
            objective="Explain why the interval halves",
        )
        db.add(lesson)
        db.flush()
        lesson_version = LessonVersion(
            lesson_id=lesson.id,
            course_version_id=version.id,
            workspace_id=workspace.id,
            version_number=1,
            status="published",
            title=lesson.title,
            learning_objectives=["Explain interval halving"],
            blocks=[
                {
                    "block_key": "source",
                    "type": "paragraph",
                    "text": chunk.content,
                    "citation_ids": ["source-1"],
                }
            ],
        )
        db.add(lesson_version)
        db.flush()
        lesson.current_published_version_id = lesson_version.id
        db.add(
            LessonCitation(
                lesson_version_id=lesson_version.id,
                workspace_id=workspace.id,
                block_key="source",
                document_id=document.id,
                document_version_id=document_version.id,
                document_chunk_id=chunk.id,
            )
        )
        db.commit()
        result = {
            "workspace_id": workspace.id,
            "course_id": course.id,
            "course_version_id": version.id,
            "section_id": section.id,
            "lesson_id": lesson.id,
            "lesson_version_id": lesson_version.id,
            "document_id": document.id,
            "chunk_id": chunk.id,
        }

    settings = get_settings()
    qdrant = QdrantClient(url=settings.qdrant_url)
    try:
        ensure_collection(qdrant, settings)
        qdrant.upsert(
            collection_name=settings.product_collection_name,
            points=[
                PointStruct(
                    id=chunk_id,
                    vector=[1.0, 0.0, 0.0, 0.0],
                    payload={
                        "workspace_id": result["workspace_id"],
                        "document_id": result["document_id"],
                        "chunk_id": chunk_id,
                    },
                )
            ],
            wait=True,
        )
    finally:
        qdrant.close()
    return result


def _reset_stub(client: httpx.Client, scenario: str) -> None:
    response = client.post(f"{STUB_URL}/__reset", json={"scenario": scenario})
    response.raise_for_status()


def _poll_turn(client: httpx.Client, workspace_id: str, turn_id: str) -> dict:
    deadline = time.monotonic() + 45
    latest: dict = {}
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/workspaces/{workspace_id}/tutor-turns/{turn_id}"
        )
        response.raise_for_status()
        latest = response.json()
        if latest["status"] in TERMINAL:
            return latest
        time.sleep(0.5)
    raise AssertionError(f"timed_out:turn_id={turn_id}:last_status={latest.get('status')}")


def _create_tutor_turn(client: httpx.Client, fixture: dict[str, str]) -> str:
    session_response = client.post(
        f"/api/v1/workspaces/{fixture['workspace_id']}/courses/"
        f"{fixture['course_id']}/tutor-sessions",
        json={
            "course_version_id": fixture["course_version_id"],
            "external_processing_ack": True,
        },
    )
    session_response.raise_for_status()
    session_id = session_response.json()["id"]
    turn_response = client.post(
        f"/api/v1/workspaces/{fixture['workspace_id']}/tutor-sessions/"
        f"{session_id}/turns",
        headers={"Idempotency-Key": f"system-{uuid4()}"},
        json={
            "question": "Why does binary search halve the search interval?",
            "scope": "lesson",
            "section_id": fixture["section_id"],
            "lesson_id": fixture["lesson_id"],
            "lesson_version_id": fixture["lesson_version_id"],
        },
    )
    assert turn_response.status_code == 202, turn_response.text
    return turn_response.json()["id"]


def _provider_calls(turn_id: str) -> tuple[AgentRun, list[ProviderCall]]:
    with SessionLocal() as db:
        run = db.scalar(
            select(AgentRun)
            .where(AgentRun.tutor_turn_id == turn_id)
            .order_by(AgentRun.created_at.desc())
        )
        assert run is not None
        db.expunge(run)
        calls = list(
            db.scalars(
                select(ProviderCall)
                .where(ProviderCall.agent_run_id == run.id)
                .order_by(ProviderCall.ordinal)
            )
        )
        for call in calls:
            db.expunge(call)
    return run, calls


def test_tutor_http_queue_worker_postgres_provider_call_path() -> None:
    fixture = _seed_reader_fixture()
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        _reset_stub(client, "success")
        turn_id = _create_tutor_turn(client, fixture)
        turn = _poll_turn(client, fixture["workspace_id"], turn_id)

    assert turn["status"] == "succeeded", turn
    assert turn["answer_blocks"]
    run, calls = _provider_calls(turn_id)
    assert run.workspace_id == fixture["workspace_id"]
    assert run.status == "succeeded"
    assert [call.ordinal for call in calls] == list(range(len(calls)))
    assert [call.phase for call in calls] == ["plan", "answer"]
    assert all(call.status == "succeeded" for call in calls)
    assert all(call.input_tokens == 11 for call in calls)
    assert all(call.output_tokens == 7 for call in calls)
    assert all(call.workspace_id == fixture["workspace_id"] for call in calls)


def test_tutor_invalid_answer_uses_bounded_repair() -> None:
    fixture = _seed_reader_fixture()
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        _reset_stub(client, "repair")
        turn_id = _create_tutor_turn(client, fixture)
        turn = _poll_turn(client, fixture["workspace_id"], turn_id)

    assert turn["status"] == "succeeded", turn
    assert turn["answer_blocks"], turn
    run, calls = _provider_calls(turn_id)
    assert run.status == "succeeded"
    assert [call.phase for call in calls] == ["plan", "answer", "repair"]
    assert [call.ordinal for call in calls] == [0, 1, 2]
    assert all(call.status == "succeeded" for call in calls)


def test_tutor_timeout_is_recorded_and_enters_retry_wait() -> None:
    fixture = _seed_reader_fixture()
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        _reset_stub(client, "timeout")
        turn_id = _create_tutor_turn(client, fixture)
        turn = _poll_turn(client, fixture["workspace_id"], turn_id)

    assert turn["status"] == "retry_wait", turn
    assert turn["error_code"] == "generation_provider_unavailable"
    run, calls = _provider_calls(turn_id)
    assert run.status == "failed"
    assert run.error_code == "generation_provider_unavailable"
    assert len(calls) == 1
    assert calls[0].phase == "plan"
    assert calls[0].status == "timed_out"
    assert calls[0].error_code == "provider_timeout"
