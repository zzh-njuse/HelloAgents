from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun,
    AgentToolCall,
    CodeLabJob,
    CodeLabRun,
    Course,
    CourseGenerationJob,
    CourseSection,
    CourseVersion,
    Lesson,
    PracticeAttempt,
    PracticeItem,
    PracticeJob,
    PracticeSet,
    TutorSession,
    TutorTurn,
    Workspace,
)

# Keys that must never appear in a safe run summary projection. The assertion is
# on the full (recursively collected) JSON key set, not just null values: a
# forbidden field must be entirely absent.
FORBIDDEN_KEYS = {
    "prompt", "system_prompt", "system", "messages", "question", "answer", "answer_blocks",
    "draft", "blocks", "coverage", "coverage_plan", "evidence", "chunk", "content", "text",
    "original_storage_uri", "parsed_storage_uri", "path", "file_path", "absolute_path",
    "input_hash", "tool_input", "input", "provider", "model", "base_url", "api_key",
    "url", "connection", "connection_string", "log", "logs", "raw", "raw_response",
    "query", "queries", "question_hash", "answer_hash", "sha256", "byte_size",
    "environment", "env", "idempotency_key", "worker_id", "lease_expires_at",
    "external_processing_ack_at", "key", "secret", "token",
    # Stage 4 private fields that must never leak into run summary
    "source_code", "stdin", "stdout", "stderr", "compile_output",
    "stem", "options", "answer_spec", "rubric", "feedback",
    "answer_payload", "observation", "exit_code",
    "mcp_server_name", "mcp_server_version", "mcp_protocol_version",
    "mcp_tool_name", "mcp_input_schema_hash", "mcp_output_schema_hash",
    "runtime", "duration_ms",
}


def _collect_keys(obj, into=None):
    into = set() if into is None else into
    if isinstance(obj, dict):
        into.update(obj.keys())
        for value in obj.values():
            _collect_keys(value, into)
    elif isinstance(obj, list):
        for value in obj:
            _collect_keys(value, into)
    return into


def _seed_course(db: Session, *, name: str = "Runs workspace", slug: str = "runs-workspace", title: str = "Algorithms"):
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace); db.flush()
    course = Course(workspace_id=workspace.id, title=title, goal="Learn")
    db.add(course); db.flush()
    version = CourseVersion(course_id=course.id, workspace_id=workspace.id, version_number=1, status="active", title=course.title)
    db.add(version); db.flush()
    course.current_active_version_id = version.id
    section = CourseSection(course_version_id=version.id, workspace_id=workspace.id, ordinal=0, title="Search", objective="Understand search")
    db.add(section); db.flush()
    lesson = Lesson(course_version_id=version.id, course_section_id=section.id, workspace_id=workspace.id, ordinal=0, title="Binary search", objective="Explain halving")
    db.add(lesson); db.flush()
    db.commit()
    return workspace, course, version, lesson


def _course_run(db: Session, workspace: Workspace, course: Course, *, role: str, job_type: str = "course_outline", lesson: Lesson | None = None, status: str = "succeeded", tokens: tuple[int | None, int | None] = (10, 20), with_tools: bool = True, age_seconds: int = 100):
    job = CourseGenerationJob(
        workspace_id=workspace.id, course_id=course.id, course_version_id=None,
        lesson_id=lesson.id if lesson else None, job_type=job_type, output_language="zh-CN",
        status="succeeded", idempotency_key=f"key-{course.id}-{job_type}-{role}-{age_seconds}",
    )
    db.add(job); db.flush()
    created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    completed = created + timedelta(seconds=5) if status != "running" else None
    run = AgentRun(
        course_generation_job_id=job.id, workspace_id=workspace.id, role=role, attempt_number=1,
        status=status, step_count=2, input_tokens=tokens[0], output_tokens=tokens[1],
        created_at=created, completed_at=completed,
    )
    db.add(run); db.flush()
    if with_tools:
        for ordinal, name, count, latency in [(2, "EvidenceSearch", 5, 30), (1, "Plan", 3, 12), (3, "Generate", None, 40)]:
            db.add(AgentToolCall(
                agent_run_id=run.id, workspace_id=workspace.id, tool_name=name, ordinal=ordinal,
                status="succeeded", result_count=count, latency_ms=latency, error_code=None,
            ))
    db.commit()
    return run


