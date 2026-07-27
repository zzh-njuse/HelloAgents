from sqlalchemy import select
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun,
    AgentToolCall,
    CodeLabJob,
    CodeLabRun,
    Course,
    CourseGenerationJob,
    Lesson,
    PracticeAttempt,
    PracticeItem,
    PracticeJob,
    PracticeSet,
    TutorSession,
    TutorTurn,
)

# Code Lab languages that are safe to surface. Abnormal historical values
# (e.g. "ruby", "go") are not exposed and return null instead.
SAFE_CODE_LANGUAGES = {"python", "java", "cpp"}


def _duration_seconds(run: AgentRun) -> float | None:
    """Duration derived from created_at/completed_at.

    Returns None while the run is still in progress. We never fabricate a
    duration from current time here: the response exposes ``completed_at`` so
    the Web can clearly distinguish an in-progress run via status/time without
    inferring not-yet-occurred usage or cost.
    """
    if run.completed_at is None:
        return None
    return (run.completed_at - run.created_at).total_seconds()


def _identity(db: Session, run: AgentRun) -> dict[str, object]:
    """Derive a safe business identity from the run's associations.

    Never reads prompt, answer, evidence, draft, citation or path content.
    When an associated object is gone, returns a ``course_deleted`` flag so the
    view can show "已删除" without reviving content.
    """
    identity: dict[str, object] = {
        "kind": "unknown",
        "job_type": None,
        "course_id": None,
        "course_title": None,
        "course_deleted": False,
        "lesson_id": None,
        "lesson_title": None,
        "tutor_scope": None,
        "code_language": None,
    }

    if run.course_generation_job_id is not None:
        identity["kind"] = "course_generation"
        job = db.get(CourseGenerationJob, run.course_generation_job_id)
        if job is None or job.workspace_id != run.workspace_id:
            identity["course_deleted"] = True
            return identity
        identity["job_type"] = job.job_type
        identity["course_id"] = job.course_id
        course = db.get(Course, job.course_id)
        # Only surface identity titles while the association is still readable and
        # active. A soft-deleted or gone course is reported as "已删除" without
        # reviving its content.
        if (
            course is not None
            and course.workspace_id == run.workspace_id
            and course.lifecycle_status == "active"
        ):
            identity["course_title"] = course.title
            if job.lesson_id:
                identity["lesson_id"] = job.lesson_id
                lesson = db.get(Lesson, job.lesson_id)
                if lesson is not None and lesson.workspace_id == run.workspace_id:
                    identity["lesson_title"] = lesson.title
        else:
            identity["course_deleted"] = True
        return identity

    if run.tutor_turn_id is not None:
        identity["kind"] = "tutor"
        turn = db.get(TutorTurn, run.tutor_turn_id)
        if turn is None or turn.workspace_id != run.workspace_id:
            identity["course_deleted"] = True
            return identity
        identity["tutor_scope"] = turn.scope
        session = db.get(TutorSession, turn.session_id)
        if (
            session is not None
            and session.workspace_id == run.workspace_id
            and session.status == "active"
            and session.deleted_at is None
        ):
            course = db.get(Course, session.course_id)
            if (
                course is not None
                and course.workspace_id == run.workspace_id
                and course.lifecycle_status == "active"
            ):
                identity["course_id"] = course.id
                identity["course_title"] = course.title
                if turn.lesson_id:
                    identity["lesson_id"] = turn.lesson_id
                    lesson = db.get(Lesson, turn.lesson_id)
                    if lesson is not None and lesson.workspace_id == run.workspace_id:
                        identity["lesson_title"] = lesson.title
            else:
                identity["course_deleted"] = True
        else:
            identity["course_deleted"] = True
        return identity

    if run.practice_job_id is not None:
        identity["kind"] = "practice"
        job = db.get(PracticeJob, run.practice_job_id)
        if job is None or job.workspace_id != run.workspace_id:
            identity["course_deleted"] = True
            return identity
        identity["job_type"] = job.job_type
        course_id = job.course_id
        lesson_id = job.lesson_id
        if course_id is None and job.practice_attempt_id:
            # Grading jobs resolve their course/lesson through the attempt chain.
            attempt = db.get(PracticeAttempt, job.practice_attempt_id)
            item = db.get(PracticeItem, attempt.practice_item_id) if attempt else None
            practice_set = db.get(PracticeSet, item.practice_set_id) if item else None
            if practice_set and practice_set.workspace_id == run.workspace_id:
                course_id = practice_set.course_id
                lesson_id = practice_set.lesson_id
        course = db.get(Course, course_id) if course_id else None
        if (
            course is not None
            and course.workspace_id == run.workspace_id
            and course.lifecycle_status == "active"
        ):
            identity["course_id"] = course.id
            identity["course_title"] = course.title
            if lesson_id:
                identity["lesson_id"] = lesson_id
                lesson = db.get(Lesson, lesson_id)
                if lesson is not None and lesson.workspace_id == run.workspace_id:
                    identity["lesson_title"] = lesson.title
        else:
            identity["course_deleted"] = True
        return identity

    if run.code_lab_job_id is not None:
        identity["kind"] = "code_execution"
        job = db.get(CodeLabJob, run.code_lab_job_id)
        if job is None or job.workspace_id != run.workspace_id:
            identity["course_deleted"] = True
            return identity
        # Read the CodeLabRun for language and optional course/lesson.
        code_run = db.get(CodeLabRun, job.run_id)
        if (
            code_run is not None
            and code_run.workspace_id == run.workspace_id
            and code_run.deleted_at is None
        ):
            # Only surface known-safe languages. Abnormal historical values
            # return null rather than being exposed verbatim.
            if code_run.language in SAFE_CODE_LANGUAGES:
                identity["code_language"] = code_run.language
            # Course/Lesson are optional on CodeLabRun.
            if code_run.course_id:
                course = db.get(Course, code_run.course_id)
                if (
                    course is not None
                    and course.workspace_id == run.workspace_id
                    and course.lifecycle_status == "active"
                ):
                    identity["course_id"] = course.id
                    identity["course_title"] = course.title
                else:
                    identity["course_deleted"] = True
            if code_run.lesson_id and not identity["course_deleted"]:
                lesson = db.get(Lesson, code_run.lesson_id)
                if lesson is not None and lesson.workspace_id == run.workspace_id:
                    identity["lesson_id"] = lesson.id
                    identity["lesson_title"] = lesson.title
        else:
            identity["course_deleted"] = True
        return identity

    # No association recorded: nothing identifiable, but still safe to surface.
    identity["course_deleted"] = True
    return identity


