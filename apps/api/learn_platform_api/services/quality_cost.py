"""Stage 5 Slice 1C — Workspace quality & cost aggregation service (Spec 005 §5).

Read-only aggregation that:
- always scopes to workspace_id and a server-computed time window;
- uses bounded SQL aggregate queries, never loads all ORM rows into Python;
- derives business_type from a shared identity kind precedence (Fix 4);
- only aggregates Provider Calls owned by filtered AgentRuns (RAG/workspace-only
  calls are excluded per Spec 005 §2);
- uses Postgres percentile_cont for deterministic P50/P95 (Fix 1);
- uses database-side cost aggregation with SQL CASE/NUMERIC (Fix 2);
- uses Decimal/ROUND_HALF_UP/8-place precision matching provider_cost.py;
- separates runs_without_provider_calls from unknown-cost calls;
- never modifies any Run, Provider Call or rate snapshot.

Query budget: 7 bounded aggregate queries. No N+1. No per-row Python loops.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import case, column, func, literal_column, select
from sqlalchemy.types import Integer, Numeric
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun,
    ProviderCall,
    ProviderRateSnapshot,
)
from learn_platform_api.services.agent_run_identity import (
    OWNER_KIND_PRECEDENCE,
    BUSINESS_TYPES,
)
from learn_platform_api.services.provider_cost import (
    COST_NUMERIC_SCALE,
    CURRENCY_CNY,
    TOKENS_PER_MILLION,
)


# --- Time windows (Spec 005 §3) ----------------------------------------------

WINDOW_DURATIONS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

VALID_WINDOWS = tuple(WINDOW_DURATIONS.keys())

# Terminal statuses for duration percentile (Spec 005 §5)
TERMINAL_STATUSES = ("succeeded", "failed", "canceled")


# --- Shared identity kind precedence (Fix 4) ---------------------------------
# OWNER_KIND_PRECEDENCE and BUSINESS_TYPES are imported from
# agent_run_identity.py — the single source of truth.
# Both the Python _identity() in agent_runs.py and the SQL CASE here
# must use this precedence. The list order defines the priority: first match wins.


def _business_type_case() -> Any:
    """SQL CASE expression deriving safe identity kind from AgentRun owner FK.

    Uses the same OWNER_KIND_PRECEDENCE as the Python _identity() function.
    The CASE order matches the precedence list; first non-null FK wins.
    """
    whens = [
        (getattr(AgentRun, col).isnot(None), literal_column(f"'{kind}'"))
        for col, kind in OWNER_KIND_PRECEDENCE
    ]
    return case(*whens, else_=literal_column("'unknown'"))


# --- Duration percentile SQL (Fix 1) ----------------------------------------

# Duration in milliseconds computed from created_at/completed_at.
# Uses EXTRACT(EPOCH FROM ...) which is Postgres-specific.

DURATION_MS_EXPR = func.cast(
    func.extract("epoch", AgentRun.completed_at - AgentRun.created_at) * 1000,
    Integer(),
).label("duration_ms")


# --- Main aggregation ---------------------------------------------------------

def get_quality_cost_summary(
    db: Session,
    workspace_id: str,
    *,
    window: str = "24h",
    role: str | None = None,
    status: str | None = None,
    business_type: str | None = None,
) -> dict[str, Any]:
    """Compute the Workspace quality & cost summary (Spec 005 §3/§5).

    Uses bounded SQL aggregate queries. Never loads individual ORM rows
    for aggregation. Returns a dict matching the QualityCostSummary schema.
    """
    # Fix 4: Reject non-Postgres dialects BEFORE any aggregation query.
    dialect_name = db.bind.dialect.name
    if dialect_name != "postgresql":
        raise RuntimeError(
            "quality_cost_summary requires Postgres: "
            "percentile_cont and NUMERIC cost aggregation are Postgres-specific. "
            f"Got dialect={dialect_name!r}."
        )

    now = datetime.now(timezone.utc)
    window_td = WINDOW_DURATIONS[window]
    from_dt = now - window_td

    # --- Build base filter for AgentRuns --------------------------------------
    base_where = [
        AgentRun.workspace_id == workspace_id,
        AgentRun.created_at >= from_dt,
    ]
    if role is not None:
        base_where.append(AgentRun.role == role)
    if status is not None:
        base_where.append(AgentRun.status == status)
    if business_type is not None:
        base_where.append(_business_type_case() == business_type)

    # Subquery of filtered run IDs for Provider Call aggregation
    filtered_run_ids = (
        select(AgentRun.id).where(*base_where)
    )

    # --- Query 1: Run counts by status ----------------------------------------
    run_count_stmt = select(
        func.count().label("total"),
        func.count().filter(AgentRun.status == "started").label("started"),
        func.count().filter(AgentRun.status == "succeeded").label("succeeded"),
        func.count().filter(AgentRun.status == "failed").label("failed"),
        func.count().filter(AgentRun.status == "canceled").label("canceled"),
    ).where(*base_where)

    run_counts = db.execute(run_count_stmt).one()

    # --- Query 2: Duration percentile (Fix 1) --------------------------------
    # Uses Postgres percentile_cont for deterministic continuous interpolation.
    # Results are rounded to integer milliseconds per Spec 005 §5.
    # Empty samples return NULL.
    # SQLite cannot compute percentile_cont or EXTRACT(EPOCH FROM ...);
    # on non-Postgres backends, p50/p95 return None and only sample_count
    # is computed via a simple COUNT.
    duration_where = base_where + [
        AgentRun.status.in_(TERMINAL_STATUSES),
        AgentRun.completed_at.isnot(None),
        AgentRun.completed_at >= AgentRun.created_at,
    ]

    percentile_stmt = select(
        func.count().label("sample_count"),
        func.percentile_cont(0.5).within_group(
            column("duration_ms")
        ).label("p50_raw"),
        func.percentile_cont(0.95).within_group(
            column("duration_ms")
        ).label("p95_raw"),
    ).select_from(
        select(DURATION_MS_EXPR).where(*duration_where).subquery()
    )
    dur_result = db.execute(percentile_stmt).one()
    sample_count = dur_result.sample_count
    p50 = int(round(float(dur_result.p50_raw))) if dur_result.p50_raw is not None else None
    p95 = int(round(float(dur_result.p95_raw))) if dur_result.p95_raw is not None else None

    # --- Query 3: Error code counts ------------------------------------------
    error_stmt = (
        select(
            AgentRun.error_code.label("error_code"),
            func.count().label("count"),
        )
        .where(*base_where)
        .where(AgentRun.error_code.isnot(None))
        .where(AgentRun.error_code != "")
        .group_by(AgentRun.error_code)
        .order_by(func.count().desc(), AgentRun.error_code.asc())
    )
    errors = [
        {"error_code": row.error_code, "count": row.count}
        for row in db.execute(error_stmt).all()
    ]

    # --- Query 4: Provider Call status & token aggregation --------------------
    pc_base_where = [
        ProviderCall.workspace_id == workspace_id,
        ProviderCall.agent_run_id.in_(filtered_run_ids),
    ]

    # 4a: counts by status
    pc_status_stmt = (
        select(
            ProviderCall.status.label("status"),
            func.count().label("count"),
        )
        .where(*pc_base_where)
        .group_by(ProviderCall.status)
    )
    pc_by_status = [
        {"status": row.status, "count": row.count}
        for row in db.execute(pc_status_stmt).all()
    ]
    pc_total = sum(item["count"] for item in pc_by_status)

    # 4b: token sums and usage completeness
    pc_token_stmt = (
        select(
            func.coalesce(func.sum(ProviderCall.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(ProviderCall.output_tokens), 0).label("output_tokens"),
            func.count().filter(
                ProviderCall.input_tokens.isnot(None),
                ProviderCall.output_tokens.isnot(None),
            ).label("usage_complete_count"),
            func.count().filter(
                ProviderCall.input_tokens.is_(None) | ProviderCall.output_tokens.is_(None),
            ).label("usage_unknown_count"),
        )
        .where(*pc_base_where)
    )
    pc_tokens = db.execute(pc_token_stmt).one()

    # --- Query 5: Database-side cost aggregation (Fix 2) ----------------------
    # Uses SQL CASE expressions to classify each call's cost status and compute
    # the known amount sum directly in the database, matching the priority and
    # precision of provider_cost.calculate_cost.
    # Pass Python's ASCII whitespace set explicitly: Postgres btrim() otherwise
    # removes spaces only, while provider_cost._is_blank() uses str.strip().
    blank_chars = " \t\n\r\f\v"
    provider_blank = (
        ProviderCall.provider.is_(None)
        | (func.btrim(ProviderCall.provider, blank_chars) == "")
    )
    model_blank = (
        ProviderCall.model.is_(None)
        | (func.btrim(ProviderCall.model, blank_chars) == "")
    )
    usage_missing = (
        ProviderCall.input_tokens.is_(None) | ProviderCall.output_tokens.is_(None)
    )
    rate_missing = (
        ProviderRateSnapshot.input_rate_per_1m.is_(None) |
        ProviderRateSnapshot.output_rate_per_1m.is_(None)
    )

    quantum = Decimal(1).scaleb(-COST_NUMERIC_SCALE)

    # Per-call cost amount (NUMERIC, only for calculated calls)
    per_call_amount = (
        func.cast(ProviderCall.input_tokens, Numeric)
        * ProviderRateSnapshot.input_rate_per_1m
        / TOKENS_PER_MILLION
        + func.cast(ProviderCall.output_tokens, Numeric)
        * ProviderRateSnapshot.output_rate_per_1m
        / TOKENS_PER_MILLION
    )

    # Classified cost amount: only non-null for calculated calls
    classified_amount = case(
        (provider_blank, literal_column("0")),
        (model_blank, literal_column("0")),
        (usage_missing, literal_column("0")),
        (rate_missing, literal_column("0")),
        else_=per_call_amount,
    )

    # Quantize to 8 decimal places in SQL
    quantized_amount = func.round(
        func.cast(classified_amount, Numeric(16, COST_NUMERIC_SCALE)),
        COST_NUMERIC_SCALE,
    )

    cost_stmt = (
        select(
            func.coalesce(
                func.sum(quantized_amount), literal_column("0")
            ).label("known_amount"),
            func.count().filter(
                ~provider_blank, ~model_blank, ~usage_missing, ~rate_missing
            ).label("calculated_call_count"),
            func.count().filter(
                provider_blank | model_blank | usage_missing | rate_missing
            ).label("unknown_call_count"),
            func.count().filter(provider_blank).label("reason_provider_missing"),
            func.count().filter(~provider_blank, model_blank).label("reason_model_missing"),
            func.count().filter(~provider_blank, ~model_blank, usage_missing).label("reason_usage_missing"),
            func.count().filter(~provider_blank, ~model_blank, ~usage_missing, rate_missing).label("reason_rate_missing"),
        )
        .join(
            ProviderRateSnapshot,
            ProviderCall.provider_rate_snapshot_id == ProviderRateSnapshot.id,
            isouter=True,
        )
        .where(*pc_base_where)
    )
    cost_result = db.execute(cost_stmt).one()

    # Format known_amount as fixed 8-decimal string
    known_amount_dec = cost_result.known_amount
    if known_amount_dec is None:
        known_amount_dec = Decimal("0")
    known_amount_str = format(
        Decimal(str(known_amount_dec)).quantize(quantum, rounding=ROUND_HALF_UP),
        f".{COST_NUMERIC_SCALE}f",
    )

    # Build unknown_by_reason list
    unknown_by_reason: list[dict[str, int]] = []
    if cost_result.reason_provider_missing > 0:
        unknown_by_reason.append({"reason": "provider_missing", "count": cost_result.reason_provider_missing})
    if cost_result.reason_model_missing > 0:
        unknown_by_reason.append({"reason": "model_missing", "count": cost_result.reason_model_missing})
    if cost_result.reason_usage_missing > 0:
        unknown_by_reason.append({"reason": "usage_missing", "count": cost_result.reason_usage_missing})
    if cost_result.reason_rate_missing > 0:
        unknown_by_reason.append({"reason": "rate_missing", "count": cost_result.reason_rate_missing})

    # --- Query 6: runs_without_provider_calls --------------------------------
    pc_exists = (
        select(ProviderCall.id)
        .where(ProviderCall.agent_run_id == AgentRun.id)
        .correlate(AgentRun)
        .exists()
    )
    runs_without_pc_stmt = (
        select(func.count())
        .where(*base_where)
        .where(~pc_exists)
    )
    runs_without_pc = db.execute(runs_without_pc_stmt).scalar() or 0

    # --- Assemble response ----------------------------------------------------
    return {
        "window": window,
        "from": from_dt,
        "to": now,
        "filters": {
            "role": role,
            "status": status,
            "business_type": business_type,
        },
        "runs": {
            "total": run_counts.total,
            "by_status": {
                "started": run_counts.started,
                "succeeded": run_counts.succeeded,
                "failed": run_counts.failed,
                "canceled": run_counts.canceled,
            },
            "duration_ms": {
                "p50": p50,
                "p95": p95,
                "sample_count": sample_count,
            },
            "errors": errors,
        },
        "provider_calls": {
            "total": pc_total,
            "by_status": pc_by_status,
            "input_tokens": pc_tokens.input_tokens,
            "output_tokens": pc_tokens.output_tokens,
            "usage_complete_count": pc_tokens.usage_complete_count,
            "usage_unknown_count": pc_tokens.usage_unknown_count,
        },
        "cost": {
            "currency": CURRENCY_CNY,
            "known_amount": known_amount_str,
            "calculated_call_count": cost_result.calculated_call_count,
            "unknown_call_count": cost_result.unknown_call_count,
            "unknown_by_reason": unknown_by_reason,
            "runs_without_provider_calls": runs_without_pc,
        },
    }