def _tutor_run(db: Session, workspace: Workspace, course: Course, *, scope: str = "lesson", lesson: Lesson | None = None, status: str = "succeeded", tokens: tuple[int | None, int | None] = (5, 7), age_seconds: int = 50):
    session = TutorSession(
        workspace_id=workspace.id, course_id=course.id, course_version_id=course.current_active_version_id,
        provider="provider-secret", model="model-secret", external_processing_ack_at=datetime.now(timezone.utc),
    )
    db.add(session); db.flush()
    turn = TutorTurn(
        session_id=session.id, workspace_id=workspace.id, ordinal=1, attempt_number=1, idempotency_key="turn-key",
        status="succeeded", question="secret-question-text", scope=scope, lesson_id=lesson.id if lesson else None,
        history_through_ordinal=0,
    )
    db.add(turn); db.flush()
    created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    completed = created + timedelta(seconds=2) if status != "running" else None
    run = AgentRun(
        tutor_turn_id=turn.id, workspace_id=workspace.id, role="tutor", attempt_number=1, status=status,
        step_count=1, input_tokens=tokens[0], output_tokens=tokens[1], created_at=created, completed_at=completed,
    )
    db.add(run); db.flush()
    db.commit()
    return run


def test_list_and_detail_cover_three_roles_and_tool_order(client: TestClient, db_session: Session) -> None:
    workspace, course, _, lesson = _seed_course(db_session)
    architect = _course_run(db_session, workspace, course, role="course_architect", job_type="course_outline", age_seconds=100)
    writer = _course_run(db_session, workspace, course, role="lesson_writer", job_type="lesson_draft", lesson=lesson, age_seconds=80)
    tutor = _tutor_run(db_session, workspace, course, scope="lesson", lesson=lesson, age_seconds=60)

    body = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs").json()
    roles = {item["role"] for item in body}
    assert roles == {"course_architect", "lesson_writer", "tutor"}
    # List items do not carry tool calls.
    assert all("tool_calls" not in item for item in body)
    # Ordering is most recent first.
    assert [item["created_at"] for item in body] == sorted((item["created_at"] for item in body), reverse=True)

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{architect.id}").json()
    assert detail["role"] == "course_architect"
    assert detail["status"] == "succeeded"
    assert detail["attempt_number"] == 1
    assert detail["step_count"] == 2
    assert detail["input_tokens"] == 10
    assert detail["output_tokens"] == 20
    assert detail["duration_seconds"] == 5.0
    assert detail["identity"]["kind"] == "course_generation"
    assert detail["identity"]["job_type"] == "course_outline"
    assert detail["identity"]["course_title"] == "Algorithms"
    assert detail["identity"]["course_deleted"] is False
    # Tool calls ordered by ordinal even though inserted out of order.
    assert [call["ordinal"] for call in detail["tool_calls"]] == [1, 2, 3]
    assert [call["tool_name"] for call in detail["tool_calls"]] == ["Plan", "EvidenceSearch", "Generate"]

    writer_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{writer.id}").json()
    assert writer_detail["identity"]["job_type"] == "lesson_draft"
    assert writer_detail["identity"]["lesson_title"] == "Binary search"

    tutor_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{tutor.id}").json()
    assert tutor_detail["identity"]["kind"] == "tutor"
    assert tutor_detail["identity"]["tutor_scope"] == "lesson"
    assert tutor_detail["identity"]["course_title"] == "Algorithms"
    assert tutor_detail["identity"]["lesson_title"] == "Binary search"


