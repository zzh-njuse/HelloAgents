"""Stage 5 Slice 1C — Workspace quality & cost summary API (Spec 005 §3)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from learn_platform_api.db.session import get_db
from learn_platform_api.schemas.quality_cost import QualityCostSummary
from learn_platform_api.services.quality_cost import (
    VALID_WINDOWS,
    get_quality_cost_summary,
)
from learn_platform_api.services.workspaces import workspace_is_active


router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}", tags=["quality-cost"]
)

Window = Literal["24h", "7d", "30d"]
BusinessType = Literal[
    "course_generation", "tutor", "practice", "code_execution", "unknown"
]
RunRole = Literal[
    "course_architect",
    "lesson_writer",
    "tutor",
    "exercise_author",
    "answer_grader",
    "scientific_solution_grader",
    "code_execution",
]
RunStatus = Literal["started", "succeeded", "failed", "canceled"]


# Note: the database AgentRun uses "started" not "running". The API filter
# and response use "started" to match the DB enum. The Web may display
# "进行中" for started status.


@router.get(
    "/quality-cost-summary",
    response_model=QualityCostSummary,
)
def quality_cost_summary_endpoint(
    workspace_id: str,
    window: Window = Query(default="24h"),
    role: RunRole | None = Query(default=None),
    status_filter: RunStatus | None = Query(default=None, alias="status"),
    business_type: BusinessType | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Workspace-level quality & cost summary (Spec 005 §3).

    Returns aggregated run health, provider usage, CNY cost and error
    classification for the given workspace and time window.
    """
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    try:
        return get_quality_cost_summary(
            db,
            workspace_id,
            window=window,
            role=role,
            status=status_filter,
            business_type=business_type,
        )
    except RuntimeError as exc:
        if "requires Postgres" in str(exc):
            raise HTTPException(
                status_code=503,
                detail="quality_cost_requires_postgres",
            ) from exc
        raise
