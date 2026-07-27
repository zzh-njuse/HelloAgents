from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from learn_platform_api.db.session import get_db
from learn_platform_api.schemas.agent_runs import AgentRunDetail, AgentRunRead
from learn_platform_api.services.agent_runs import get_agent_run, list_agent_runs
from learn_platform_api.services.workspaces import workspace_is_active


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["agent-runs"])

# Stage 5 Slice 1A: seven known roles covering Stage 3 + Stage 4.
RunRole = Literal[
    "course_architect",
    "lesson_writer",
    "tutor",
    "exercise_author",
    "answer_grader",
    "scientific_solution_grader",
    "code_execution",
]
RunStatus = Literal["running", "succeeded", "failed", "canceled"]


@router.get("/agent-runs", response_model=list[AgentRunRead])
def list_agent_runs_endpoint(
    workspace_id: str,
    course_id: str | None = Query(default=None),
    role: RunRole | None = Query(default=None),
    status_filter: RunStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    return list_agent_runs(
        db,
        workspace_id,
        course_id=course_id,
        role=role,
        status=status_filter,
        limit=limit,
    )


@router.get("/agent-runs/{run_id}", response_model=AgentRunDetail)
def get_agent_run_endpoint(
    workspace_id: str,
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    detail = get_agent_run(db, workspace_id, run_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行记录不存在")
    return detail