def test_workspace_isolation_and_unknown_run_404(client: TestClient, db_session: Session) -> None:
    workspace_a, course_a, _, _ = _seed_course(db_session, name="A", slug="a", title="Course A")
    workspace_b, _, _, _ = _seed_course(db_session, name="B", slug="b", title="Course B")
    run = _course_run(db_session, workspace_a, course_a, role="course_architect")

    # Cross-workspace access: empty list and 404 detail.
    assert client.get(f"/api/v1/workspaces/{workspace_b.id}/agent-runs").json() == []
    assert client.get(f"/api/v1/workspaces/{workspace_b.id}/agent-runs/{run.id}").status_code == 404
    # Unknown run within the owning workspace.
    assert client.get(f"/api/v1/workspaces/{workspace_a.id}/agent-runs/00000000-0000-0000-0000-000000000000").status_code == 404
    # Unknown workspace id.
    assert client.get(f"/api/v1/workspaces/00000000-0000-0000-0000-000000000000/agent-runs").status_code == 404


def test_filters_and_limit(client: TestClient, db_session: Session) -> None:
    workspace, course, _, lesson = _seed_course(db_session)
    _course_run(db_session, workspace, course, role="course_architect", status="succeeded", age_seconds=100)
    _course_run(db_session, workspace, course, role="lesson_writer", lesson=lesson, status="failed", age_seconds=80)
    _tutor_run(db_session, workspace, course, scope="course", age_seconds=60)

    by_role = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"role": "course_architect"}).json()
    assert [item["role"] for item in by_role] == ["course_architect"]

    by_status = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"status": "failed"}).json()
    assert [item["role"] for item in by_status] == ["lesson_writer"]

    by_course = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"course_id": course.id}).json()
    # All three runs belong to the same course (course jobs + tutor session course).
    assert len(by_course) == 3
    assert client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"course_id": "00000000-0000-0000-0000-000000000000"}).json() == []

    limited = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"limit": 2}).json()
    assert len(limited) == 2


def test_invalid_filters_return_422(client: TestClient, db_session: Session) -> None:
    workspace, _, _, _ = _seed_course(db_session)
    base = f"/api/v1/workspaces/{workspace.id}/agent-runs"
    assert client.get(base, params={"role": "bogus"}).status_code == 422
    assert client.get(base, params={"status": "bogus"}).status_code == 422
    assert client.get(base, params={"limit": 0}).status_code == 422
    assert client.get(base, params={"limit": 51}).status_code == 422
    assert client.get(base, params={"limit": "abc"}).status_code == 422


def test_running_completed_and_missing_usage(client: TestClient, db_session: Session) -> None:
    workspace, course, _, _ = _seed_course(db_session)
    running = _course_run(db_session, workspace, course, role="course_architect", status="running", tokens=(None, None))
    missing_usage = _course_run(db_session, workspace, course, role="lesson_writer", status="succeeded", tokens=(None, None), with_tools=False, age_seconds=70)

    running_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{running.id}").json()
    assert running_detail["status"] == "running"
    assert running_detail["completed_at"] is None
    assert running_detail["duration_seconds"] is None
    assert running_detail["input_tokens"] is None

    missing_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{missing_usage.id}").json()
    assert missing_detail["status"] == "succeeded"
    assert missing_detail["completed_at"] is not None
    assert missing_detail["duration_seconds"] is not None
    # Usage unreported by provider must surface as null, never an estimate.
    assert missing_detail["input_tokens"] is None
    assert missing_detail["output_tokens"] is None
    assert missing_detail["tool_calls"] == []


def test_deleted_association_shows_safe_identity(client: TestClient, db_session: Session) -> None:
    workspace, course, _, _ = _seed_course(db_session)
    run = _course_run(db_session, workspace, course, role="course_architect")
    # Simulate a soft-deleted course: the association can no longer be read back
    # as an active course, so the view must not revive content.
    course.lifecycle_status = "deleted"
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["identity"]["course_deleted"] is True
    assert detail["identity"]["course_title"] is None
    assert detail["role"] == "course_architect"
    assert detail["status"] == "succeeded"


