"""Stage 5 Slice 1B-1 — pure CNY provider cost calculator (Spec 002 §2 / ADR 001).

The calculator is a pure function: no database, no settings, no float, no
re-persistence of the derived total. These tests lock:

- the formula ``tokens * rate_per_1m / 1,000,000`` for complete facts;
- that ``0`` tokens is a real zero cost, not "unknown";
- the four stable unknown reasons and their strict priority order;
- the centralized Decimal scale (8 places) and ROUND_HALF_UP rounding rule;
- that blank/whitespace provider or model counts as missing.
"""

from __future__ import annotations

from decimal import Decimal

from learn_platform_api.services.provider_cost import (
    COST_NUMERIC_SCALE,
    UNKNOWN_MODEL_MISSING,
    UNKNOWN_PROVIDER_MISSING,
    UNKNOWN_RATE_MISSING,
    UNKNOWN_REASONS_IN_PRIORITY_ORDER,
    UNKNOWN_USAGE_MISSING,
    calculate_cost,
)


def test_complete_usage_returns_cny_decimal() -> None:
    result = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=1500,
        output_tokens=500,
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=Decimal("120"),
    )
    # 1500*40/1e6 = 0.06 ; 500*120/1e6 = 0.06 ; total = 0.12 CNY.
    assert result.is_unknown is False
    assert result.unknown_reason is None
    assert result.amount == Decimal("0.12")
    assert isinstance(result.amount, Decimal)


def test_zero_tokens_is_real_zero_cost_not_unknown() -> None:
    result = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=0,
        output_tokens=0,
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=Decimal("120"),
    )
    # 0 tokens is a valid real fact — a real zero cost, NOT an unknown.
    assert result.is_unknown is False
    assert result.unknown_reason is None
    assert result.amount is not None
    assert result.amount == Decimal("0")


def test_missing_output_tokens_returns_usage_missing() -> None:
    result = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=100,
        output_tokens=None,
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=Decimal("120"),
    )
    assert result.amount is None
    assert result.unknown_reason == UNKNOWN_USAGE_MISSING


def test_missing_input_tokens_returns_usage_missing() -> None:
    result = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=None,
        output_tokens=100,
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=Decimal("120"),
    )
    assert result.amount is None
    assert result.unknown_reason == UNKNOWN_USAGE_MISSING


def test_missing_rates_return_rate_missing_when_usage_present() -> None:
    # Both rates missing.
    result = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=10,
        output_tokens=20,
        input_rate_per_1m=None,
        output_rate_per_1m=None,
    )
    assert result.amount is None
    assert result.unknown_reason == UNKNOWN_RATE_MISSING

    # Only one rate missing is still rate_missing.
    result_one = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=10,
        output_tokens=20,
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=None,
    )
    assert result_one.amount is None
    assert result_one.unknown_reason == UNKNOWN_RATE_MISSING


def test_blank_provider_returns_provider_missing() -> None:
    for blank in (None, "", "   "):
        result = calculate_cost(
            provider=blank,
            model="claude-fable-5",
            input_tokens=10,
            output_tokens=20,
            input_rate_per_1m=Decimal("40"),
            output_rate_per_1m=Decimal("120"),
        )
        assert result.amount is None, f"provider={blank!r} should be missing"
        assert result.unknown_reason == UNKNOWN_PROVIDER_MISSING


def test_blank_model_returns_model_missing_when_provider_present() -> None:
    for blank in (None, "", "\t "):
        result = calculate_cost(
            provider="anthropic",
            model=blank,
            input_tokens=10,
            output_tokens=20,
            input_rate_per_1m=Decimal("40"),
            output_rate_per_1m=Decimal("120"),
        )
        assert result.amount is None, f"model={blank!r} should be missing"
        assert result.unknown_reason == UNKNOWN_MODEL_MISSING


