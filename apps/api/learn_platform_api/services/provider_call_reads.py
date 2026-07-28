"""Stage 5 Slice 1B-3 — read-only Provider Call service (Spec 004 §5).

Safe list and detail queries that:
- always scope to ProviderCall.workspace_id first;
- load price snapshots in one joined query to avoid N+1;
- project cost via the shared ``calculate_cost`` (never copies the formula);
- never read settings or "current latest price";
- never write back any database field;
- never return sensitive content (prompt, message, answer, evidence, etc.).

Cost projection rules (Spec 004 §4 / Spec 002 §2):
- calculated amount → fixed 8-decimal-place string;
- real zero cost → ``"0.00000000"``;
- unknown amount → ``null``;
- unknown reason follows strict priority: provider > model > usage > rate;
- snapshot missing or unreadable → ``rate_missing``;
- failed/timed_out/canceled status does NOT change calculation rules.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from learn_platform_api.db.models import ProviderCall, ProviderRateSnapshot
from learn_platform_api.services.provider_cost import (
    COST_NUMERIC_SCALE,
    CURRENCY_CNY,
    calculate_cost,
)


# --- Cost projection -----------------------------------------------------------

def _project_cost(call: ProviderCall) -> dict[str, Any]:
    """Project the CNY cost for a single Provider Call.

    Uses the already-loaded ``provider_rate_snapshot`` relationship.
    If the snapshot is missing or unreadable, returns ``rate_missing``.
    Never reads settings or current prices. Never writes back.
    """
    # Extract rate snapshot values if available and readable
    input_rate: Decimal | None = None
    output_rate: Decimal | None = None

    snapshot = call.provider_rate_snapshot  # joined eagerly
    if snapshot is not None:
        try:
            input_rate = snapshot.input_rate_per_1m
            output_rate = snapshot.output_rate_per_1m
        except Exception:
            # Snapshot data is abnormal/unreadable → safe degradation
            input_rate = None
            output_rate = None

    result = calculate_cost(
        provider=call.provider,
        model=call.model,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        input_rate_per_1m=input_rate,
        output_rate_per_1m=output_rate,
    )

    if result.is_unknown:
        # If calculate_cost returned unknown and we had a snapshot but
        # it was unreadable, the reason from calculate_cost might be
        # usage_missing (if tokens are None). Only override to
        # rate_missing when the snapshot itself was the problem.
        # calculate_cost already handles the priority correctly:
        # provider_missing > model_missing > usage_missing > rate_missing.
        # If snapshot was None/unreadable and provider/model/tokens are
        # present, calculate_cost returns rate_missing — correct.
        # If snapshot was None but tokens are also missing, calculate_cost
        # returns usage_missing — also correct (higher priority).
        return {
            "currency": CURRENCY_CNY,
            "status": "unknown",
            "amount": None,
            "unknown_reason": result.unknown_reason,
        }

    # Fixed 8-decimal-place string (Spec 004 §4 / ADR 001 §4.4)
    # str(Decimal) can produce scientific notation like "0E-8" for zero.
    # Format using the Decimal's __format__ with 'f' suffix for fixed-point.
    quantized = result.amount.quantize(Decimal(1).scaleb(-COST_NUMERIC_SCALE))
    amount_str = format(quantized, f".{COST_NUMERIC_SCALE}f")
    return {
        "currency": CURRENCY_CNY,
        "status": "calculated",
        "amount": amount_str,
        "unknown_reason": None,
    }


# --- Owner projection -----------------------------------------------------------

def _project_owner(call: ProviderCall) -> dict[str, Any]:
    """Derive the safe owner projection from the database fact.

    Per Spec 004 §3: owner kind is derived from the DB owner fact,
    not from request parameters or current business state.
    """
    if call.agent_run_id is not None:
        return {
            "kind": "agent_run",
            "agent_run_id": call.agent_run_id,
            "rag_answer_trace_id": None,
        }
    if call.rag_answer_trace_id is not None:
        return {
            "kind": "rag_answer",
            "agent_run_id": None,
            "rag_answer_trace_id": call.rag_answer_trace_id,
        }
    return {
        "kind": "workspace",
        "agent_run_id": None,
        "rag_answer_trace_id": None,
    }


# --- Full call projection -------------------------------------------------------

def _project_call(call: ProviderCall) -> dict[str, Any]:
    """Project a single ProviderCall into the safe whitelist dict."""
    return {
        "id": call.id,
        "owner": _project_owner(call),
        "ordinal": call.ordinal,
        "phase": call.phase,
        "provider": call.provider,
        "model": call.model,
        "status": call.status,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "latency_ms": call.latency_ms,
        "error_code": call.error_code,
        "started_at": call.started_at,
        "completed_at": call.completed_at,
        "cost": _project_cost(call),
    }


# --- List query ----------------------------------------------------------------

def list_provider_calls(
    db: Session,
    workspace_id: str,
    *,
    agent_run_id: str | None = None,
    rag_answer_trace_id: str | None = None,
    status: str | None = None,
    phase: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List Provider Calls for a workspace, with optional filters.

    All queries first scope to ProviderCall.workspace_id (Spec 004 §5).
    Owner/status/phase filters further narrow within that scope.
    Stable sort: started_at DESC, id DESC (Spec 004 §2).
    Price snapshots are loaded via joined eager load to avoid N+1.
    """
    stmt = (
        select(ProviderCall)
        .join(ProviderRateSnapshot, ProviderCall.provider_rate_snapshot_id == ProviderRateSnapshot.id, isouter=True)
        .options(contains_eager(ProviderCall.provider_rate_snapshot))
        .where(ProviderCall.workspace_id == workspace_id)
    )

    if agent_run_id is not None:
        stmt = stmt.where(ProviderCall.agent_run_id == agent_run_id)
    if rag_answer_trace_id is not None:
        stmt = stmt.where(ProviderCall.rag_answer_trace_id == rag_answer_trace_id)
    if status is not None:
        stmt = stmt.where(ProviderCall.status == status)
    if phase is not None:
        stmt = stmt.where(ProviderCall.phase == phase)

    stmt = stmt.order_by(ProviderCall.started_at.desc(), ProviderCall.id.desc()).limit(limit)

    calls = list(db.execute(stmt).unique().scalars().all())
    return [_project_call(call) for call in calls]


# --- Detail query ---------------------------------------------------------------

def get_provider_call(
    db: Session,
    workspace_id: str,
    provider_call_id: str,
) -> dict[str, Any] | None:
    """Read a single Provider Call by workspace + call ID.

    Returns None if the call does not exist, is deleted, or belongs toD
    a different workspace. The caller returns a uniform 404 in all cases.
    """
    stmt = (
        select(ProviderCall)
        .join(ProviderRateSnapshot, ProviderCall.provider_rate_snapshot_id == ProviderRateSnapshot.id, isouter=True)
        .options(contains_eager(ProviderCall.provider_rate_snapshot))
        .where(
            ProviderCall.workspace_id == workspace_id,
            ProviderCall.id == provider_call_id,
        )
    )

    call = db.execute(stmt).unique().scalar_one_or_none()
    if call is None:
        return None
    return _project_call(call)
