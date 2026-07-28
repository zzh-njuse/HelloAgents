from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..services.provider_cost import CURRENCY_CNY, RATE_NUMERIC_PRECISION, RATE_NUMERIC_SCALE
from .base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("slug", name="uq_workspaces_slug"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceDeletionJob(Base):
    __tablename__ = "workspace_deletion_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_workspace_deletion_jobs_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # Deliberately not an FK: the minimal job remains queryable after the workspace is hard deleted.
    workspace_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "document_versions.id",
            name="fk_source_documents_current_version",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_storage_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    parsed_storage_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parser_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_ingestion_jobs_idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_version_id", "ordinal", name="uq_document_chunks_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DocumentParseReport(Base):
    __tablename__ = "document_parse_reports"
    __table_args__ = (UniqueConstraint("document_version_id", "attempt_number", name="uq_document_parse_reports_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class RagQueryTrace(Base):
    __tablename__ = "rag_query_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    filter_summary: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    collection_name: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_ingestion_batches_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_metadata_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="accepting", nullable=False, index=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ready_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    canceled_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_declared_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionBatchItem(Base):
    __tablename__ = "ingestion_batch_items"
    __table_args__ = (UniqueConstraint("batch_id", "client_ordinal", name="uq_ingestion_batch_items_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id"), index=True, nullable=False)
    client_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    display_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    declared_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("source_documents.id"), nullable=True)
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id"), nullable=True)
    ingestion_job_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_jobs.id"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class RagAnswerTrace(Base):
    __tablename__ = "rag_answer_traces"
    __table_args__ = (
        # Composite-FK target for provider_calls (Stage 5 Slice 1B-2:
        # RAG owner Workspace isolation). ``id`` is already the PK, so
        # (id, workspace_id) is trivially unique and this can never be
        # violated — it exists only so Postgres accepts the matching
        # composite foreign key on provider_calls below.
        UniqueConstraint("id", "workspace_id", name="uq_rag_answer_traces_id_workspace"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    query_trace_id: Mapped[str | None] = mapped_column(ForeignKey("rag_query_traces.id"), nullable=True)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_template_version: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence_chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    citation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieval_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    current_active_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_versions.id", name="fk_courses_current_active_version", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CourseVersion(Base):
    __tablename__ = "course_versions"
    __table_args__ = (UniqueConstraint("course_id", "version_number", name="uq_course_versions_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class CourseVersionSource(Base):
    __tablename__ = "course_version_sources"
    __table_args__ = (UniqueConstraint("course_version_id", "document_version_id", name="uq_course_version_sources_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True, nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=False)


class CourseSection(Base):
    __tablename__ = "course_sections"
    __table_args__ = (UniqueConstraint("course_version_id", "ordinal", name="uq_course_sections_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)


class CourseSectionCitation(Base):
    __tablename__ = "course_section_citations"
    __table_args__ = (UniqueConstraint("course_section_id", "document_chunk_id", name="uq_course_section_citations_chunk"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_section_id: Mapped[str] = mapped_column(ForeignKey("course_sections.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    document_chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("course_section_id", "ordinal", name="uq_lessons_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    course_section_id: Mapped[str] = mapped_column(ForeignKey("course_sections.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    current_published_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("lesson_versions.id", name="fk_lessons_current_published_version", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )


class LessonVersion(Base):
    __tablename__ = "lesson_versions"
    __table_args__ = (UniqueConstraint("lesson_id", "version_number", name="uq_lesson_versions_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True, nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    learning_objectives: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    blocks: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    # Per Correction 011 §1.2: structured practice type hints set by the
    # Lesson Writer during generation. Used by Practice type adaptation
    # as a structural, content-agnostic contract — NOT keyword scanning.
    practice_type_hints: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LessonCitation(Base):
    __tablename__ = "lesson_citations"
    __table_args__ = (UniqueConstraint("lesson_version_id", "block_key", "document_chunk_id", name="uq_lesson_citations_block_chunk"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    block_key: Mapped[str] = mapped_column(String(100), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    document_chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)


class CourseGenerationJob(Base):
    __tablename__ = "course_generation_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_course_generation_jobs_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True, nullable=False)
    course_version_id: Mapped[str | None] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True, nullable=True)
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    output_language: Mapped[str] = mapped_column(String(10), default="zh-CN", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Slice 4 packet 002: Lesson Writer science verification authorization
    science_tool_authorized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class CourseGenerationJobSource(Base):
    __tablename__ = "course_generation_job_sources"
    __table_args__ = (UniqueConstraint("course_generation_job_id", "document_version_id", name="uq_course_generation_job_sources_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_generation_job_id: Mapped[str] = mapped_column(ForeignKey("course_generation_jobs.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True, nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=False)


class TutorSession(Base):
    __tablename__ = "tutor_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True, nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    external_processing_ack_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_turn_ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TutorTurn(Base):
    __tablename__ = "tutor_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "ordinal", "attempt_number", name="uq_tutor_turns_session_ordinal_attempt"),
        UniqueConstraint("session_id", "idempotency_key", name="uq_tutor_turns_session_key"),
        # The teaching-skill snapshot is all-NULL (historical turn) or fully
        # populated (Slice 3 turn). Declared on the ORM so SQLite test tables
        # match the Postgres migration 0019 contract (corr 3.8).
        CheckConstraint(
            "((teaching_skill_id IS NULL AND teaching_skill_version IS NULL AND teaching_skill_hash IS NULL) "
            "OR (teaching_skill_id IS NOT NULL AND teaching_skill_version IS NOT NULL AND teaching_skill_hash IS NOT NULL))",
            name="ck_tutor_turns_teaching_skill_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("tutor_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("course_sections.id"), nullable=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    lesson_version_id: Mapped[str | None] = mapped_column(ForeignKey("lesson_versions.id"), nullable=True)
    history_through_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_blocks: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Slice 3 immutable teaching-skill snapshot. NULL for historical (pre-Slice-3)
    # turns; all three populated for new turns. The check constraint lives in
    # migration 0019 and guarantees "all NULL or all non-NULL".
    teaching_skill_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    teaching_skill_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    teaching_skill_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Slice 4 packet 002: code tool authorization and usage projection
    code_tool_authorized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    code_tool_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    code_tool_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    science_tool_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    science_tool_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TutorTurnCitation(Base):
    __tablename__ = "tutor_turn_citations"
    __table_args__ = (UniqueConstraint("turn_id", "citation_id", name="uq_tutor_turn_citations_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    turn_id: Mapped[str] = mapped_column(ForeignKey("tutor_turns.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    block_key: Mapped[str] = mapped_column(String(100), nullable=False)
    citation_id: Mapped[str] = mapped_column(String(50), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    document_chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "((CASE WHEN course_generation_job_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN tutor_turn_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN practice_job_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN code_lab_job_id IS NOT NULL THEN 1 ELSE 0 END)) = 1",
            name="ck_agent_runs_one_owner",
        ),
        # Composite-FK target for provider_calls (Stage 5 Slice 1B-1 Issue 1:
        # Workspace isolation). ``id`` is already the PK, so (id, workspace_id)
        # is trivially unique and this can never be violated — it exists only so
        # Postgres accepts the matching composite foreign key on provider_calls.
        # Human-approved minimal hardening of an existing table (2026-07-27);
        # recorded in Spec 002 / ADR 001.
        UniqueConstraint("id", "workspace_id", name="uq_agent_runs_id_workspace"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_generation_job_id: Mapped[str | None] = mapped_column(ForeignKey("course_generation_jobs.id"), index=True, nullable=True)
    tutor_turn_id: Mapped[str | None] = mapped_column(ForeignKey("tutor_turns.id", ondelete="CASCADE"), index=True, nullable=True)
    practice_job_id: Mapped[str | None] = mapped_column(ForeignKey("practice_jobs.id"), index=True, nullable=True)
    code_lab_job_id: Mapped[str | None] = mapped_column(ForeignKey("code_lab_jobs.id", ondelete="CASCADE"), index=True, nullable=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PracticeJob(Base):
    __tablename__ = "practice_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_practice_jobs_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    practice_set_id: Mapped[str | None] = mapped_column(ForeignKey("practice_sets.id", use_alter=True), index=True, nullable=True)
    practice_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("practice_attempts.id", use_alter=True), index=True, nullable=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), index=True, nullable=True)
    course_version_id: Mapped[str | None] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True, nullable=True)
    lesson_version_id: Mapped[str | None] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=True)
    output_language: Mapped[str] = mapped_column(String(10), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    external_processing_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Slice 4 packet 002: item type mode and code language request
    item_type_mode: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    code_languages: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Slice 5 (ADR 007 §3.9): artifact contract version pinned at creation.
    # Failed/retry Jobs keep their snapshot instead of reading a deployment
    # default that could silently change the contract after an upgrade.
    # Existing rows backfill to practice_artifact_v1 via migration 0023.
    artifact_contract_version: Mapped[str] = mapped_column(String(40), default="practice_artifact_v1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PracticeJobSource(Base):
    __tablename__ = "practice_job_sources"
    __table_args__ = (UniqueConstraint("practice_job_id", "document_version_id", name="uq_practice_job_sources_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_job_id: Mapped[str] = mapped_column(ForeignKey("practice_jobs.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)


class PracticeSet(Base):
    __tablename__ = "practice_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True, nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True, nullable=False)
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=False)
    practice_job_id: Mapped[str | None] = mapped_column(ForeignKey("practice_jobs.id", use_alter=True), index=True, nullable=True)
    output_language: Mapped[str] = mapped_column(String(10), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PracticeItem(Base):
    __tablename__ = "practice_items"
    __table_args__ = (UniqueConstraint("practice_set_id", "ordinal", name="uq_practice_items_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_set_id: Mapped[str] = mapped_column(ForeignKey("practice_sets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    # Hidden grading material: correct option, option rationales, rubric and
    # reference answer. Never projected into a pre-submission read schema.
    answer_spec: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    # Slice 4 packet 002: public interaction spec for coding items
    # (language, starter_code, io description, constraints, public examples, limits)
    # Null for non-coding items.
    interaction_spec: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PracticeItemCitation(Base):
    __tablename__ = "practice_item_citations"
    __table_args__ = (UniqueConstraint("practice_item_id", "citation_key", name="uq_practice_item_citations_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    citation_key: Mapped[str] = mapped_column(String(50), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    document_chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)


class PracticeAttempt(Base):
    __tablename__ = "practice_attempts"
    __table_args__ = (
        UniqueConstraint("practice_item_id", "ordinal", name="uq_practice_attempts_item_ordinal"),
        UniqueConstraint("practice_item_id", "idempotency_key", name="uq_practice_attempts_item_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    practice_item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    answer_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    # Slice 4 packet 002: source code for coding attempts (1..20000 chars)
    source_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="succeeded", nullable=False, index=True)
    practice_job_id: Mapped[str | None] = mapped_column(ForeignKey("practice_jobs.id"), index=True, nullable=True)
    external_processing_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PracticeFeedback(Base):
    __tablename__ = "practice_feedback"
    __table_args__ = (UniqueConstraint("practice_attempt_id", name="uq_practice_feedback_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_attempt_id: Mapped[str] = mapped_column(ForeignKey("practice_attempts.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    verdict: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criterion_results: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    feedback_blocks: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    is_ai_graded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Slice 4 packet 002: coding execution summary (safe projection)
    coding_tests_passed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coding_tests_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coding_error_categories: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    coding_public_cases: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


# --------------------------------------------------------------------------- #
# Stage 4 Slice 2: Mastery, Review and Memory
# --------------------------------------------------------------------------- #


class LearningTarget(Base):
    __tablename__ = "learning_targets"
    __table_args__ = (UniqueConstraint("lesson_version_id", "target_key", name="uq_learning_targets_version_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=False)
    target_key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # objective | lesson_overall
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PracticeItemTarget(Base):
    __tablename__ = "practice_item_targets"
    __table_args__ = (UniqueConstraint("practice_item_id", "learning_target_id", "criterion_key", name="uq_practice_item_targets_item_target_criterion"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id"), index=True, nullable=False)
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    criterion_key: Mapped[str | None] = mapped_column(String(100), nullable=True)


class LearningEvent(Base):
    __tablename__ = "learning_events"
    __table_args__ = (UniqueConstraint("practice_feedback_id", name="uq_learning_events_feedback"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)  # practice_result
    practice_attempt_id: Mapped[str] = mapped_column(ForeignKey("practice_attempts.id"), index=True, nullable=False)
    practice_feedback_id: Mapped[str] = mapped_column(ForeignKey("practice_feedback.id"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MasterySignal(Base):
    __tablename__ = "mastery_signals"
    __table_args__ = (UniqueConstraint("learning_event_id", "learning_target_id", name="uq_mastery_signals_event_target"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_event_id: Mapped[str] = mapped_column(ForeignKey("learning_events.id"), index=True, nullable=False)
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    practice_item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id"), nullable=False)
    practice_set_id: Mapped[str] = mapped_column(ForeignKey("practice_sets.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # positive | partial | negative
    value: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)  # single_choice | short_answer
    is_ai_derived: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MasteryState(Base):
    __tablename__ = "mastery_states"
    __table_args__ = (UniqueConstraint("learning_target_id", name="uq_mastery_states_target"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    band: Mapped[str] = mapped_column(String(20), nullable=False)  # insufficient | needs_review | developing | secure
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_set_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    projection_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(20), default="001", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class Weakness(Base):
    __tablename__ = "weaknesses"
    __table_args__ = (UniqueConstraint("learning_target_id", name="uq_weaknesses_target"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="provisional", nullable=False)  # provisional|confirmed|resolved|dismissed
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_negative_event_id: Mapped[str | None] = mapped_column(ForeignKey("learning_events.id"), nullable=True)
    last_negative_event_id: Mapped[str | None] = mapped_column(ForeignKey("learning_events.id"), nullable=True)
    memory_suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("weakness_id", name="uq_review_items_weakness"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    weakness_id: Mapped[str] = mapped_column(ForeignKey("weaknesses.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="due", nullable=False)  # due|reviewing|awaiting_validation|snoozed|dismissed|resolved
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    review_item_id: Mapped[str] = mapped_column(ForeignKey("review_items.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)  # reviewing|reviewed|snooze|dismiss|reopen
    snooze_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class LearningProjectionJob(Base):
    __tablename__ = "learning_projection_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_learning_projection_jobs_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LearningMemory(Base):
    __tablename__ = "learning_memories"
    __table_args__ = (
        Index(
            "uq_learning_memories_current_target",
            "learning_target_id",
            unique=True,
            postgresql_where=text("status <> 'archived'"),
            sqlite_where=text("status <> 'archived'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=False)
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    weakness_id: Mapped[str | None] = mapped_column(ForeignKey("weaknesses.id", use_alter=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # weakness
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|needs_review|paused|archived
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_supported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class LearningMemorySource(Base):
    __tablename__ = "learning_memory_sources"
    __table_args__ = (UniqueConstraint("learning_memory_id", "learning_event_id", name="uq_learning_memory_sources_memory_event"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_memory_id: Mapped[str] = mapped_column(ForeignKey("learning_memories.id", ondelete="CASCADE"), index=True, nullable=False)
    learning_event_id: Mapped[str] = mapped_column(ForeignKey("learning_events.id"), nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)


class LearningMemoryRevision(Base):
    __tablename__ = "learning_memory_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_memory_id: Mapped[str] = mapped_column(ForeignKey("learning_memories.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)  # auto_created|edited|reconfirmed|paused|archived|conflicted
    before_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class LearningMemoryPolicy(Base):
    __tablename__ = "learning_memory_policies"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_learning_memory_policies_workspace"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    tutor_use_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class LessonCompletion(Base):
    __tablename__ = "lesson_completions"
    __table_args__ = (UniqueConstraint("workspace_id", "lesson_version_id", name="uq_lesson_completions_workspace_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id", ondelete="CASCADE"), index=True, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


# --------------------------------------------------------------------------- #
# Stage 4 Slice 4: Controlled MCP Capabilities
# --------------------------------------------------------------------------- #


class WorkspaceMcpPolicy(Base):
    __tablename__ = "workspace_mcp_policies"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    code_execution_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class CodeLabRun(Base):
    __tablename__ = "code_lab_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    # Optional navigation grouping
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)
    course_version_id: Mapped[str | None] = mapped_column(ForeignKey("course_versions.id", ondelete="SET NULL"), nullable=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True)
    lesson_version_id: Mapped[str | None] = mapped_column(ForeignKey("lesson_versions.id", ondelete="SET NULL"), nullable=True)
    # Fixed language
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    # Private I/O
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    stdin: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Execution result
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    compile_output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stdout: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stdout_truncated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stderr_truncated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # MCP snapshot
    mcp_server_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mcp_server_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mcp_protocol_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mcp_tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mcp_input_schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mcp_output_schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CodeLabJob(Base):
    __tablename__ = "code_lab_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_code_lab_jobs_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("code_lab_runs.id", ondelete="CASCADE"), nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TutorTurnToolAuthorization(Base):
    __tablename__ = "tutor_turn_tool_authorizations"
    __table_args__ = (UniqueConstraint("turn_id", "capability_id", name="uq_tutor_turn_tool_auth_turn_capability"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    turn_id: Mapped[str] = mapped_column(ForeignKey("tutor_turns.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    capability_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # Budget
    max_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    used_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # MCP snapshot
    mcp_server_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mcp_protocol_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mcp_tool_allowlist: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    mcp_schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Timestamps
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TutorTurnCodeRun(Base):
    __tablename__ = "tutor_turn_code_runs"
    __table_args__ = (UniqueConstraint("turn_id", name="uq_tutor_turn_code_runs_turn"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    turn_id: Mapped[str] = mapped_column(ForeignKey("tutor_turns.id", ondelete="CASCADE"), index=True, nullable=False)
    code_lab_run_id: Mapped[str] = mapped_column(ForeignKey("code_lab_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)


# --------------------------------------------------------------------------- #
# Stage 4 Slice 4: MCP Capability Status Projection (correction 004 §3/§4)
# --------------------------------------------------------------------------- #


class McpCapabilityStatus(Base):
    """Desensitized capability readiness projection written by probe/worker.

    Per correction 004 §3/§4: readiness must come from an actual, TTL-bearing
    capability status projection — not from enabled=True or URL non-empty.
    The probe/worker that holds the remote config writes this row; the API
    only reads it. enabled ≠ ready.

    The projection contains only desensitized status information — never
    URLs, credentials, remote body text, or internal IDs.
    """

    __tablename__ = "mcp_capability_statuses"
    __table_args__ = (UniqueConstraint("capability_id", name="uq_mcp_capability_statuses_capability"),)

    capability_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    # Projection status: "ready" | "unavailable" | "verification_pending" | "disabled"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="unavailable")
    # Desensitized detail — stable, human-readable reason only
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Verified schema hash from the last successful probe (empty = never verified)
    verified_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # TTL: when this projection was last checked
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    # TTL: how many seconds this projection remains valid
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


# --------------------------------------------------------------------------- #
# Stage 4 Slice 4 Packet 002: Job Tool Authorizations
# --------------------------------------------------------------------------- #


class JobToolAuthorization(Base):
    """Per-Job MCP tool authorization with owner check.

    Per SLICE_4_GLM_IMPLEMENTATION_PACKET_002 §7.1:
    - Each row belongs to exactly one job owner (CourseGenerationJob or PracticeJob)
    - The owner check constraint ensures exactly one FK is non-null
    - Partial unique indexes prevent duplicate (owner, capability) pairs
    - Budget is tracked via max_calls/used_calls
    - MCP snapshot is frozen at authorization time

    The owner constraint uses portable CASE expressions so SQLite tests and
    Postgres enforce the same invariant.
    """
    __tablename__ = "job_tool_authorizations"
    __table_args__ = (
        CheckConstraint(
            "((CASE WHEN course_generation_job_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN practice_job_id IS NOT NULL THEN 1 ELSE 0 END)) = 1",
            name="ck_job_tool_auth_one_owner",
        ),
        Index(
            "uq_job_tool_auth_course_cap",
            "course_generation_job_id",
            "capability_id",
            unique=True,
            postgresql_where=text("course_generation_job_id IS NOT NULL"),
            sqlite_where=text("course_generation_job_id IS NOT NULL"),
        ),
        Index(
            "uq_job_tool_auth_practice_cap",
            "practice_job_id",
            "capability_id",
            unique=True,
            postgresql_where=text("practice_job_id IS NOT NULL"),
            sqlite_where=text("practice_job_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    capability_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # Owner: exactly one non-null (enforced by check constraint)
    course_generation_job_id: Mapped[str | None] = mapped_column(ForeignKey("course_generation_jobs.id"), index=True, nullable=True)
    practice_job_id: Mapped[str | None] = mapped_column(ForeignKey("practice_jobs.id"), index=True, nullable=True)
    # Budget
    max_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    used_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # MCP snapshot (frozen at authorization time)
    server_allowlist: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    schema_hash_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    protocol_version_snapshot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Timestamps
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------- #
# Stage 5 Slice 1B-1: Provider Call and CNY rate snapshot foundation
# (Spec 002 / ADR 001). Independent facts for per-request provider cost.
# This slice only defines schema + a pure calculator; no business chain,
# API/Web or real provider calls are wired here.
# --------------------------------------------------------------------------- #


class ProviderRateSnapshot(Base):
    """Append-only CNY price snapshot for a provider/model (Spec 002 §2).

    Human-maintained per-million-token input/output unit prices, fixed to CNY.
    A Provider Call binds an immutable snapshot so historical cost never reads
    the current configuration. There is intentionally no update/delete business
    method on this fact.
    """

    __tablename__ = "provider_rate_snapshots"
    __table_args__ = (
        UniqueConstraint("provider", "model", "effective_at", name="uq_provider_rate_snapshots_pme"),
        # Composite-FK target for provider_calls (Issue 2: no wrong-price
        # binding). ``id`` is already the PK, so (id, provider, model) is
        # trivially unique and this constraint can never be violated — it exists
        # only so Postgres accepts the matching composite foreign key below.
        UniqueConstraint("id", "provider", "model", name="uq_provider_rate_snapshots_id_provider_model"),
        CheckConstraint("currency = 'CNY'", name="ck_provider_rate_snapshots_currency_cny"),
        CheckConstraint("input_rate_per_1m >= 0", name="ck_provider_rate_snapshots_input_rate_nonneg"),
        CheckConstraint("output_rate_per_1m >= 0", name="ck_provider_rate_snapshots_output_rate_nonneg"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default=CURRENCY_CNY, server_default=CURRENCY_CNY)
    input_rate_per_1m: Mapped[Decimal] = mapped_column(Numeric(RATE_NUMERIC_PRECISION, RATE_NUMERIC_SCALE), nullable=False)
    output_rate_per_1m: Mapped[Decimal] = mapped_column(Numeric(RATE_NUMERIC_PRECISION, RATE_NUMERIC_SCALE), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ProviderCall(Base):
    """One real provider request attempt — not an Agent step or Tool call.

    Per Spec 002 §2 / ADR 001: provider/model, usage, status and price are
    captured as a call-time snapshot so repair/retry and multiple requests
    never overwrite each other. Never stores prompt, message, evidence,
    answer, provider raw response or raw error — only a stable error code.

    Per Spec 003 §4 / ADR 002: agent_run_id and rag_answer_trace_id are
    mutually exclusive (at most one non-null). Both NULL allows workspace-only
    calls. RAG owner uses a composite FK for Workspace isolation, matching
    the AgentRun pattern from 0024.
    """

    __tablename__ = "provider_calls"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_provider_calls_ordinal_nonneg"),
        CheckConstraint(
            "status IN ('started','succeeded','failed','timed_out','canceled')",
            name="ck_provider_calls_status_valid",
        ),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_provider_calls_input_tokens_nonneg"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_provider_calls_output_tokens_nonneg"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_provider_calls_latency_nonneg"),
        # Owner mutual exclusion (Spec 003 §4): at most one of agent_run_id
        # or rag_answer_trace_id may be non-null. Both NULL is allowed
        # (workspace-only call).
        CheckConstraint(
            "(CASE WHEN agent_run_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN rag_answer_trace_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
            name="ck_provider_calls_one_owner",
        ),
        # Issue 2: a bound snapshot's provider/model must equal the call's
        # provider/model, so a call can never inherit another model's price.
        # Composite FK over (snapshot_id, provider, model): MATCH SIMPLE skips
        # it when provider_rate_snapshot_id IS NULL (call has no snapshot);
        # when set, the (id, provider, model) triple must exist on
        # provider_rate_snapshots, forcing the provider/model to match.
        ForeignKeyConstraint(
            ["provider_rate_snapshot_id", "provider", "model"],
            ["provider_rate_snapshots.id", "provider_rate_snapshots.provider", "provider_rate_snapshots.model"],
            name="fk_provider_calls_snapshot_provider_model",
        ),
        # Issue 1: when a call is bound to an AgentRun, its workspace_id must
        # equal the run's workspace_id (Workspace isolation). Composite FK over
        # (agent_run_id, workspace_id): MATCH SIMPLE skips it when
        # agent_run_id IS NULL (workspace-only call); when set, the
        # (id, workspace_id) pair must exist on agent_runs, forcing the
        # workspaces to match. ON DELETE CASCADE is required here because
        # Postgres checks constraints in DDL order; since this composite FK
        # appears before the simple FK in SQLAlchemy's emitted DDL, NO ACTION
        # would block the AgentRun delete before the simple FK's CASCADE fires.
        ForeignKeyConstraint(
            ["agent_run_id", "workspace_id"],
            ["agent_runs.id", "agent_runs.workspace_id"],
            name="fk_provider_calls_run_workspace",
            ondelete="CASCADE",
        ),
        # RAG owner Workspace isolation (Spec 003 §4 / ADR 002 §7):
        # when a call is bound to a RagAnswerTrace, its workspace_id must
        # equal the trace's workspace_id. Composite FK over
        # (rag_answer_trace_id, workspace_id): MATCH SIMPLE skips it when
        # rag_answer_trace_id IS NULL; when set, forces workspace match.
        # ON DELETE CASCADE: deleting a RagAnswerTrace cascades to its calls.
        ForeignKeyConstraint(
            ["rag_answer_trace_id", "workspace_id"],
            ["rag_answer_traces.id", "rag_answer_traces.workspace_id"],
            name="fk_provider_calls_rag_trace_workspace",
            ondelete="CASCADE",
        ),
        # ordinal uniquely identifies a call within a run (Spec §5 gate).
        # Workspace-only calls (no agent_run) are excluded so they don't clash.
        Index(
            "uq_provider_calls_run_ordinal",
            "agent_run_id",
            "ordinal",
            unique=True,
            postgresql_where=text("agent_run_id IS NOT NULL"),
            sqlite_where=text("agent_run_id IS NOT NULL"),
        ),
        # RAG owner ordinal uniqueness (Spec 003 §4): ordinal is unique within
        # a RagAnswerTrace. Calls without a RAG trace are excluded.
        Index(
            "uq_provider_calls_rag_trace_ordinal",
            "rag_answer_trace_id",
            "ordinal",
            unique=True,
            postgresql_where=text("rag_answer_trace_id IS NOT NULL"),
            sqlite_where=text("rag_answer_trace_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True, nullable=True)
    rag_answer_trace_id: Mapped[str | None] = mapped_column(ForeignKey("rag_answer_traces.id", ondelete="CASCADE"), index=True, nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="started", nullable=False, index=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stable error code only — no raw error text, message or provider payload.
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_rate_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_rate_snapshots.id"), index=True, nullable=True
    )
    # Eager-joinable relationship for the read API (Slice 1B-3).
    # Never used for write; the recorder sets provider_rate_snapshot_id directly.
    # foreign_keys is required because there are two FK paths between
    # provider_calls and provider_rate_snapshots (the simple FK on
    # provider_rate_snapshot_id, and the composite FK for Issue 2).
    provider_rate_snapshot: Mapped[ProviderRateSnapshot | None] = relationship(
        ProviderRateSnapshot,
        foreign_keys=[provider_rate_snapshot_id],
        lazy="select",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
