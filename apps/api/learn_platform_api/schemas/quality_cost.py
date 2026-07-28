"""Stage 5 Slice 1C — Workspace quality & cost summary schema (Spec 005 §3)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QualityCostFilters(BaseModel):
    role: str | None = None
    status: str | None = None
    business_type: str | None = None


class RunDurationMs(BaseModel):
    p50: int | None = None
    p95: int | None = None
    sample_count: int = 0


class RunByStatus(BaseModel):
    started: int = 0
    succeeded: int = 0
    failed: int = 0
    canceled: int = 0


class RunSummary(BaseModel):
    total: int = 0
    by_status: RunByStatus
    duration_ms: RunDurationMs
    errors: list[dict[str, int | str]]  # [{error_code: str, count: int}]


class ProviderCallByStatus(BaseModel):
    status: str
    count: int


class ProviderCallSummary(BaseModel):
    total: int = 0
    by_status: list[ProviderCallByStatus] = []
    input_tokens: int = 0
    output_tokens: int = 0
    usage_complete_count: int = 0
    usage_unknown_count: int = 0


class CostUnknownByReason(BaseModel):
    reason: str
    count: int


class CostSummary(BaseModel):
    currency: Literal["CNY"] = "CNY"
    known_amount: str = "0.00000000"
    calculated_call_count: int = 0
    unknown_call_count: int = 0
    unknown_by_reason: list[CostUnknownByReason] = []
    runs_without_provider_calls: int = 0


class QualityCostSummary(BaseModel):
    window: str
    from_: datetime = Field(alias="from")
    to: datetime
    filters: QualityCostFilters
    runs: RunSummary
    provider_calls: ProviderCallSummary
    cost: CostSummary

    model_config = {"populate_by_name": True}
