"""Stage 5 Slice 1B-3 — safe Provider Call read schema (Spec 004 §3).

Explicit Pydantic whitelist that never auto-derives from the ORM model.
Only safe telemetry and identity fields are exposed; sensitive content
(prompt, message, answer, evidence, response, payload, raw error,
HTTP body/header, key, URL, hash, path, rate snapshot ID, or rate
values) is never included.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# --- Owner projection (Spec 004 §3) -------------------------------------------

class ProviderCallOwnerRead(BaseModel):
    """Safe owner projection for a Provider Call.

    ``kind`` is derived from the database owner fact, not from request
    parameters or current business state.
    """

    kind: Literal["agent_run", "rag_answer", "workspace"]
    agent_run_id: str | None = None
    rag_answer_trace_id: str | None = None


# --- Cost projection (Spec 004 §4) --------------------------------------------

class ProviderCallCostRead(BaseModel):
    """Safe CNY cost projection for a Provider Call.

    - ``currency`` is always ``CNY`` (Spec 002 §2).
    - ``status`` is ``calculated`` when all facts are present, ``unknown``
      when any fact is missing.
    - ``amount`` is a fixed 8-decimal-place string when calculated, or
      ``null`` when unknown. Never a float, JSON number, or scientific
      notation.
    - ``unknown_reason`` follows the strict priority from Spec 002 §2:
      provider_missing > model_missing > usage_missing > rate_missing.
    """

    currency: Literal["CNY"] = "CNY"
    status: Literal["calculated", "unknown"]
    amount: str | None = None
    unknown_reason: Literal[
        "provider_missing", "model_missing", "usage_missing", "rate_missing"
    ] | None = None


# --- Full call projection (Spec 004 §3) ----------------------------------------

class ProviderCallRead(BaseModel):
    """Whitelisted projection of a Provider Call.

    Deliberately omits:
    - prompt, message, question, answer, evidence, citation
    - provider raw response, exception body, HTTP body/headers
    - API key, base URL, internal connection URL
    - input hash, uploaded text, file path
    - rate snapshot ID, raw rates, or internal ORM fields
    - RagAnswerTrace question/answer hash or evidence/citation IDs
    """

    id: str
    owner: ProviderCallOwnerRead
    ordinal: int
    phase: str
    provider: str
    model: str
    status: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    cost: ProviderCallCostRead