def test_response_excludes_forbidden_fields(client: TestClient, db_session: Session) -> None:
    workspace, course, _, lesson = _seed_course(db_session)
    architect = _course_run(db_session, workspace, course, role="course_architect")
    tutor = _tutor_run(db_session, workspace, course, scope="lesson", lesson=lesson)

    list_body = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs").json()
    detail_architect = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{architect.id}").json()
    detail_tutor = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{tutor.id}").json()

    for payload in [list_body, detail_architect, detail_tutor]:
        keys = _collect_keys(payload)
        leaked = keys & FORBIDDEN_KEYS
        assert not leaked, f"forbidden fields leaked: {leaked}"

    # Tool call projections specifically must omit the persisted input_hash and
    # any tool input, despite the ORM column existing.
    for detail in [detail_architect, detail_tutor]:
        for call in detail["tool_calls"]:
            assert set(call.keys()) == {
                "tool_name",
                "ordinal",
                "status",
                "result_count",
                "latency_ms",
                "error_code",
                "created_at",
            }

    # Provider/model must not be exposed on the generic run summary.
    for payload in [list_body, detail_architect, detail_tutor]:
        assert "provider" not in _collect_keys(payload)
        assert "model" not in _collect_keys(payload)


# ---------------------------------------------------------------------------
# Stage 5 Slice 1A: seven-role, four-owner, unknown fallback, code_language
# ---------------------------------------------------------------------------


def _practice_run(
    db: Session,
    workspace: Workspace,
    course: Course,
    *,
    role: str,
    job_type: str = "generate_set",
    lesson: Lesson | None = None,
    status: str = "succeeded",
    age_seconds: int = 40,
) -> AgentRun:
    """Create a PracticeJob + AgentRun for exercise_author / answer_grader / scientific_solution_grader."""
    job = PracticeJob(
        workspace_id=workspace.id,
        job_type=job_type,
        course_id=course.id,
        lesson_id=lesson.id if lesson else None,
        output_language="zh-CN",
        difficulty="standard",
        item_count=1,
        request_hash="rh-practice",
        status="succeeded",
        idempotency_key=f"key-practice-{role}-{age_seconds}",
    )
    db.add(job)
    db.flush()
    created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    completed = created + timedelta(seconds=3) if status != "running" else None
    run = AgentRun(
        practice_job_id=job.id,
        workspace_id=workspace.id,
        role=role,
        attempt_number=1,
        status=status,
        step_count=1,
        input_tokens=5,
        output_tokens=10,
        created_at=created,
        completed_at=completed,
    )
    db.add(run)
    db.flush()
    db.commit()
    return run


def _code_lab_run(
    db: Session,
    workspace: Workspace,
    *,
    language: str = "python",
    course: Course | None = None,
    lesson: Lesson | None = None,
    role: str = "code_execution",
    status: str = "succeeded",
    age_seconds: int = 30,
) -> AgentRun:
    """Create a CodeLabRun + CodeLabJob + AgentRun for code_execution role."""
    code_run = CodeLabRun(
        workspace_id=workspace.id,
        course_id=course.id if course else None,
        lesson_id=lesson.id if lesson else None,
        language=language,
        source_code="print('hello')",
        stdin="",
        status="succeeded",
    )
    db.add(code_run)
    db.flush()
    job = CodeLabJob(
        workspace_id=workspace.id,
        run_id=code_run.id,
        idempotency_key=f"key-codelab-{language}-{age_seconds}",
        request_hash="rh-codelab",
        status="succeeded",
    )
    db.add(job)
    db.flush()
    created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    completed = created + timedelta(seconds=1) if status != "running" else None
    run = AgentRun(
        code_lab_job_id=job.id,
        workspace_id=workspace.id,
        role=role,
        attempt_number=1,
        status=status,
        step_count=1,
        input_tokens=2,
        output_tokens=4,
        created_at=created,
        completed_at=completed,
    )
    db.add(run)
    db.flush()
    db.commit()
    return run


