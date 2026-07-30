"""Seed a desensitised browser fixture for the Slice 2B Batch B tool specs.

Creates ONE workspace + course with TWO lessons (one coding-suitable, one
science-suitable) plus a source chunk embedded in Qdrant, so the Playwright
Practice/Tutor tool specs can drive generation, answering, grading and the run
record through the real UI/API/worker/MCP path. Reuses controlled_helpers for
the DB + Qdrant wiring. Run inside the system-test runner image.
"""

from __future__ import annotations

from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from learn_platform_api.db.models import (
    Course, CourseSection, CourseVersion, CourseVersionSource,
    DocumentChunk, DocumentVersion, Lesson, LessonVersion, SourceDocument, Workspace,
)
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.settings import get_settings
from learn_platform_api.workers import ensure_collection

from controlled_helpers import wait_for_environment


def _lesson_version(db, cv, section, ws, *, ordinal, title, profile):
    lesson = Lesson(course_version_id=cv.id, course_section_id=section.id,
                    workspace_id=ws.id, ordinal=ordinal, title=title, objective="o")
    db.add(lesson); db.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id,
                       version_number=1, status="published", title=title,
                       learning_objectives=["objective_1"],
                       blocks=[{"block_key": "b1", "type": "text", "text": "body", "citation_ids": []}],
                       practice_type_hints=[{"objective_key": "objective_1", "evidence_keys": ["e1"], **profile}])
    db.add(lv); db.flush()
    lesson.current_published_version_id = lv.id
    return lesson, lv


def main() -> None:
    wait_for_environment(practice=True, tutor=True)
    short = uuid4().hex[:6]
    coding_profile = {"has_algorithmic_objective": True, "has_executable_evidence": True,
                      "has_math_objective": False, "has_physics_objective": False,
                      "has_chemistry_objective": False, "has_computable_evidence": False}
    science_profile = {"has_algorithmic_objective": False, "has_executable_evidence": False,
                       "has_math_objective": True, "has_physics_objective": False,
                       "has_chemistry_objective": False, "has_computable_evidence": True}
    with SessionLocal() as db:
        ws = Workspace(name=f"Stage5 2B Browser {short}", slug=f"stage5-2b-{short}",
                       description="Controlled browser tool fixture")
        db.add(ws); db.flush()
        doc = SourceDocument(workspace_id=ws.id, display_name="tools_source.md", lifecycle_status="active")
        db.add(doc); db.flush()
        ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready",
                              original_filename="tools_source.md", mime_type="text/markdown",
                              byte_size=96, sha256="a" * 64, original_storage_uri="file:///controlled")
        db.add(ver); db.flush()
        doc.current_version_id = ver.id
        chunk_id = str(uuid4())
        db.add(DocumentChunk(id=chunk_id, document_version_id=ver.id, ordinal=0,
                             content="Binary search halves the remaining sorted search interval.",
                             content_hash="b" * 64, start_offset=0, end_offset=50, page_start=1, page_end=1))
        course = Course(workspace_id=ws.id, title=f"Stage5 2B Tools {short}", goal="g",
                        audience="general", lifecycle_status="active")
        db.add(course); db.flush()
        cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active",
                           title=course.title, summary="s")
        db.add(cv); db.flush()
        course.current_active_version_id = cv.id
        db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id,
                                   document_id=doc.id, document_version_id=ver.id))
        section = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="s", objective="o")
        db.add(section); db.flush()
        coding_lesson, coding_lv = _lesson_version(db, cv, section, ws, ordinal=0,
                                                   title=f"Coding Tools {short}", profile=coding_profile)
        science_lesson, science_lv = _lesson_version(db, cv, section, ws, ordinal=1,
                                                     title=f"Science Tools {short}", profile=science_profile)
        db.commit()
        fixture = {"workspace_id": ws.id, "course_id": course.id, "course_version_id": cv.id,
                   "coding_lesson_id": coding_lesson.id, "coding_lesson_version_id": coding_lv.id,
                   "science_lesson_id": science_lesson.id, "science_lesson_version_id": science_lv.id,
                   "document_id": doc.id, "chunk_id": chunk_id}

    settings = get_settings()
    qdrant = QdrantClient(url=settings.qdrant_url)
    try:
        ensure_collection(qdrant, settings)
        # Practice/Tutor generation scope retrieval to the job's source documents:
        # services/retrieval.retrieve(...) adds a Qdrant `must` filter on
        # payload.document_id when document_ids is passed. A point whose payload
        # omits document_id is silently dropped -> empty evidence ->
        # `insufficient_evidence` (job fails "当前资料不足以生成练习"). Mirror the
        # passing controlled_helpers.seed_practice_lesson payload exactly.
        qdrant.upsert(collection_name=settings.product_collection_name, wait=True, points=[
            PointStruct(id=fixture["chunk_id"], vector=[1.0, 0.0, 0.0, 0.0],
                        payload={"workspace_id": fixture["workspace_id"],
                                 "document_id": fixture["document_id"], "chunk_id": fixture["chunk_id"]})])
    finally:
        qdrant.close()
    print("SEEDED Stage5 2B Browser", short)


if __name__ == "__main__":
    main()
