from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator

from app.core.exceptions import DashboardBadRequestError
from app.core.openai.model_registry import get_model_registry
from app.core.usage.price_overrides import BaseRates, PricingView
from app.core.usage.pricing import ModelPrice, get_pricing_for_model
from app.core.usage.pricing_catalog import CatalogPriceSource, get_active_prices, get_catalog_price_source
from app.modules.settings.model_prices_repository import ModelPricesRepository
from app.modules.shared.schemas import DashboardModel

_MODEL_ID = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,255}", re.ASCII)
_RATE = re.compile(r"[0-9]+(?:\.[0-9]{1,6})?", re.ASCII)
type Rate = Annotated[Decimal, Field(ge=0, le=1_000_000, decimal_places=6, allow_inf_nan=False)]


class ModelPriceUpdate(DashboardModel):
    model_config = ConfigDict(extra="forbid")

    input_per_1m: Rate
    cached_input_per_1m: Rate
    output_per_1m: Rate

    @field_validator("input_per_1m", "cached_input_per_1m", "output_per_1m", mode="before")
    @classmethod
    def check_decimal(cls, value: str | int | float) -> Decimal:
        if isinstance(value, str) and len(value) <= 20 and _RATE.fullmatch(value):
            return Decimal(value)
        if type(value) in (int, float):
            return Decimal(str(value))
        raise ValueError("Enter a finite decimal rate with at most six fractional digits")

    def base_rates(self) -> BaseRates:
        return BaseRates(float(self.input_per_1m), float(self.cached_input_per_1m), float(self.output_per_1m))


class ModelRatesResponse(DashboardModel):
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float

    @classmethod
    def from_price(cls, price: ModelPrice) -> ModelRatesResponse:
        rates = BaseRates.from_price(price)
        return cls(
            input_per_1m=rates.input_per_1m,
            cached_input_per_1m=rates.cached_input_per_1m,
            output_per_1m=rates.output_per_1m,
        )


class ModelPriceResponse(DashboardModel):
    model_id: str
    catalog_model_id: str | None
    source: CatalogPriceSource | Literal["local_override", "missing"]
    effective: ModelRatesResponse | None
    inherited: ModelRatesResponse | None
    cached_input_inherits_input: bool
    has_catalog_tiers: bool


class ModelPricesResponse(DashboardModel):
    models: list[ModelPriceResponse]


def normalize_price_model_id(model_id: str) -> str:
    normalized = model_id.lower()
    if not _MODEL_ID.fullmatch(normalized):
        raise DashboardBadRequestError("Enter a literal model ID", code="invalid_price_model_id")
    return normalized


class ModelPricesService:
    def __init__(self, repository: ModelPricesRepository) -> None:
        self._repository = repository

    async def _known_ids(self, overrides: dict[str, BaseRates]) -> set[str]:
        return (
            {model.lower() for model in get_active_prices()}
            | {model.lower() for model in get_model_registry().get_models_with_fallback()}
            | await self._repository.recent_subscription_models()
            | set(overrides)
        )

    async def list_prices(self) -> ModelPricesResponse:
        overrides = await self._repository.overrides()
        model_ids = await self._known_ids(overrides)
        upstream = get_active_prices()
        view = PricingView(upstream, overrides)
        return ModelPricesResponse(
            models=[self._row(model_id, view) for model_id in sorted(model_ids) if _MODEL_ID.fullmatch(model_id)]
        )

    async def save(self, model_id: str, rates: BaseRates) -> None:
        overrides = await self._repository.overrides()
        if model_id not in await self._known_ids(overrides):
            raise DashboardBadRequestError("Unknown subscription model ID", code="unknown_price_model_id")
        await self._repository.upsert(model_id, rates)

    def _row(self, model_id: str, view: PricingView) -> ModelPriceResponse:
        inherited = get_pricing_for_model(model_id, view.upstream)
        resolved = view.resolve(model_id)
        catalog_model_id, underlying = inherited if inherited is not None else (None, None)
        price = resolved[1] if resolved is not None else None
        source: CatalogPriceSource | Literal["local_override", "missing"]
        if model_id in view.overrides:
            source = "local_override"
        elif catalog_model_id is not None:
            source = get_catalog_price_source(catalog_model_id)
        else:
            source = "missing"
        return ModelPriceResponse(
            model_id=model_id,
            catalog_model_id=catalog_model_id,
            source=source,
            effective=ModelRatesResponse.from_price(price) if price is not None else None,
            inherited=ModelRatesResponse.from_price(underlying) if underlying is not None else None,
            cached_input_inherits_input=price is not None and price.cached_input_per_1m is None,
            has_catalog_tiers=underlying is not None
            and any(
                value is not None
                for value in (
                    underlying.priority_input_per_1m,
                    underlying.priority_multiplier,
                    underlying.flex_input_per_1m,
                    underlying.long_context_threshold_tokens,
                )
            ),
        )
