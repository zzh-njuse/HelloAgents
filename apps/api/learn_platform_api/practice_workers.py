import logging
import socket
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from learn_platform_api.db.models import AgentRun, AgentToolCall, PracticeAttempt, PracticeFeedback, PracticeItem, PracticeJob
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.services.practice_generation import execute_generation, execute_grading
from learn_platform_api.services.practice import cleanup_set
from learn_platform_api.settings import get_settings


logger = logging.getLogger(__name__)

# Slice 5 (Spec 005 §7.1 / ADR 007 §3.6): delivery retry covers transient
# provider/queue/MCP/lease faults only. Structural, reference, budget, cancel
# and source-stale failures are NOT auto-retried.
RETRYABLE_CODES = {
    "provider_unavailable",
    "queue_unavailable",
    "code_execution_unavailable",
    "science_tool_unavailable",
}

ERROR_MESSAGES = {
    "coding_item_not_supported_by_lesson": "当前课节缺少可执行学习目标或代码证据，无法生成合适的编程题。请选择自动选择或普通题。",
    "science_item_not_supported_by_lesson": "当前课节缺少可计算的数学、物理或化学目标与证据，无法生成合适的科学计算题。请选择自动选择或普通题。",
    "source_snapshot_stale": "课程来源已变化，请基于当前资料重新生成",
    "provider_unconfigured": "练习模型尚未配置",
    "provider_unavailable": "练习模型服务暂不可用",
    "insufficient_evidence": "当前资料不足以生成练习",
    "invalid_practice_artifact": "练习结果未通过结构或引用校验",
    # Slice 5 refined coding/science reference codes (Spec 005 §8).
    "coding_contract_invalid": "编程题合同不合法，系统已拒绝发布；请重新生成",
    "coding_reference_compile_failed": "模型生成的编程题参考实现无法编译，系统已拒绝发布；请重新生成",
    "coding_reference_test_failed": "模型生成的编程题参考实现未通过后台测试，系统已拒绝发布；请重新生成",
    "coding_starter_invalid": "编程题初始代码会泄露答案，系统已拒绝发布；请重新生成",
    "scientific_answer_spec_invalid": "科学题答案规格不完整，系统已拒绝发布；请重新生成",
    "scientific_spec_missing": "科学题缺少答案规格，系统已拒绝发布；请重新生成",
    "scientific_reference_unverified": "科学题参考答案未通过验证，系统已拒绝发布；请重新生成",
    # Transient infrastructure (delivery-retryable).
    "code_execution_unavailable": "编程题后台执行服务暂时不可用，请稍后重试",
    "science_tool_unavailable": "科学验证工具暂时不可用，请稍后重试",
    "queue_unavailable": "练习队列暂时不可用",
    # Slice 5 version authority (not retryable): re-generate to get a fresh Job.
    "artifact_contract_unsupported": "该练习任务的 artifact 合同版本不受当前系统支持，请重新生成",
    # Slice 5 staged structure codes (Spec 005 §8).
    "practice_artifact_schema_invalid": "练习结果未通过结构校验，系统已拒绝发布；请重新生成",
    "practice_citation_invalid": "练习结果引用校验失败，系统已拒绝发布；请重新生成",
    "practice_formula_invalid": "练习结果公式校验失败，系统已拒绝发布；请重新生成",
    "practice_duplicate": "练习结果与已有题目重复，系统已拒绝发布；请重新生成",
    # Correction 002 §D: stable codes for repair artifact invalid vs re-validation failure
    "coding_repair_artifact_invalid": "编程题修复结果格式不合法，系统已拒绝；请重新生成",
    "scientific_repair_artifact_invalid": "科学题修复结果格式不合法，系统已拒绝；请重新生成",
    "coding_repair_revalidation_failed": "编程题修复后参考实现仍未通过验证，系统已拒绝；请重新生成",
    "scientific_repair_revalidation_failed": "科学题修复后参考答案仍未通过验证，系统已拒绝；请重新生成",
    # Legacy aliases kept for any in-flight/older rows (still mapped, not retried).
    "coding_reference_validation_failed": "模型生成的编程题参考实现未通过后台测试，系统已拒绝发布；请重新生成",
    "coding_reference_validation_infrastructure_failure": "编程题后台验证服务暂时不可用，请稍后重试",
    "scientific_answer_verification_failed": "科学题参考答案未通过 Wolfram 验证，系统已拒绝发布；请重新生成",
    "invalid_rubric": "评分标准未通过校验",
    "unknown_citation": "引用校验失败",
    "answer_too_large": "简答答案超出长度限制",
    "generation_budget_exceeded": "练习生成达到运行预算，未提交截断结果",
    "grading_budget_exceeded": "评分达到运行预算，未提交结果",
    "practice_budget_exceeded": "练习生成达到受控预算",
    "practice_canceled": "练习任务已取消",
}