def test_seven_roles_returned_in_default_list(client: TestClient, db_session: Session) -> None:
    """All seven known roles appear in the default run list."""
    workspace, course, _, lesson = _seed_course(db_session)
    _course_run(db_session, workspace, course, role="course_architect", age_seconds=100)
    _course_run(db_session, workspace, course, role="lesson_writer", lesson=lesson, age_seconds=90)
    _tutor_run(db_session, workspace, course, scope="lesson", lesson=lesson, age_seconds=80)
    _practice_run(db_session, workspace, course, role="exercise_author", lesson=lesson, age_seconds=70)
    _practice_run(db_session, workspace, course, role="answer_grader", lesson=lesson, age_seconds=60)
    _practice_run(db_session, workspace, course, role="scientific_solution_grader", lesson=lesson, age_seconds=50)
    _code_lab_run(db_session, workspace, language="python", course=course, lesson=lesson, age_seconds=40)

    body = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs").json()
    roles = {item["role"] for item in body}
    assert roles == {
        "course_architect", "lesson_writer", "tutor",
        "exercise_author", "answer_grader", "scientific_solution_grader",
        "code_execution",
    }


def test_seven_role_filters_work(client: TestClient, db_session: Session) -> None:
    """Each of the seven known role filter values returns the correct runs."""
    workspace, course, _, lesson = _seed_course(db_session)
    _course_run(db_session, workspace, course, role="course_architect", age_seconds=100)
    _course_run(db_session, workspace, course, role="lesson_writer", lesson=lesson, age_seconds=90)
    _tutor_run(db_session, workspace, course, scope="lesson", lesson=lesson, age_seconds=80)
    _practice_run(db_session, workspace, course, role="exercise_author", lesson=lesson, age_seconds=70)
    _practice_run(db_session, workspace, course, role="answer_grader", lesson=lesson, age_seconds=60)
    _practice_run(db_session, workspace, course, role="scientific_solution_grader", lesson=lesson, age_seconds=50)
    _code_lab_run(db_session, workspace, language="python", age_seconds=40)

    for role in ["course_architect", "lesson_writer", "tutor", "exercise_author",
                 "answer_grader", "scientific_solution_grader", "code_execution"]:
        result = client.get(
            f"/api/v1/workspaces/{workspace.id}/agent-runs",
            params={"role": role},
        ).json()
        assert len(result) >= 1, f"filter role={role} returned no results"
        assert all(item["role"] == role for item in result), f"filter role={role} returned wrong roles"


def test_course_architect_and_lesson_writer_identity(client: TestClient, db_session: Session) -> None:
    """Course generation identity shows kind, job_type, course and lesson."""
    workspace, course, _, lesson = _seed_course(db_session)
    architect = _course_run(db_session, workspace, course, role="course_architect", job_type="course_outline", age_seconds=100)
    writer = _course_run(db_session, workspace, course, role="lesson_writer", job_type="lesson_draft", lesson=lesson, age_seconds=80)

    arch_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{architect.id}").json()
    assert arch_detail["identity"]["kind"] == "course_generation"
    assert arch_detail["identity"]["job_type"] == "course_outline"
    assert arch_detail["identity"]["course_title"] == "Algorithms"
    assert arch_detail["identity"]["course_deleted"] is False

    writer_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{writer.id}").json()
    assert writer_detail["identity"]["kind"] == "course_generation"
    assert writer_detail["identity"]["job_type"] == "lesson_draft"
    assert writer_detail["identity"]["lesson_title"] == "Binary search"


def test_tutor_identity_with_lesson_and_course_scope(client: TestClient, db_session: Session) -> None:
    """Tutor identity shows kind=tutor, scope, course and lesson."""
    workspace, course, _, lesson = _seed_course(db_session)
    lesson_run = _tutor_run(db_session, workspace, course, scope="lesson", lesson=lesson, age_seconds=60)
    course_run = _tutor_run(db_session, workspace, course, scope="course", age_seconds=50)

    lesson_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{lesson_run.id}").json()
    assert lesson_detail["identity"]["kind"] == "tutor"
    assert lesson_detail["identity"]["tutor_scope"] == "lesson"
    assert lesson_detail["identity"]["course_title"] == "Algorithms"
    assert lesson_detail["identity"]["lesson_title"] == "Binary search"

    course_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{course_run.id}").json()
    assert course_detail["identity"]["kind"] == "tutor"
    assert course_detail["identity"]["tutor_scope"] == "course"


