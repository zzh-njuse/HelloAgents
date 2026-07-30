"""Durable recorder for authorized remote tool attempts.

Spec 008 / ADR 006 make the authorization reservation and ``started`` tool
fact one independent transaction. Business rollback cannot erase a request
that was already eligible to leave the process, and concurrent consumers
cannot exceed the authorization budget.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun,
    AgentToolCall,
    JobToolAuthorization,
    TutorTurnToolAuthorization,
)
from learn_platform_api.db.session import SessionLocal


AuthorizationKind = Literal["job", "tutor_turn"]

STATUS_STARTED = "started"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_TIMED_OUT = "timed_out"

TOOL_BUDGET_EXCEEDED = "tool_budget_exceeded"
TOOL_AUTHORIZATION_INVALID = "tool_authorization_invalid"
TOOL_TIMEOUT = "tool_timeout"
UNKNOWN_TOOL_ERROR = "unknown_tool_error"

STABLE_TOOL_ERROR_CODES = frozenset({
    TOOL_BUDGET_EXCEEDED,
    TOOL_AUTHORIZATION_INVALID,
    TOOL_TIMEOUT,
    UNKNOWN_TOOL_ERROR,
    "backend_not_configured",
    "backend_unavailable",
    "capability_unavailable",
    "code_execution_unavailable",
    "empty_result",
    "invalid_tool_result",
    "mcp_connection_failed",
    "non_json_result",
    "protocol_drift",
    "result_too_large",
    "schema_drift",
    "science_tool_unavailable",
    "tool_call_error",
    "tool_not_allowed",
    "tool_not_found",
    "unrecognized_tool_error",
})


def _effective_session_factory(db: Session, override: Any = None) -> Any:
    if override is not None:
        return override
    return getattr(db, "_test_session_factory", SessionLocal)


def _stable_error_code(error_code: str | None) -> str:
    if error_code in STABLE_TOOL_ERROR_CODES:
        return error_code
    return UNKNOWN_TOOL_ERROR


def _course_authorization_matches(
    authorization: JobToolAuthorization,
    *,
    workspace_id: str,
    course_generation_job_id: str,
    capability_id: str,
    max_calls: int,
    server_allowlist: str | None,
    schema_hash_snapshot: str | None,
    protocol_version_snapshot: str | None,
) -> bool:
    return (
        authorization.workspace_id == workspace_id
        and authorization.course_generation_job_id
        == course_generation_job_id
        and authorization.practice_job_id is None
        and authorization.capability_id == capability_id
        and authorization.max_calls == max_calls
        and authorization.server_allowlist == server_allowlist
        and authorization.schema_hash_snapshot == schema_hash_snapshot
        and authorization.protocol_version_snapshot
        == protocol_version_snapshot
    )


def ensure_course_job_tool_authorization(
    db: Session,
    *,
    authorization_id: str,
    workspace_id: str,
    agent_run_id: str,
    course_generation_job_id: str,
    capability_id: str,
    max_calls: int,
    server_allowlist: str | None,
    schema_hash_snapshot: str | None,
    protocol_version_snapshot: str | None,
    _session_factory: Any = None,
) -> None:
    """Persist the minimal Course authorization immediately before first use.

    Course generation discovers capability readiness inside the worker. This
    helper prevents a later business rollback from deleting the authorization
    without committing lesson artifacts or other caller Session state.
    """
    factory = _effective_session_factory(db, _session_factory)
    try:
        with factory() as ind_db:
            run = ind_db.get(AgentRun, agent_run_id)
            if (
                run is None
                or run.workspace_id != workspace_id
                or run.course_generation_job_id != course_generation_job_id
            ):
                raise ValueError(TOOL_AUTHORIZATION_INVALID)
            existing = ind_db.get(JobToolAuthorization, authorization_id)
            if existing is not None:
                if not _course_authorization_matches(
                    existing,
                    workspace_id=workspace_id,
                    course_generation_job_id=course_generation_job_id,
                    capability_id=capability_id,
                    max_calls=max_calls,
                    server_allowlist=server_allowlist,
                    schema_hash_snapshot=schema_hash_snapshot,
                    protocol_version_snapshot=protocol_version_snapshot,
                ):
                    raise ValueError(TOOL_AUTHORIZATION_INVALID)
                return
            ind_db.add(JobToolAuthorization(
                id=authorization_id,
                workspace_id=workspace_id,
                capability_id=capability_id,
                course_generation_job_id=course_generation_job_id,
                max_calls=max_calls,
                used_calls=0,
                server_allowlist=server_allowlist,
                schema_hash_snapshot=schema_hash_snapshot,
                protocol_version_snapshot=protocol_version_snapshot,
            ))
            try:
                ind_db.commit()
            except IntegrityError:
                # Concurrent workers may both observe the authorization as
                # absent. The winner creates it; the loser accepts only the
                # exact same immutable snapshot.
                ind_db.rollback()
                existing = ind_db.get(
                    JobToolAuthorization,
                    authorization_id,
                )
                if existing is None or not _course_authorization_matches(
                    existing,
                    workspace_id=workspace_id,
                    course_generation_job_id=course_generation_job_id,
                    capability_id=capability_id,
                    max_calls=max_calls,
                    server_allowlist=server_allowlist,
                    schema_hash_snapshot=schema_hash_snapshot,
                    protocol_version_snapshot=protocol_version_snapshot,
                ):
                    raise
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError("tool_authorization_persist_failed") from exc


class RemoteToolCallRecorder:
    """Reserve budget and record one authorized outbound tool attempt."""

    def __init__(
        self,
        db: Session,
        *,
        workspace_id: str,
        agent_run_id: str,
        authorization_kind: AuthorizationKind,
        authorization_id: str,
        capability_id: str,
        tool_name: str,
        ordinal: int,
        input_hash: str | None = None,
        _session_factory: Any = None,
    ) -> None:
        if authorization_kind not in {"job", "tutor_turn"}:
            raise ValueError(TOOL_AUTHORIZATION_INVALID)
        if ordinal < 0:
            raise ValueError(TOOL_AUTHORIZATION_INVALID)
        if not tool_name or not tool_name.strip() or len(tool_name) > 100:
            raise ValueError(TOOL_AUTHORIZATION_INVALID)
        if input_hash is not None and len(input_hash) > 64:
            raise ValueError(TOOL_AUTHORIZATION_INVALID)

        self._workspace_id = workspace_id
        self._agent_run_id = agent_run_id
        self._authorization_kind = authorization_kind
        self._authorization_id = authorization_id
        self._capability_id = capability_id
        self._tool_name = tool_name
        self._ordinal = ordinal
        self._input_hash = input_hash
        self._session_factory = _effective_session_factory(db, _session_factory)
        self._call_id: str | None = None
        self._started_perf = 0.0

    def reserve(self) -> int:
        """Atomically consume one call and commit a ``started`` fact.

        Returns the authoritative used-call count after reservation. A failed
        reservation is always reported with a stable ValueError and must stop
        the caller before any remote request is sent.
        """
        try:
            with self._session_factory() as ind_db:
                run = ind_db.get(AgentRun, self._agent_run_id)
                if run is None or run.workspace_id != self._workspace_id:
                    raise ValueError(TOOL_AUTHORIZATION_INVALID)

                if self._authorization_kind == "job":
                    auth = ind_db.get(JobToolAuthorization, self._authorization_id)
                    if (
                        auth is None
                        or auth.workspace_id != self._workspace_id
                        or auth.capability_id != self._capability_id
                        or (
                            auth.course_generation_job_id is not None
                            and run.course_generation_job_id != auth.course_generation_job_id
                        )
                        or (
                            auth.practice_job_id is not None
                            and run.practice_job_id != auth.practice_job_id
                        )
                    ):
                        raise ValueError(TOOL_AUTHORIZATION_INVALID)
                    statement = (
                        update(JobToolAuthorization)
                        .where(
                            JobToolAuthorization.id == self._authorization_id,
                            JobToolAuthorization.workspace_id == self._workspace_id,
                            JobToolAuthorization.capability_id == self._capability_id,
                            JobToolAuthorization.used_calls
                            < JobToolAuthorization.max_calls,
                        )
                        .values(used_calls=JobToolAuthorization.used_calls + 1)
                        .returning(JobToolAuthorization.used_calls)
                    )
                else:
                    auth = ind_db.get(
                        TutorTurnToolAuthorization,
                        self._authorization_id,
                    )
                    if (
                        auth is None
                        or auth.workspace_id != self._workspace_id
                        or auth.capability_id != self._capability_id
                        or run.tutor_turn_id != auth.turn_id
                    ):
                        raise ValueError(TOOL_AUTHORIZATION_INVALID)
                    statement = (
                        update(TutorTurnToolAuthorization)
                        .where(
                            TutorTurnToolAuthorization.id
                            == self._authorization_id,
                            TutorTurnToolAuthorization.workspace_id
                            == self._workspace_id,
                            TutorTurnToolAuthorization.capability_id
                            == self._capability_id,
                            TutorTurnToolAuthorization.used_calls
                            < TutorTurnToolAuthorization.max_calls,
                        )
                        .values(
                            used_calls=TutorTurnToolAuthorization.used_calls + 1
                        )
                        .returning(TutorTurnToolAuthorization.used_calls)
                    )

                used_calls = ind_db.scalar(statement)
                if used_calls is None:
                    raise ValueError(TOOL_BUDGET_EXCEEDED)

                call = AgentToolCall(
                    workspace_id=self._workspace_id,
                    agent_run_id=self._agent_run_id,
                    tool_name=self._tool_name,
                    ordinal=self._ordinal,
                    status=STATUS_STARTED,
                    input_hash=self._input_hash,
                )
                ind_db.add(call)
                ind_db.commit()
                self._call_id = call.id
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError("remote_tool_call_reserve_failed") from exc

        self._started_perf = time.perf_counter()
        return int(used_calls)

    def succeed(self, *, result_count: int | None = None) -> None:
        self._finalize(
            status=STATUS_SUCCEEDED,
            result_count=result_count,
            error_code=None,
        )

    def fail(
        self,
        *,
        error_code: str | None,
        result_count: int | None = None,
    ) -> None:
        self._finalize(
            status=STATUS_FAILED,
            result_count=result_count,
            error_code=_stable_error_code(error_code),
        )

    def timeout(self) -> None:
        self._finalize(
            status=STATUS_TIMED_OUT,
            result_count=None,
            error_code=TOOL_TIMEOUT,
        )

    def _finalize(
        self,
        *,
        status: str,
        result_count: int | None,
        error_code: str | None,
    ) -> None:
        if self._call_id is None:
            raise RuntimeError("remote_tool_call_not_reserved")
        latency_ms = round((time.perf_counter() - self._started_perf) * 1000)
        try:
            with self._session_factory() as ind_db:
                call = ind_db.get(AgentToolCall, self._call_id)
                if call is None:
                    raise RuntimeError("remote_tool_call_finalize_missing")
                call.status = status
                call.result_count = result_count
                call.latency_ms = latency_ms
                call.error_code = error_code
                ind_db.commit()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError("remote_tool_call_finalize_failed") from exc

    @property
    def call_id(self) -> str | None:
        return self._call_id