def heartbeat_practice_job(job_id: str, worker_id: str, settings) -> bool:
    now = datetime.now(timezone.utc)
    with SessionLocal() as heartbeat_db:
        updated = heartbeat_db.execute(update(PracticeJob).where(PracticeJob.id == job_id, PracticeJob.status == "running", PracticeJob.worker_id == worker_id).values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds))).rowcount
        heartbeat_db.commit()
        return bool(updated)


@contextmanager
def maintain_practice_lease(job_id: str, worker_id: str, settings):
    stopped = threading.Event()
    lost = threading.Event()

    def loop() -> None:
        while not stopped.wait(settings.ingestion_heartbeat_seconds):
            try:
                if not heartbeat_practice_job(job_id, worker_id, settings):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=loop, name=f"practice-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stopped.set()
        thread.join(timeout=5)


def _capture_progress(db, job: PracticeJob) -> tuple[int, list[dict]]:
    """Read progress without flushing the caller's business transaction.

    Before rollback, SQLAlchemy's identity map preserves the in-memory
    ``step_count``. After rollback, independently committed remote-tool facts
    provide a durable lower bound. Callers combine both snapshots.
    """
    with db.no_autoflush:
        run = db.scalar(select(AgentRun).where(AgentRun.practice_job_id == job.id, AgentRun.workspace_id == job.workspace_id, AgentRun.status == "running"))
    if run is None:
        return 0, []
    with db.no_autoflush:
        calls = list(db.scalars(select(AgentToolCall).where(AgentToolCall.agent_run_id == run.id).order_by(AgentToolCall.ordinal)))
    safe_calls = [{
        "workspace_id": call.workspace_id,
        "tool_name": call.tool_name,
        "ordinal": call.ordinal,
        "status": call.status,
        "input_hash": call.input_hash,
        "result_count": call.result_count,
        "latency_ms": call.latency_ms,
        "error_code": call.error_code,
        "created_at": call.created_at,
    } for call in calls]
    durable_step_count = (max(call.ordinal for call in calls) + 1) if calls else 0
    return max(run.step_count or 0, durable_step_count), safe_calls


def _capture_pending_tool_calls(db, job: PracticeJob) -> list[dict]:
    """Snapshot unflushed local-only tool facts before business rollback."""
    run = next((
        value for value in db.identity_map.values()
        if isinstance(value, AgentRun)
        and value.practice_job_id == job.id
        and value.workspace_id == job.workspace_id
        and value.status == "running"
    ), None)
    if run is None:
        return []
    return [{
        "workspace_id": call.workspace_id,
        "tool_name": call.tool_name,
        "ordinal": call.ordinal,
        "status": call.status,
        "input_hash": call.input_hash,
        "result_count": call.result_count,
        "latency_ms": call.latency_ms,
        "error_code": call.error_code,
        "created_at": call.created_at,
    } for call in db.new if (
        isinstance(call, AgentToolCall) and call.agent_run_id == run.id
    )]


