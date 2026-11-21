"""In-memory pricing views for subscription request accounting."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from types import MappingProxyType

from app.core.usage.pricing import ModelPrice, get_pricing_for_model
from app.core.usage.pricing_catalog import get_active_prices


@dataclass(frozen=True, slots=True)
class BaseRates:
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float

    @classmethod
    def from_price(cls, price: ModelPrice) -> BaseRates:
        cached = price.cached_input_per_1m
        return cls(price.input_per_1m, price.input_per_1m if cached is None else cached, price.output_per_1m)

    def apply(self, catalog_price: ModelPrice | None) -> ModelPrice:
        if catalog_price is None:
            return ModelPrice(self.input_per_1m, self.output_per_1m, self.cached_input_per_1m)
        return replace(
            catalog_price,
            input_per_1m=self.input_per_1m,
            cached_input_per_1m=self.cached_input_per_1m,
            output_per_1m=self.output_per_1m,
        )


@dataclass(frozen=True, slots=True)
class PricingView:
    upstream: Mapping[str, ModelPrice]
    overrides: Mapping[str, BaseRates]
    forwarded_price: tuple[str, ModelPrice | None] | None = None

    def resolve(self, model: str) -> tuple[str, ModelPrice] | None:
        if self.forwarded_price is not None and model.lower() == self.forwarded_price[0]:
            forwarded_model, forwarded_price = self.forwarded_price
            return (forwarded_model, forwarded_price) if forwarded_price is not None else None
        inherited = get_pricing_for_model(model, self.upstream)
        override = self.overrides.get(model.lower())
        if override is None:
            return inherited
        return model.lower(), override.apply(inherited[1] if inherited is not None else None)


_overrides: Mapping[str, BaseRates] = MappingProxyType({})
_request_view: ContextVar[PricingView | None] = ContextVar("request_price_view", default=None)


def install_overrides(overrides: Mapping[str, BaseRates]) -> None:
    global _overrides
    _overrides = MappingProxyType(dict(overrides))


def current_pricing_view() -> PricingView:
    return _request_view.get() or PricingView(get_active_prices(), _overrides)


def bind_pricing_view(view: PricingView | None = None) -> Token[PricingView | None]:
    return _request_view.set(view if view is not None else current_pricing_view())


def reset_pricing_view(token: Token[PricingView | None]) -> None:
    _request_view.reset(token)


def get_subscription_pricing(model: str) -> tuple[str, ModelPrice] | None:
    return current_pricing_view().resolve(model)
