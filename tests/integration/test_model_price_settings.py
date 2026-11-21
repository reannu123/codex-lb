from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

import app.core.auth.dependencies as dashboard_auth
import app.modules.proxy.service as proxy_module
from app.core.auth.dashboard_access import guest_principal
from app.core.auth.dependencies import validate_dashboard_session
from app.core.cache.invalidation import NAMESPACE_SETTINGS, CacheInvalidationPoller
from app.core.usage.price_overrides import get_subscription_pricing, install_overrides
from app.core.usage.pricing import ModelPrice
from app.core.usage.pricing_catalog import install_prices
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.request_logs.cost_backfill import backfill_missing_costs
from app.modules.settings.model_prices_cache import refresh_model_price_overrides
from tests.integration.test_proxy_responses import _make_auth_json

pytestmark = pytest.mark.integration

_MODEL = "gpt-6.2-sol"
_PRICES = "/api/settings/model-prices"
_SYNTHETIC_RATES = {"inputPer1M": "2", "cachedInputPer1M": "0", "outputPer1M": "8"}


def _price_row(response, model: str = _MODEL) -> dict:
    assert response.status_code == 200, response.text
    return next(row for row in response.json()["models"] if row["modelId"] == model)


def _input_rate(model: str) -> float:
    resolved = get_subscription_pricing(model)
    assert resolved is not None
    return resolved[1].input_per_1m


async def test_model_prices_settings_authorization_validation_and_reload(
    async_client, app_instance, db_setup, monkeypatch
):
    from app.core.usage import pricing_catalog as catalog

    monkeypatch.setattr(catalog, "_prices", None)
    monkeypatch.setattr(catalog, "_price_sources", {})
    async with SessionLocal() as session:
        session.add(RequestLog(request_id="old-model", model=_MODEL, status="success"))
        session.add(
            RequestLog(
                request_id="source-only",
                model="source-only-id",
                status="success",
                model_source_id="test-source",
                model_source_kind="openai_compatible",
            )
        )
        await session.commit()

    assert _price_row(await async_client.get(_PRICES))["source"] == "missing"
    for model, rates in (
        ("source-only-id", _SYNTHETIC_RATES),
        ("gpt-6.2-*", _SYNTHETIC_RATES),
        (_MODEL, {**_SYNTHETIC_RATES, "cachedInputPer1M": False}),
        (_MODEL, {**_SYNTHETIC_RATES, "cachedInputPer1M": "0.1234567"}),
        (_MODEL, {**_SYNTHETIC_RATES, "priorityInputPer1M": 5}),
    ):
        assert (await async_client.put(f"{_PRICES}/{model}", json=rates)).status_code in {400, 422}

    async def validate_guest(request):
        return guest_principal()

    app_instance.dependency_overrides[validate_dashboard_session] = guest_principal
    try:
        scoped = monkeypatch.context()
        with scoped as auth_patch:
            auth_patch.setattr(dashboard_auth, "validate_dashboard_session", validate_guest)
            assert (await async_client.get(_PRICES)).status_code == 200
            assert (await async_client.put(f"{_PRICES}/{_MODEL}", json=_SYNTHETIC_RATES)).status_code == 403
            assert (await async_client.delete(f"{_PRICES}/{_MODEL}")).status_code == 403
    finally:
        del app_instance.dependency_overrides[validate_dashboard_session]

    peer = CacheInvalidationPoller(SessionLocal)
    peer.on_invalidation(NAMESPACE_SETTINGS, refresh_model_price_overrides)
    await peer.prime()
    try:
        row = _price_row(await async_client.put(f"{_PRICES}/{_MODEL.upper()}", json=_SYNTHETIC_RATES))
        assert row["source"] == "local_override"
        assert row["effective"] == {"inputPer1M": 2, "cachedInputPer1M": 0, "outputPer1M": 8}

        install_overrides({})
        await peer._poll_once()
        assert _input_rate(_MODEL) == 2
        install_prices({_MODEL: ModelPrice(4, 10, 1, priority_input_per_1m=8, priority_output_per_1m=20)})
        row = _price_row(await async_client.get(_PRICES))
        assert row["source"] == "local_override"
        assert row["inherited"]["inputPer1M"] == 4
        assert row["hasCatalogTiers"]
        assert _input_rate(f"{_MODEL}-2026-11-01") == 4

        install_overrides({})
        await refresh_model_price_overrides()
        assert _input_rate(_MODEL) == 2
        for _ in range(2):
            row = _price_row(await async_client.delete(f"{_PRICES}/{_MODEL}"))
            assert row["source"] == "live_catalog"
            assert row["effective"]["inputPer1M"] == 4
    finally:
        install_overrides({})