def test_practice_generate_identity(client: TestClient, db_session: Session) -> None:
    """Practice generation identity shows kind=practice, job_type, course and lesson."""
    workspace, course, _, lesson = _seed_course(db_session)
    run = _practice_run(db_session, workspace, course, role="exercise_author", job_type="generate_set", lesson=lesson, age_seconds=40)

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["identity"]["kind"] == "practice"
    assert detail["identity"]["job_type"] == "generate_set"
    assert detail["identity"]["course_title"] == "Algorithms"
    assert detail["identity"]["lesson_title"] == "Binary search"
    assert detail["identity"]["course_deleted"] is False


def test_practice_grade_identity_through_attempt_chain(client: TestClient, db_session: Session) -> None:
    """Practice grading identity resolves course/lesson through Attempt -> Item -> Set."""
    workspace, course, version, lesson = _seed_course(db_session)
    # Build the practice chain: Set -> Item -> Attempt
    practice_set = PracticeSet(
        workspace_id=workspace.id, course_id=course.id, course_version_id=version.id,
        lesson_id=lesson.id, lesson_version_id=version.id, output_language="zh-CN",
        difficulty="standard", item_count=1, generation_config={},
    )
    db_session.add(practice_set)
    db_session.flush()
    item = PracticeItem(
        practice_set_id=practice_set.id, workspace_id=workspace.id,
        ordinal=1, item_type="single_choice", stem="q", answer_spec={},
    )
    db_session.add(item)
    db_session.flush()
    attempt = PracticeAttempt(
        practice_item_id=item.id, workspace_id=workspace.id,
        ordinal=1, item_type="single_choice", answer_payload={}, idempotency_key="att-key",
    )
    db_session.add(attempt)
    db_session.flush()
    # Grading job with no direct course_id — resolves through attempt chain
    grade_job = PracticeJob(
        workspace_id=workspace.id, job_type="grade_attempt",
        practice_attempt_id=attempt.id,
        output_language="zh-CN", difficulty="standard", item_count=1,
        request_hash="rh-grade", status="succeeded",
        idempotency_key="key-grade-chain",
    )
    db_session.add(grade_job)
    db_session.flush()
    run = AgentRun(
        practice_job_id=grade_job.id, workspace_id=workspace.id,
        role="answer_grader", attempt_number=1, status="succeeded",
        step_count=1, input_tokens=3, output_tokens=6,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=30),
        completed_at=datetime.now(timezone.utc) - timedelta(seconds=27),
    )
    db_session.add(run)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["identity"]["kind"] == "practice"
    assert detail["identity"]["job_type"] == "grade_attempt"
    assert detail["identity"]["course_title"] == "Algorithms"
    assert detail["identity"]["lesson_title"] == "Binary search"


def test_code_lab_identity_with_course_and_language(client: TestClient, db_session: Session) -> None:
    """Code Lab identity shows kind=code_execution, code_language, and course/lesson."""
    workspace, course, _, lesson = _seed_course(db_session)
    run = _code_lab_run(db_session, workspace, language="python", course=course, lesson=lesson, age_seconds=20)

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["identity"]["kind"] == "code_execution"
    assert detail["identity"]["code_language"] == "python"
    assert detail["identity"]["course_title"] == "Algorithms"
    assert detail["identity"]["lesson_title"] == "Binary search"
    assert detail["identity"]["course_deleted"] is False


def test_code_lab_identity_without_course(client: TestClient, db_session: Session) -> None:
    """Code Lab run without associated course shows identity without course info."""
    workspace, _, _, _ = _seed_course(db_session)
    run = _code_lab_run(db_session, workspace, language="java", age_seconds=15)

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["identity"]["kind"] == "code_execution"
    assert detail["identity"]["code_language"] == "java"
    assert detail["identity"]["course_id"] is None
    assert detail["identity"]["course_title"] is None


def test_code_lab_safe_language_projection(client: TestClient, db_session: Session) -> None:
    """Only python|java|cpp are surfaced; abnormal historical language returns null."""
    workspace, _, _, _ = _seed_course(db_session)

    # Known safe languages
    for lang in ["python", "java", "cpp"]:
        run = _code_lab_run(db_session, workspace, language=lang, age_seconds=10)
        detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
        assert detail["identity"]["code_language"] == lang, f"expected {lang} for safe language"

    # Abnormal historical languages must not be exposed verbatim.
    for index, lang in enumerate(["ruby", "javascript", "go", "rust", "", "Python"]):
        run = _code_lab_run(db_session, workspace, language=lang, age_seconds=index + 1)
        detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
        assert detail["identity"]["code_language"] is None, f"{lang!r} must return null"


