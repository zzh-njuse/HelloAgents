from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AgentRunIdentity(BaseModel):
    """Safe, derived business identity for a run.

    Only contains identity metadata (titles, scopes, task kind) that is safe to
    show. Never carries prompts, answers, evidence, draft content or any path.
    """

    # "course_generation" | "tutor" | "practice" | "code_execution" | "unknown"
    kind: Literal["course_generation", "tutor", "practice", "code_execution", "unknown"]
    # Course generation task type, e.g. "course_outline" / "lesson_draft". None for tutor runs.
    job_type: str | None = None
    course_id: str | None = None
    course_title: str | None = None
    # True when the associated Course/TutorSession no longer exists; Web shows "已删除".
    course_deleted: bool = False
    lesson_id: str | None = None
    lesson_title: str | None = None
    # Tutor turn scope ("lesson" / "course"). None for course generation runs.
    tutor_scope: str | None = None
    # Code Lab language: "python" | "java" | "cpp" | null.
    # Abnormal historical values are not surfaced and return null.
    code_language: Literal["python", "java", "cpp"] | None = None


class AgentToolCallRead(BaseModel):
    """Whitelisted projection of an AgentToolCall.

    Deliberately omits input_hash, tool input and any raw payload.
    """

    tool_name: str
    ordinal: int
    status: str
    result_count: int | None
    latency_ms: int | None
    error_code: str | None
    created_at: datetime


class AgentRunRead(BaseModel):
    """Whitelisted list-item projection of an AgentRun.

    Only safe telemetry and identity fields are exposed. Tool calls are not
    loaded for list responses. Provider/model, prompts and sensitive trace
    content are never included; only recorded input/output token counts are.
    """

    id: str
    role: str
    status: str
    attempt_number: int
    step_count: int
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime
    completed_at: datetime | None
    # Derived from created_at/completed_at. Null while the run is still in progress;
    # we never fabricate a duration or infer not-yet-occurred usage.
    duration_seconds: float | None
    error_code: str | None
    identity: AgentRunIdentity


class AgentRunDetail(AgentRunRead):
    """Detail projection that additionally returns ordered tool calls."""

    tool_calls: list[AgentToolCallRead]
