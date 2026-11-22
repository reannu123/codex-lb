from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache.invalidation import NAMESPACE_SETTINGS, bump_cache_invalidation_in_transaction
from app.core.usage.price_overrides import BaseRates
from app.db.models import ModelPriceOverride, RequestLog

_RECENT_MODEL_SAMPLE_SIZE = 5_000


class ModelPricesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def overrides(self) -> dict[str, BaseRates]:
        rows = await self._session.scalars(select(ModelPriceOverride))
        return {row.model_id: BaseRates(row.input_per_1m, row.cached_input_per_1m, row.output_per_1m) for row in rows}

    async def recent_subscription_models(self) -> set[str]:
        recent = (
            select(RequestLog.model, RequestLog.model_source_id, RequestLog.model_source_kind, RequestLog.deleted_at)
            .order_by(RequestLog.id.desc())
            .limit(_RECENT_MODEL_SAMPLE_SIZE)
            .subquery()
        )
        result = await self._session.scalars(
            select(recent.c.model)
            .where(
                recent.c.deleted_at.is_(None),
                recent.c.model_source_id.is_(None),
                (recent.c.model_source_kind.is_(None) | (recent.c.model_source_kind == "subscription")),
            )
            .distinct()
        )
        return {model.lower() for model in result}

    async def upsert(self, model_id: str, rates: BaseRates) -> None:
        dialect = self._session.get_bind().dialect.name
        insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}[dialect]
        values = {
            "input_per_1m": rates.input_per_1m,
            "cached_input_per_1m": rates.cached_input_per_1m,
            "output_per_1m": rates.output_per_1m,
        }
        await self._session.execute(
            insert(ModelPriceOverride)
            .values(model_id=model_id, **values)
            .on_conflict_do_update(index_elements=[ModelPriceOverride.model_id], set_=values)
        )
        await bump_cache_invalidation_in_transaction(self._session, NAMESPACE_SETTINGS)
        await self._session.commit()

    async def delete(self, model_id: str) -> bool:
        deleted = await self._session.scalar(
            delete(ModelPriceOverride)
            .where(ModelPriceOverride.model_id == model_id)
            .returning(ModelPriceOverride.model_id)
        )
        if deleted is not None:
            await bump_cache_invalidation_in_transaction(self._session, NAMESPACE_SETTINGS)
        await self._session.commit()
        return deleted is not None