def test_unknown_role_read_safely(client: TestClient, db_session: Session) -> None:
    """Unknown historical role can be read and is not changed to a known role."""
    workspace, course, _, _ = _seed_course(db_session)
    # Create a CourseGenerationJob as owner (required by one_owner constraint),
    # but give the AgentRun an unknown role to test safe degradation.
    job = CourseGenerationJob(
        workspace_id=workspace.id, course_id=course.id, course_version_id=None,
        lesson_id=None, job_type="course_outline", output_language="zh-CN",
        status="succeeded", idempotency_key="key-unknown-role",
    )
    db_session.add(job)
    db_session.flush()
    run = AgentRun(
        course_generation_job_id=job.id,
        workspace_id=workspace.id,
        role="future_agent_v2",
        attempt_number=1,
        status="succeeded",
        step_count=0,
        input_tokens=None,
        output_tokens=None,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        completed_at=datetime.now(timezone.utc) - timedelta(seconds=8),
    )
    db_session.add(run)
    db_session.commit()

    body = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs").json()
    matching = [item for item in body if item["id"] == run.id]
    assert len(matching) == 1
    assert matching[0]["role"] == "future_agent_v2"
    # Identity kind is derived from the owner (CourseGenerationJob), not the role.
    # The role string itself is preserved as-is and not rewritten.
    assert matching[0]["identity"]["kind"] == "course_generation"

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["role"] == "future_agent_v2"
    assert detail["identity"]["kind"] == "course_generation"


def test_course_id_filter_covers_code_lab(client: TestClient, db_session: Session) -> None:
    """course_id filter includes Code Lab runs that have an associated course."""
    workspace, course, _, lesson = _seed_course(db_session)
    _course_run(db_session, workspace, course, role="course_architect", age_seconds=100)
    _tutor_run(db_session, workspace, course, scope="lesson", lesson=lesson, age_seconds=80)
    _practice_run(db_session, workspace, course, role="exercise_author", lesson=lesson, age_seconds=60)
    _code_lab_run(db_session, workspace, language="python", course=course, age_seconds=40)
    # Code Lab without course should NOT appear
    _code_lab_run(db_session, workspace, language="java", age_seconds=30)

    by_course = client.get(
        f"/api/v1/workspaces/{workspace.id}/agent-runs",
        params={"course_id": course.id},
    ).json()
    roles = {item["role"] for item in by_course}
    assert "course_architect" in roles
    assert "tutor" in roles
    assert "exercise_author" in roles
    assert "code_execution" in roles
    # The code_lab without course should not appear in course_id filter
    code_lab_runs = [item for item in by_course if item["role"] == "code_execution"]
    assert len(code_lab_runs) == 1


def test_deleted_owner_and_course_degradation(client: TestClient, db_session: Session) -> None:
    """When owner/course is deleted, identity shows course_deleted=True without reviving content."""
    workspace, course, _, lesson = _seed_course(db_session)
    run = _practice_run(db_session, workspace, course, role="exercise_author", lesson=lesson, age_seconds=40)

    # Soft-delete the course
    course.lifecycle_status = "deleted"
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["identity"]["course_deleted"] is True
    assert detail["identity"]["course_title"] is None
    assert detail["identity"]["kind"] == "practice"


def test_code_lab_deleted_course_degradation(client: TestClient, db_session: Session) -> None:
    """Code Lab with deleted course shows course_deleted=True."""
    workspace, course, _, _ = _seed_course(db_session)
    run = _code_lab_run(db_session, workspace, language="python", course=course, age_seconds=20)

    course.lifecycle_status = "deleted"
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["identity"]["kind"] == "code_execution"
    assert detail["identity"]["course_deleted"] is True
    assert detail["identity"]["course_title"] is None