async def test_subscription_route_pins_price_and_preserves_recorded_history(async_client, db_setup, monkeypatch):
    from app.core.usage import pricing_catalog as catalog

    monkeypatch.setattr(catalog, "_prices", None)
    monkeypatch.setattr(catalog, "_price_sources", {})
    imported = await async_client.post(
        "/api/accounts/import",
        files={
            "auth_json": (
                "auth.json",
                json.dumps(_make_auth_json("price-test", "test@example.com")),
                "application/json",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    settings = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert settings.status_code == 200, settings.text
    key = await async_client.post(
        "/api/api-keys",
        json={
            "name": "synthetic-price-limit",
            "limits": [{"limitType": "cost_usd", "limitWindow": "daily", "maxValue": 1_000_000_000}],
        },
    )
    assert key.status_code == 200
    headers = {"Authorization": f"Bearer {key.json()['key']}"}
    entered, release = asyncio.Event(), asyncio.Event()
    counter = 0

    async def upstream(*args, **kwargs) -> AsyncIterator[str]:
        nonlocal counter
        counter += 1
        if counter == 2:
            entered.set()
            await release.wait()
        response = {
            "type": "response.completed",
            "response": {
                "id": f"resp_model_prices_{counter}",
                "object": "response",
                "status": "completed",
                "output": [],
                "usage": {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 100}, "output_tokens": 100},
            },
        }
        yield f"data: {json.dumps(response)}\n\n"

    monkeypatch.setattr(proxy_module, "core_stream_responses", upstream)

    async def request():
        response = await async_client.post(
            "/v1/responses",
            headers=headers,
            json={"model": _MODEL, "instructions": "", "input": "synthetic input", "stream": True},
        )
        assert response.status_code == 200, response.text
        assert "response.completed" in response.text, response.text

    try:
        await request()
        row = _price_row(await async_client.put(f"{_PRICES}/{_MODEL}", json=_SYNTHETIC_RATES))
        assert row["source"] == "local_override"
        pending = asyncio.create_task(request())
        try:
            await asyncio.wait_for(entered.wait(), 10)
            zero = dict.fromkeys(_SYNTHETIC_RATES, "0")
            assert _price_row(await async_client.put(f"{_PRICES}/{_MODEL}", json=zero))["source"] == "local_override"
        finally:
            release.set()
            await pending

        await request()
        small = {**zero, "inputPer1M": "0.0001"}
        await async_client.put(f"{_PRICES}/{_MODEL}", json=small)
        await request()
        assert _price_row(await async_client.delete(f"{_PRICES}/{_MODEL}"))["source"] == "missing"

        async with SessionLocal() as session:
            assert (await backfill_missing_costs(session)).updated == 0
            ledger = (
                await session.scalars(select(ApiKeyUsageReservation).order_by(ApiKeyUsageReservation.created_at))
            ).all()
            assert [row.cost_microdollars for row in ledger] == [0, 2600, 0, 0]
        history = (await async_client.get("/api/request-logs")).json()["requests"]
        by_id = {item["requestId"]: item for item in history}
        first, pinned, zero_cost, tiny = (by_id[f"resp_model_prices_{i}"] for i in range(1, 5))
        assert first["costUsd"] is None and first["costStatus"] == "missing_price"
        assert pinned["costUsd"] == pytest.approx(0.0026)
        assert zero_cost["costUsd"] == 0 and zero_cost["costStatus"] == "priced"
        assert tiny["costUsd"] == pytest.approx(0.00000009)
    finally:
        install_overrides({})


async def test_internal_bridge_route_uses_origin_quote_during_stream(async_client, monkeypatch):
    from fastapi.responses import StreamingResponse

    from app.core.config.settings import get_settings
    from app.core.openai.requests import ResponsesRequest
    from app.modules.proxy import api as proxy_api
    from app.modules.proxy.http_bridge_forwarding import HTTPBridgeForwardContext, build_owner_forward_headers

    payload = ResponsesRequest.model_validate({"model": "gpt-5.4", "instructions": "", "input": "synthetic"})
    origin_price = ModelPrice(2, 8, 0, priority_multiplier=2)
    seen = []

    async def stream_response(*args, **kwargs):
        seen.append(get_subscription_pricing(payload.model))

        async def body():
            seen.append(get_subscription_pricing(payload.model))
            yield "data: synthetic\n\n"

        return StreamingResponse(body(), media_type="text/event-stream")

    monkeypatch.setattr(proxy_api, "_stream_responses", stream_response)
    forwarding = HTTPBridgeForwardContext(
        origin_instance="synthetic-origin",
        target_instance=get_settings().http_responses_session_bridge_instance_id,
        codex_session_affinity=False,
        downstream_turn_state=None,
        original_request_unanchored=True,
        price_quote=(payload.model, origin_price),
    )
    response = await async_client.post(
        "/internal/bridge/responses",
        json=payload.model_dump_for_forwarding(),
        headers=build_owner_forward_headers(headers={}, payload=payload, context=forwarding),
    )
    assert response.status_code == 200, response.text
    assert response.text == "data: synthetic\n\n"
    assert seen == [(payload.model, origin_price), (payload.model, origin_price)]
    assert get_subscription_pricing(payload.model) != (payload.model, origin_price)