def _fail_job(db, job: PracticeJob, code: str, *, retryable: bool, settings, step_count: int = 0, tool_calls: list[dict] | None = None) -> None:
    role = "exercise_author" if job.job_type == "generate_set" else "answer_grader"
    # ADR 004 commits the minimal running owner before the first outbound
    # request. Finalize that same attempt after the business transaction rolls
    # back; creating a second failed row would split ProviderCall facts from the
    # terminal outcome and falsely look like duplicate execution.
    run = db.scalar(
        select(AgentRun)
        .where(
            AgentRun.practice_job_id == job.id,
            AgentRun.workspace_id == job.workspace_id,
            AgentRun.role == role,
            AgentRun.attempt_number == job.attempt_count,
            AgentRun.status == "running",
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        run = AgentRun(
            practice_job_id=job.id,
            workspace_id=job.workspace_id,
            role=role,
            attempt_number=job.attempt_count,
        )
    run.status = "failed"
    run.step_count = step_count
    run.error_code = code
    run.completed_at = datetime.now(timezone.utc)
    db.add(run)
    db.flush()
    for call in tool_calls or []:
        db.add(AgentToolCall(agent_run_id=run.id, **call))
    if retryable and job.attempt_count < settings.ingestion_max_attempts:
        job.status = "retry_wait"
        job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=5)
        # Keep the attempt consistent with the retrying job; it must not keep
        # pretending to be plain "grading" while the job waits to retry.
        if job.job_type == "grade_attempt":
            attempt = db.get(PracticeAttempt, job.practice_attempt_id)
            if attempt is not None and attempt.status not in {"succeeded", "canceled"}:
                attempt.status = "retry_wait"
                attempt.error_code = code
                attempt.error_message = ERROR_MESSAGES.get(code, "评分失败")
    else:
        job.status = "failed"
        job.next_attempt_at = None
        job.completed_at = datetime.now(timezone.utc)
        if job.job_type == "grade_attempt":
            attempt = db.get(PracticeAttempt, job.practice_attempt_id)
            if attempt is not None and attempt.status not in {"succeeded", "canceled"}:
                attempt.status = "failed"
                attempt.error_code = code
                attempt.error_message = ERROR_MESSAGES.get(code, "评分失败")
    job.error_code = code
    job.error_message = ERROR_MESSAGES.get(code, "练习任务失败")
    job.worker_id = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _cancel_job(
    db,
    job: PracticeJob,
    *,
    step_count: int,
    tool_calls: list[dict],
) -> None:
    role = "exercise_author" if job.job_type == "generate_set" else "answer_grader"
    run = db.scalar(
        select(AgentRun)
        .where(
            AgentRun.practice_job_id == job.id,
            AgentRun.workspace_id == job.workspace_id,
            AgentRun.role == role,
            AgentRun.attempt_number == job.attempt_count,
            AgentRun.status == "running",
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    completed = datetime.now(timezone.utc)
    if run is not None:
        run.status = "canceled"
        run.step_count = step_count
        run.error_code = "practice_canceled"
        run.completed_at = completed
        for call in tool_calls:
            db.add(AgentToolCall(agent_run_id=run.id, **call))

    job.status = "canceled"
    job.error_code = "practice_canceled"
    job.error_message = ERROR_MESSAGES["practice_canceled"]
    job.worker_id = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    job.next_attempt_at = None
    job.completed_at = completed
    if job.job_type == "grade_attempt":
        attempt = db.get(PracticeAttempt, job.practice_attempt_id)
        if attempt is not None and attempt.status != "succeeded":
            attempt.status = "canceled"
            attempt.completed_at = completed


def run_practice_job(job_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        job = db.get(PracticeJob, job_id)
        if job is None:
            return
        current = datetime.now(timezone.utc)
        # claim only queued, or retry_wait whose backoff has elapsed.
        due = job.status == "queued" or (job.status == "retry_wait" and job.next_attempt_at is not None and job.next_attempt_at <= current)
        if not due:
            return
        worker_id = f"{socket.gethostname()}:{threading.get_ident()}:{job_id}"
        claimed = db.execute(update(PracticeJob).where(
            PracticeJob.id == job_id,
            (PracticeJob.status == "queued") | ((PracticeJob.status == "retry_wait") & PracticeJob.next_attempt_at.is_not(None) & (PracticeJob.next_attempt_at <= current)),
        ).values(status="running", attempt_count=PracticeJob.attempt_count + 1, worker_id=worker_id, heartbeat_at=current, lease_expires_at=current + timedelta(seconds=settings.ingestion_lease_seconds), next_attempt_at=None, error_code=None, error_message=None)).rowcount
        db.commit()
        if not claimed:
            return
        job = db.get(PracticeJob, job_id)
        try:
            with maintain_practice_lease(job.id, worker_id, settings) as lease_lost:
                if job.job_type == "generate_set":
                    execute_generation(db, settings, job, worker_id=worker_id, lease_lost=lease_lost)
                else:
                    execute_grading(db, settings, job, worker_id=worker_id, lease_lost=lease_lost)
                if lease_lost.is_set():
                    raise ValueError("practice_canceled")
            db.commit()
        except ValueError as exc:
            local_progress, _ = _capture_progress(db, job)
            pending_tool_calls = _capture_pending_tool_calls(db, job)
            db.rollback()
            job = db.get(PracticeJob, job_id)
            if not job or job.worker_id != worker_id:
                return
            durable_progress, durable_tool_calls = _capture_progress(db, job)
            progress = max(local_progress, durable_progress)
            durable_ordinals = {
                call["ordinal"] for call in durable_tool_calls
            }
            tool_calls = [
                call for call in pending_tool_calls
                if call["ordinal"] not in durable_ordinals
            ]
            if job.status == "cancel_requested":
                _cancel_job(
                    db,
                    job,
                    step_count=progress,
                    tool_calls=tool_calls,
                )
                db.commit()
                return
            if job.status != "running":
                return
            code = str(exc)
            _fail_job(db, job, code, retryable=code in RETRYABLE_CODES, settings=settings, step_count=progress, tool_calls=tool_calls)
            db.commit()
        except Exception:
            logger.exception("practice_internal_error job_id=%s", job_id)
            try:
                local_progress, _ = _capture_progress(db, job)
                pending_tool_calls = _capture_pending_tool_calls(db, job)
            except Exception:
                local_progress = 0
                pending_tool_calls = []
            # SQLAlchemy may already have placed the transaction in a failed
            # state (for example after a database constraint violation). Roll
            # back before any ORM read so error handling cannot raise a second
            # PendingRollbackError and leave the job stuck in ``running``.
            db.rollback()
            job = db.get(PracticeJob, job_id)
            if not job or job.worker_id != worker_id:
                return
            try:
                durable_progress, durable_tool_calls = _capture_progress(db, job)
            except Exception:
                durable_progress, durable_tool_calls = 0, []
            progress = max(local_progress, durable_progress)
            durable_ordinals = {
                call["ordinal"] for call in durable_tool_calls
            }
            tool_calls = [
                call for call in pending_tool_calls
                if call["ordinal"] not in durable_ordinals
            ]
            if job.status == "cancel_requested":
                _cancel_job(
                    db,
                    job,
                    step_count=progress,
                    tool_calls=tool_calls,
                )
                db.commit()
                return
            if job.status != "running":
                return
            _fail_job(db, job, "practice_internal_error", retryable=False, settings=settings, step_count=progress, tool_calls=tool_calls)
            db.commit()


def cleanup_practice_set(set_id: str) -> None:
    with SessionLocal() as db:
        cleanup_set(db, set_id)


def heartbeat_learning_job(job_id: str, worker_id: str, settings) -> bool:
    from learn_platform_api.db.models import LearningProjectionJob
    now = datetime.now(timezone.utc)
    with SessionLocal() as heartbeat_db:
        updated = heartbeat_db.execute(update(LearningProjectionJob).where(
            LearningProjectionJob.id == job_id,
            LearningProjectionJob.status == "running",
            LearningProjectionJob.worker_id == worker_id,
        ).values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds))).rowcount
        heartbeat_db.commit()
        return bool(updated)


@contextmanager
def maintain_learning_lease(job_id: str, worker_id: str, settings):
    stopped = threading.Event()
    lost = threading.Event()

    def loop() -> None:
        while not stopped.wait(settings.ingestion_heartbeat_seconds):
            try:
                if not heartbeat_learning_job(job_id, worker_id, settings):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=loop, name=f"learning-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stopped.set()
        thread.join(timeout=5)


def run_learning_recompute(job_id: str) -> None:
    """Claim and run a workspace-wide learning projection recompute.

    Reuses the practice queue; does not call provider. Token usage is null.
    """
    settings = get_settings()
    with SessionLocal() as db:
        from learn_platform_api.db.models import LearningMemoryPolicy, LearningProjectionJob, Workspace
        from learn_platform_api.services.learning_projection import recompute_workspace
        job = db.get(LearningProjectionJob, job_id)
        if job is None or job.status not in {"queued", "retry_wait"}:
            return
        worker_id = f"{socket.gethostname()}:{threading.get_ident()}:{job_id}"
        now = datetime.now(timezone.utc)
        claimed = db.execute(update(LearningProjectionJob).where(
            LearningProjectionJob.id == job_id,
            (LearningProjectionJob.status == "queued") | ((LearningProjectionJob.status == "retry_wait") & LearningProjectionJob.next_attempt_at.is_not(None) & (LearningProjectionJob.next_attempt_at <= now)),
        ).values(status="running", attempt_count=LearningProjectionJob.attempt_count + 1, worker_id=worker_id, heartbeat_at=now, lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds), next_attempt_at=None, error_code=None, error_message=None)).rowcount
        db.commit()
        if not claimed:
            return
        job = db.get(LearningProjectionJob, job_id)
        try:
            with maintain_learning_lease(job_id, worker_id, settings) as lease_lost:
                recompute_workspace(db, job.workspace_id)
                current = datetime.now(timezone.utc)
                db.refresh(job)
                workspace = db.get(Workspace, job.workspace_id)
                policy = db.scalar(select(LearningMemoryPolicy).where(LearningMemoryPolicy.workspace_id == job.workspace_id))
                current_policy_revision = policy.policy_revision if policy is not None else 0
                if (
                    lease_lost.is_set()
                    or job.status != "running"
                    or job.worker_id != worker_id
                    or job.lease_expires_at is None
                    or job.lease_expires_at <= current
                    or workspace is None
                    or workspace.lifecycle_status != "active"
                    or current_policy_revision != job.policy_revision
                ):
                    raise RuntimeError("learning_recompute_authority_lost")
                job.status = "succeeded"
                job.completed_at = current
                job.worker_id = None
                job.heartbeat_at = None
                job.lease_expires_at = None
                db.commit()
        except Exception:
            logger.exception("learning_recompute_failed job_id=%s", job_id)
            db.rollback()
            job = db.get(LearningProjectionJob, job_id)
            if job and job.worker_id == worker_id:
                if job.status == "cancel_requested":
                    job.status = "canceled"
                    job.error_code = None
                    job.error_message = None
                else:
                    job.status = "failed"
                    job.error_code = "recompute_internal_error"
                    job.error_message = "Learning recompute failed"
                job.completed_at = datetime.now(timezone.utc)
                job.worker_id = None
                job.heartbeat_at = None
                job.lease_expires_at = None
                db.commit()
                return