def test_forbidden_keys_cover_code_and_practice_private_fields(client: TestClient, db_session: Session) -> None:
    """Run summary must never leak code execution, practice, or science private fields."""
    workspace, course, _, lesson = _seed_course(db_session)
    architect = _course_run(db_session, workspace, course, role="course_architect", age_seconds=100)
    practice_run = _practice_run(db_session, workspace, course, role="exercise_author", lesson=lesson, age_seconds=60)
    code_run = _code_lab_run(db_session, workspace, language="python", course=course, age_seconds=40)

    list_body = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs").json()
    for run_id in [architect.id, practice_run.id, code_run.id]:
        detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run_id}").json()
        keys = _collect_keys(detail)
        leaked = keys & FORBIDDEN_KEYS
        assert not leaked, f"forbidden fields leaked in run {run_id}: {leaked}"

    # Also check list items
    for item in list_body:
        keys = _collect_keys(item)
        leaked = keys & FORBIDDEN_KEYS
        assert not leaked, f"forbidden fields leaked in list item: {leaked}"


def test_practice_grade_broken_chain_degrades_safely(client: TestClient, db_session: Session) -> None:
    """A grading job with no readable attempt chain must not guess an identity."""
    workspace, _, _, _ = _seed_course(db_session)
    job = PracticeJob(
        workspace_id=workspace.id,
        job_type="grade_attempt",
        output_language="zh-CN",
        difficulty="standard",
        item_count=1,
        request_hash="rh-broken-grade",
        status="failed",
        idempotency_key="key-broken-grade",
    )
    db_session.add(job)
    db_session.flush()
    run = AgentRun(
        practice_job_id=job.id,
        workspace_id=workspace.id,
        role="answer_grader",
        attempt_number=1,
        status="failed",
        step_count=0,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        completed_at=datetime.now(timezone.utc) - timedelta(seconds=8),
    )
    db_session.add(run)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["identity"] == {
        "kind": "practice",
        "job_type": "grade_attempt",
        "course_id": None,
        "course_title": None,
        "course_deleted": True,
        "lesson_id": None,
        "lesson_title": None,
        "tutor_scope": None,
        "code_language": None,
    }


def test_unknown_role_filter_returns_422(client: TestClient, db_session: Session) -> None:
    """Unknown role filter value still returns 422."""
    workspace, _, _, _ = _seed_course(db_session)
    base = f"/api/v1/workspaces/{workspace.id}/agent-runs"
    assert client.get(base, params={"role": "bogus"}).status_code == 422


def test_owner_unreadable_shows_unknown_identity(client: TestClient, db_session: Session) -> None:
    """When the owner object cannot be read (e.g. cross-workspace), identity degrades gracefully."""
    workspace_a, course_a, _, _ = _seed_course(db_session, name="A", slug="a", title="Course A")
    workspace_b, _, _, _ = _seed_course(db_session, name="B", slug="b", title="Course B")
    # Create a job in workspace A
    job = CourseGenerationJob(
        workspace_id=workspace_a.id, course_id=course_a.id, course_version_id=None,
        lesson_id=None, job_type="course_outline", output_language="zh-CN",
        status="succeeded", idempotency_key="key-cross-ws",
    )
    db_session.add(job)
    db_session.flush()
    # Create a run in workspace B that references workspace A's job
    # This violates the workspace boundary but tests the defensive code
    run = AgentRun(
        course_generation_job_id=job.id,
        workspace_id=workspace_b.id,
        role="course_architect",
        attempt_number=1,
        status="succeeded",
        step_count=0,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        completed_at=datetime.now(timezone.utc) - timedelta(seconds=8),
    )
    db_session.add(run)
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{workspace_b.id}/agent-runs/{run.id}").json()
    # The job's workspace_id doesn't match the run's workspace_id, so identity degrades.
    assert detail["identity"] == {
        "kind": "course_generation",
        "job_type": None,
        "course_id": None,
        "course_title": None,
        "course_deleted": True,
        "lesson_id": None,
        "lesson_title": None,
        "tutor_scope": None,
        "code_language": None,
    }