def _run_to_dict(db: Session, run: AgentRun) -> dict[str, object]:
    return {
        "id": run.id,
        "role": run.role,
        "status": run.status,
        "attempt_number": run.attempt_number,
        "step_count": run.step_count,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "duration_seconds": _duration_seconds(run),
        "error_code": run.error_code,
        "identity": _identity(db, run),
    }


def list_agent_runs(
    db: Session,
    workspace_id: str,
    *,
    course_id: str | None = None,
    role: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, object]]:
    statement = select(AgentRun).where(AgentRun.workspace_id == workspace_id)
    if course_id is not None:
        # Course-scoped filter: runs whose CourseGenerationJob or TutorTurn/TutorSession
        # belongs to this course. Kept as an explicit OR so unknown course_ids simply
        # match nothing rather than leaking cross-workspace runs.
        course_jobs = select(CourseGenerationJob.id).where(
            CourseGenerationJob.workspace_id == workspace_id,
            CourseGenerationJob.course_id == course_id,
        )
        tutor_turns = (
            select(TutorTurn.id)
            .join(TutorSession, TutorTurn.session_id == TutorSession.id)
            .where(
                TutorTurn.workspace_id == workspace_id,
                TutorSession.workspace_id == workspace_id,
                TutorSession.course_id == course_id,
            )
        )
        # Practice generate jobs carry course_id directly; grading jobs resolve
        # through attempt -> item -> set -> course.
        practice_generate = select(PracticeJob.id).where(
            PracticeJob.workspace_id == workspace_id,
            PracticeJob.course_id == course_id,
        )
        practice_grade_sets = select(PracticeSet.id).where(
            PracticeSet.workspace_id == workspace_id, PracticeSet.course_id == course_id
        )
        practice_grade_items = select(PracticeItem.id).where(
            PracticeItem.workspace_id == workspace_id,
            PracticeItem.practice_set_id.in_(practice_grade_sets),
        )
        practice_grade_attempts = select(PracticeAttempt.id).where(
            PracticeAttempt.workspace_id == workspace_id,
            PracticeAttempt.practice_item_id.in_(practice_grade_items),
        )
        practice_grade_jobs = select(PracticeJob.id).where(
            PracticeJob.workspace_id == workspace_id,
            PracticeJob.practice_attempt_id.in_(practice_grade_attempts)
        )
        # Code Lab runs with an associated course_id on the CodeLabRun.
        code_lab_runs_with_course = select(CodeLabRun.id).where(
            CodeLabRun.workspace_id == workspace_id,
            CodeLabRun.course_id == course_id,
        )
        code_lab_jobs_with_course = select(CodeLabJob.id).where(
            CodeLabJob.workspace_id == workspace_id,
            CodeLabJob.run_id.in_(code_lab_runs_with_course),
        )
        statement = statement.where(
            AgentRun.course_generation_job_id.in_(course_jobs)
            | AgentRun.tutor_turn_id.in_(tutor_turns)
            | AgentRun.practice_job_id.in_(practice_generate)
            | AgentRun.practice_job_id.in_(practice_grade_jobs)
            | AgentRun.code_lab_job_id.in_(code_lab_jobs_with_course)
        )
    if role is not None:
        statement = statement.where(AgentRun.role == role)
    if status is not None:
        statement = statement.where(AgentRun.status == status)
    statement = statement.order_by(AgentRun.created_at.desc()).limit(limit)
    runs = list(db.execute(statement).scalars().all())
    return [_run_to_dict(db, run) for run in runs]


def get_agent_run(db: Session, workspace_id: str, run_id: str) -> dict[str, object] | None:
    run = db.scalar(
        select(AgentRun).where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.id == run_id,
        )
    )
    if run is None:
        return None
    detail = _run_to_dict(db, run)
    tool_calls = list(
        db.execute(
            select(AgentToolCall)
            .where(
                AgentToolCall.agent_run_id == run.id,
                AgentToolCall.workspace_id == workspace_id,
            )
            .order_by(AgentToolCall.ordinal.asc(), AgentToolCall.created_at.asc())
        ).scalars().all()
    )
    detail["tool_calls"] = [
        {
            "tool_name": call.tool_name,
            "ordinal": call.ordinal,
            "status": call.status,
            "result_count": call.result_count,
            "latency_ms": call.latency_ms,
            "error_code": call.error_code,
            "created_at": call.created_at,
        }
        for call in tool_calls
    ]
    return detail
