from __future__ import annotations

import pytest

from app.core.usage.price_overrides import BaseRates, PricingView
from app.core.usage.pricing import ModelPrice, UsageTokens, calculate_cost_from_usage

_CATALOG = {
    "gpt-tiered": ModelPrice(
        4,
        10,
        1,
        priority_input_per_1m=8,
        priority_output_per_1m=20,
        flex_input_per_1m=2,
        flex_output_per_1m=5,
        long_context_threshold_tokens=1000,
        long_context_input_per_1m=8,
        long_context_output_per_1m=15,
    ),
    "gpt-multiplied": ModelPrice(4, 10, 1, priority_multiplier=2),
}
_VIEW = PricingView(
    _CATALOG,
    {
        "gpt-tiered": BaseRates(3, 0, 6),
        "gpt-multiplied": BaseRates(3, 0.5, 6),
        "gpt-override-only": BaseRates(3, 1, 9),
    },
)


def _microdollars(view: PricingView, model: str, tier: str | None, input_tokens: int) -> int:
    resolved = view.resolve(model)
    assert resolved is not None
    cost = calculate_cost_from_usage(
        UsageTokens(input_tokens=input_tokens, output_tokens=100, cached_input_tokens=100),
        resolved[1],
        service_tier=tier,
    )
    assert cost is not None
    return round(cost * 1_000_000)


@pytest.mark.parametrize(
    ("model", "tier", "input_tokens", "expected"),
    [
        # Standard traffic at the threshold (not above it) uses the override triple.
        ("gpt-tiered", None, 1000, 900 * 3 + 100 * 0 + 100 * 6),
        # Above the threshold, catalog long-context rates keep precedence.
        ("gpt-tiered", None, 1001, 901 * 8 + 100 * 8 + 100 * 15),
        # Explicit catalog Priority rates win for both tier spellings.
        ("gpt-tiered", "priority", 1000, 900 * 8 + 100 * 8 + 100 * 20),
        ("gpt-tiered", "fast", 1000, 900 * 8 + 100 * 8 + 100 * 20),
        # Explicit catalog Flex rates win, including the long-context uplift.
        ("gpt-tiered", "flex", 1000, 900 * 2 + 100 * 2 + 100 * 5),
        ("gpt-tiered", "flex", 1001, 901 * 4 + 100 * 4 + 100 * 7.5),
        # A Priority multiplier scales the selected (override) base rates.
        ("gpt-multiplied", None, 1000, 900 * 3 + 100 * 0.5 + 100 * 6),
        ("gpt-multiplied", "priority", 1000, 900 * 6 + 100 * 1 + 100 * 12),
        # Without catalog tier rates an override-only ID always uses its triple.
        ("gpt-override-only", "priority", 1000, 900 * 3 + 100 * 1 + 100 * 9),
        ("gpt-override-only", "flex", 5000, 4900 * 3 + 100 * 1 + 100 * 9),
    ],
)
def test_override_composes_with_catalog_tiers_and_long_context(
    model: str, tier: str | None, input_tokens: int, expected: float
) -> None:
    assert _microdollars(_VIEW, model, tier, input_tokens) == round(expected)


def test_override_keeps_catalog_tier_fields_and_leaves_catalog_untouched() -> None:
    resolved = _VIEW.resolve("GPT-Tiered")
    assert resolved is not None
    model, price = resolved
    assert model == "gpt-tiered"
    assert (price.input_per_1m, price.cached_input_per_1m, price.output_per_1m) == (3, 0, 6)
    assert (price.priority_input_per_1m, price.long_context_threshold_tokens) == (8, 1000)
    assert _microdollars(PricingView(_CATALOG, {}), "gpt-tiered", None, 1000) == 900 * 4 + 100 * 1 + 100 * 10


def test_unknown_minor_ids_stay_missing_and_overrides_are_alias_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.usage import pricing_catalog as catalog

    monkeypatch.setattr(catalog, "_prices", None)
    upstream = catalog.get_active_prices()
    sol = upstream["gpt-5.6-sol"]
    base = PricingView(upstream, {})
    assert base.resolve("gpt-5.6") == ("gpt-5.6-sol", sol)
    # An unknown minor ID is missing, never priced through the legacy gpt-5 family.
    assert base.resolve("gpt-5.99") is None
    view = PricingView(
        upstream,
        {"gpt-5": BaseRates(1, 1, 1), "gpt-5.6": BaseRates(2, 2, 2), "gpt-5.99": BaseRates(3, 0, 9)},
    )
    assert view.resolve("gpt-5.99") == ("gpt-5.99", ModelPrice(3, 9, 0))
    assert view.resolve("gpt-5.99-2026-09-10") is None
    assert view.resolve("gpt-5.98") is None
    # The alias override reprices only the alias ID; its target and dated siblings keep upstream rates.
    assert view.resolve("GPT-5.6") == ("gpt-5.6", BaseRates(2, 2, 2).apply(sol))
    assert view.resolve("gpt-5.6-sol") == ("gpt-5.6-sol", sol)
    assert view.resolve("gpt-5.6-sol-2026-11-01") == base.resolve("gpt-5.6-sol-2026-11-01")
    # Overriding the target likewise leaves the alias on upstream resolution.
    target_only = PricingView(upstream, {"gpt-5.6-sol": BaseRates(4, 0, 8)})
    assert target_only.resolve("gpt-5.6-sol") == ("gpt-5.6-sol", BaseRates(4, 0, 8).apply(sol))
    assert target_only.resolve("gpt-5.6") == ("gpt-5.6-sol", sol)
    assert target_only.resolve("gpt-5.6-terra") == base.resolve("gpt-5.6-terra")