def test_unknown_reason_priority_provider_before_all_others() -> None:
    # Everything is missing/blank at once: provider_missing wins.
    result = calculate_cost(
        provider=None,
        model=None,
        input_tokens=None,
        output_tokens=None,
        input_rate_per_1m=None,
        output_rate_per_1m=None,
    )
    assert result.unknown_reason == UNKNOWN_PROVIDER_MISSING


def test_unknown_reason_priority_model_before_usage_and_rate() -> None:
    result = calculate_cost(
        provider="anthropic",
        model="",
        input_tokens=None,
        output_tokens=None,
        input_rate_per_1m=None,
        output_rate_per_1m=None,
    )
    assert result.unknown_reason == UNKNOWN_MODEL_MISSING


def test_unknown_reason_priority_usage_before_rate() -> None:
    result = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=None,
        output_tokens=None,
        input_rate_per_1m=None,
        output_rate_per_1m=None,
    )
    assert result.unknown_reason == UNKNOWN_USAGE_MISSING


def test_unknown_reason_priority_chain_is_locked() -> None:
    # The four reasons exist and are returned in exactly the documented order
    # as facts are filled in one by one.
    seen: list[str] = []
    facts: dict[str, object] = {
        "provider": None,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "input_rate_per_1m": None,
        "output_rate_per_1m": None,
    }
    # Calculate once with everything missing first, then fill provider -> model
    # -> both tokens -> both rates. Each stage must surface the next reason in
    # the documented priority order; the final stage computes a real amount.
    steps = [
        {},  # all missing -> provider_missing
        {"provider": "anthropic"},
        {"model": "claude-fable-5"},
        {"input_tokens": 1, "output_tokens": 1},
        {"input_rate_per_1m": Decimal("1"), "output_rate_per_1m": Decimal("1")},
    ]
    for step in steps:
        facts.update(step)
        result = calculate_cost(**facts)  # type: ignore[arg-type]
        if result.unknown_reason is not None:
            seen.append(result.unknown_reason)
    assert seen == list(UNKNOWN_REASONS_IN_PRIORITY_ORDER)


def test_large_token_calculation_is_exact_decimal() -> None:
    result = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=2_000_000,
        output_tokens=1_000_000,
        input_rate_per_1m=Decimal("0.5"),
        output_rate_per_1m=Decimal("1.5"),
    )
    # 2e6*0.5/1e6 = 1.0 ; 1e6*1.5/1e6 = 1.5 ; total = 2.5 CNY (exact).
    assert result.amount == Decimal("2.5")
    assert result.unknown_reason is None


def test_computed_cost_scale_locked_to_eight_decimals() -> None:
    result = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=1500,
        output_tokens=500,
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=Decimal("120"),
    )
    assert result.amount is not None
    # The centralized COST_NUMERIC_SCALE must show through as the exponent.
    assert result.amount.as_tuple().exponent == -COST_NUMERIC_SCALE


def test_rounding_rule_is_half_up() -> None:
    # 5 tokens * 0.001 CNY/1M / 1e6 = 5e-9, exactly halfway between 0 and 1e-8.
    # ROUND_HALF_UP -> 0.00000001 ; ROUND_HALF_EVEN -> 0.00000000.
    result = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=5,
        output_tokens=0,
        input_rate_per_1m=Decimal("0.001"),
        output_rate_per_1m=Decimal("0"),
    )
    assert result.amount == Decimal("0.00000001")
    assert result.unknown_reason is None


def test_real_zero_and_unknown_are_distinguished() -> None:
    zero = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=0,
        output_tokens=0,
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=Decimal("120"),
    )
    unknown = calculate_cost(
        provider="anthropic",
        model="claude-fable-5",
        input_tokens=0,
        output_tokens=None,  # usage incomplete -> unknown, not zero
        input_rate_per_1m=Decimal("40"),
        output_rate_per_1m=Decimal("120"),
    )
    assert zero.is_unknown is False and zero.amount == Decimal("0")
    assert unknown.is_unknown is True and unknown.amount is None
    assert unknown.unknown_reason == UNKNOWN_USAGE_MISSING
