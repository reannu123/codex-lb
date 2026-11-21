from __future__ import annotations

import asyncio

from app.core.usage.price_overrides import install_overrides
from app.db.session import SessionLocal
from app.modules.settings.model_prices_repository import ModelPricesRepository

_refresh_lock = asyncio.Lock()


async def refresh_model_price_overrides() -> None:
    # Serialize the read and install so overlapping refreshes cannot publish
    # an older database snapshot after a newer one.
    async with _refresh_lock, SessionLocal() as session:
        install_overrides(await ModelPricesRepository(session).overrides())
