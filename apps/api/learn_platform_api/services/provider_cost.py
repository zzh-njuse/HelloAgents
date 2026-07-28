"""Stage 5 Slice 1B-1 — pure CNY provider cost calculator.

This is the single home for the Decimal precision, scale and rounding rules
that govern provider token cost (Spec 002 / ADR 001), plus a pure cost
calculator that has no database side effects. Contract highlights:

- currency is fixed to CNY;
- rates are expressed as CNY per 1,000,000 tokens;
- a cost is produced only when provider, model, both token counts and both
  rates are all present (``0`` tokens is a valid real cost, not "missing");
- otherwise exactly one stable unknown reason is returned, in the strict
  priority ``provider_missing > model_missing > usage_missing > rate_missing``;
- a blank/whitespace-only provider or model counts as missing;
- the derived total cost is never re-persisted onto a Provider Call.

The module imports nothing from the ORM, so it can be unit-tested in
isolation and imported by ``db.models`` for the shared ``Numeric`` precision.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Final

# --- Currency (Spec 002 §2: fixed CNY) --------------------------------------
CURRENCY_CNY: Final[str] = "CNY"

# --- Centralized Decimal precision & scale ----------------------------------
# Rates are CNY per 1,000,000 tokens. 16 digits / 8 places is ample for any
# realistic per-million CNY price while keeping values exact in NUMERIC.
RATE_NUMERIC_PRECISION: Final[int] = 16
RATE_NUMERIC_SCALE: Final[int] = 8

# Computed cost: CNY amount returned to callers. Never persisted on the call
# (ADR 001 §4.6 / packet 4.3), so this only governs the returned Decimal.
COST_NUMERIC_PRECISION: Final[int] = 16
COST_NUMERIC_SCALE: Final[int] = 8

# Rates are "per 1,000,000 tokens" (Spec 002 §2).
TOKENS_PER_MILLION: Final[Decimal] = Decimal(1_000_000)

# Rounding rule applied when quantizing the computed CNY total. Centralized
# here so no caller picks its own rounding mode.
COST_ROUNDING: Final[str] = ROUND_HALF_UP


def cost_quantum() -> Decimal:
    """Smallest representable computed-cost unit (1e-``COST_NUMERIC_SCALE``)."""
    return Decimal(1).scaleb(-COST_NUMERIC_SCALE)


# --- Stable unknown reasons (Spec 002 §2; strict priority order below) -------
UNKNOWN_PROVIDER_MISSING: Final[str] = "provider_missing"
UNKNOWN_MODEL_MISSING: Final[str] = "model_missing"
UNKNOWN_USAGE_MISSING: Final[str] = "usage_missing"
UNKNOWN_RATE_MISSING: Final[str] = "rate_missing"

# Evaluated top-to-bottom by ``calculate_cost``; the first match wins, which
# fixes the documented priority provider > model > usage > rate.
UNKNOWN_REASONS_IN_PRIORITY_ORDER: Final[tuple[str, ...]] = (
    UNKNOWN_PROVIDER_MISSING,
    UNKNOWN_MODEL_MISSING,
    UNKNOWN_USAGE_MISSING,
    UNKNOWN_RATE_MISSING,
)


@dataclass(frozen=True)
class CostResult:
    """Outcome of a cost calculation.

    Exactly one of ``amount`` / ``unknown_reason`` is set:

    - computed: ``amount`` is a non-negative Decimal and ``unknown_reason`` is
      ``None``. A real zero cost (e.g. 0 tokens with rates present) is reported
      here — it is NOT an unknown.
    - unknown: ``amount`` is ``None`` and ``unknown_reason`` is one of the
      stable reason constants.
    """

    amount: Decimal | None
    unknown_reason: str | None

    @property
    def is_unknown(self) -> bool:
        return self.unknown_reason is not None


def _is_blank(value: str | None) -> bool:
    """None or a whitespace-only string counts as missing (packet 4.3)."""
    return value is None or value.strip() == ""


def calculate_cost(
    *,
    provider: str | None,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    input_rate_per_1m: Decimal | None,
    output_rate_per_1m: Decimal | None,
) -> CostResult:
    """Compute a CNY cost from primitive facts, or return a stable unknown reason.

    Pure: no database access and no mutation. Sign integrity of tokens/rates
    is enforced by the Provider Call / rate snapshot CHECK constraints; this
    function reasons only about *presence*, in the priority order fixed by
    Spec 002 §2. Floats must never be passed (ADR 001 §4.4).
    """
    if _is_blank(provider):
        return CostResult(amount=None, unknown_reason=UNKNOWN_PROVIDER_MISSING)
    if _is_blank(model):
        return CostResult(amount=None, unknown_reason=UNKNOWN_MODEL_MISSING)
    # 0 tokens is a valid real fact; only a missing (None) count is "missing".
    if input_tokens is None or output_tokens is None:
        return CostResult(amount=None, unknown_reason=UNKNOWN_USAGE_MISSING)
    if input_rate_per_1m is None or output_rate_per_1m is None:
        return CostResult(amount=None, unknown_reason=UNKNOWN_RATE_MISSING)

    input_cost = Decimal(input_tokens) * input_rate_per_1m / TOKENS_PER_MILLION
    output_cost = Decimal(output_tokens) * output_rate_per_1m / TOKENS_PER_MILLION
    total = (input_cost + output_cost).quantize(cost_quantum(), rounding=COST_ROUNDING)
    return CostResult(amount=total, unknown_reason=None)
