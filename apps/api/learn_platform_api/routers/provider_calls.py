"""Stage 5 Slice 1B-3 — safe Provider Call read API (Spec 004 §2).

Read-only endpoints that project each Provider Call's owner, phase,
status, usage, latency, stable error code and CNY cost. Never exposes
sensitive content (prompt, message, answer, evidence, response, payload,
raw error, HTTP body/header, key, URL, hash, path, rate snapshot ID,
or rate values).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from learn_platform_api.db.session import get_db
from learn_platform_api.schemas.provider_calls import ProviderCallRead
from learn_platform_api.services.provider_call_reads import (
    get_provider_call,
    list_provider_calls,
)
from learn_platform_api.services.workspaces import workspace_is_active


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["provider-calls"])

# Stable low-cardinality enums (Spec 004 §2). Do NOT extend these from
# dynamic database values.
CallStatus = Literal["started", "succeeded", "failed", "timed_out", "canceled"]
CallPhase = Literal["plan", "generation", "answer", "grading", "repair"]


@router.get("/provider-calls", response_model=list[ProviderCallRead])
def list_provider_calls_endpoint(
    workspace_id: str,
    agent_run_id: str | None = Query(default=None),
    rag_answer_trace_id: str | None = Query(default=None),
    status_filter: CallStatus | None = Query(default=None, alias="status"),
    phase: CallPhase | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    """List Provider Calls for a workspace.

    Both owner filters cannot be provided simultaneously (422).
    Cross-workspace owner filters return empty lists without leaking
    whether the owner exists.
    """
    if agent_run_id is not None and rag_answer_trace_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="不能同时提供 agent_run_id 和 rag_answer_trace_id",
        )
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    return list_provider_calls(
        db,
        workspace_id,
        agent_run_id=agent_run_id,
        rag_answer_trace_id=rag_answer_trace_id,
        status=status_filter,
        phase=phase,
        limit=limit,
    )


@router.get("/provider-calls/{provider_call_id}", response_model=ProviderCallRead)
def get_provider_call_endpoint(
    workspace_id: str,
    provider_call_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Read a single Provider Call.

    Returns 404 if the call does not exist, is deleted, or belongs to a
    different workspace. The response is identical in all three cases to
    prevent information leakage.
    """
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    result = get_provider_call(db, workspace_id, provider_call_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider Call 不存在")
    return result
