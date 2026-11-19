"""POST /api/accounts/{account_id}/limit-warmup/manual against the real app and database.

Only the upstream Responses stream is mocked; account loading, token freshness,
upstream-route resolution, the atomic attempt claim, request logging, and the
dashboard permission gate all run for real.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.auth.dashboard_access import ADMIN_GRANTS, Permission
from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountLimitWarmup, AccountStatus, RequestLog, UsageHistory
from app.db.session import SessionLocal
from app.modules.limit_warmup import service as limit_warmup_service
from app.modules.settings.repository import SettingsRepository
from tests.integration.test_dashboard_permission_gates import _principal_without, _use_principal

pytestmark = pytest.mark.integration

URL = "/api/accounts/{account_id}/limit-warmup/manual"


async def _seed_account(
    account_id: str,
    *,
    status: AccountStatus = AccountStatus.ACTIVE,
    limit_warmup_enabled: bool = True,
    deleted: bool = False,
) -> None:
    encryptor = TokenEncryptor()
    async with SessionLocal() as session:
        session.add(
            Account(
                id=account_id,
                chatgpt_account_id=f"chatgpt-{account_id}",
                email=f"{account_id}@example.com",
                plan_type="plus",
                status=status,
                access_token_encrypted=encryptor.encrypt(f"access-{account_id}"),
                refresh_token_encrypted=encryptor.encrypt("refresh"),
                id_token_encrypted=encryptor.encrypt("id"),
                last_refresh=utcnow(),
                limit_warmup_enabled=limit_warmup_enabled,
                reset_at=None,
                blocked_at=None,
                delete_requested_at=utcnow() if deleted else None,
            )
        )
        settings = await SettingsRepository(session).get_or_create()
        settings.limit_warmup_model = "gpt-5.1-codex-mini"
        await session.commit()


class _MockUpstream:
    def __init__(self, terminal: str = "response.completed", delay: float = 0.0) -> None:
        self.terminal = terminal
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def stream(self, payload, headers, access_token, chatgpt_account_id, **kwargs):
        self.calls.append(
            {
                "payload": payload.to_payload(),
                "access_token": access_token,
                "chatgpt_account_id": chatgpt_account_id,
                "codex_lb_account_id": kwargs.get("codex_lb_account_id"),
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.terminal == "response.completed":
            yield (
                'data: {"type":"response.completed","response":{"id":"resp_1",'
                '"usage":{"input_tokens":7,"output_tokens":1,"total_tokens":8}}}\n\n'
            )
        else:
            yield (
                'data: {"type":"response.failed","response":{"id":"resp_1",'
                '"error":{"code":"server_error","message":"upstream exploded"}}}\n\n'
            )


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> _MockUpstream:
    mock = _MockUpstream()
    monkeypatch.setattr(limit_warmup_service, "stream_responses", mock.stream)
    return mock


async def _attempts() -> list[AccountLimitWarmup]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(AccountLimitWarmup).order_by(AccountLimitWarmup.id))).all())


async def _warmup_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        stmt = select(RequestLog).where(RequestLog.source == "limit_warmup").order_by(RequestLog.id)
        return list((await session.scalars(stmt)).all())


@pytest.mark.asyncio
async def test_manual_warmup_is_pinned_logged_and_leaves_quota_metadata_alone(
    async_client: AsyncClient, upstream: _MockUpstream
) -> None:
    await _seed_account("acc-target")
    await _seed_account("acc-other")

    response = await async_client.post(URL.format(account_id="acc-target"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accountId"] == "acc-target"
    assert body["status"] == "succeeded"
    assert body["model"] == "gpt-5.1-codex-mini"
    assert body["requestId"].startswith("limit-warmup-")
    # Exactly one upstream request, sent with the selected account's identity.
    (call,) = upstream.calls
    assert call["chatgpt_account_id"] == "chatgpt-acc-target"
    assert call["access_token"] == "access-acc-target"
    assert call["codex_lb_account_id"] == "acc-target"
    assert "max_output_tokens" not in call["payload"]

    (attempt,) = await _attempts()
    assert (attempt.account_id, attempt.window, attempt.status) == ("acc-target", "manual", "succeeded")
    assert attempt.id == body["attemptId"]
    (log,) = await _warmup_logs()
    assert log.account_id == "acc-target"
    assert log.request_id == body["requestId"]
    assert log.request_kind == "warmup"
    assert log.status == "success"

    async with SessionLocal() as session:
        accounts = {account.id: account for account in (await session.scalars(select(Account))).all()}
        usage_rows = await session.scalar(select(func.count()).select_from(UsageHistory))
    for account in accounts.values():
        assert account.status == AccountStatus.ACTIVE
        assert account.reset_at is None
        assert account.blocked_at is None
    assert usage_rows == 0


@pytest.mark.asyncio
async def test_manual_warmup_double_click_returns_conflict(async_client: AsyncClient, upstream: _MockUpstream) -> None:
    await _seed_account("acc-target")

    first = await async_client.post(URL.format(account_id="acc-target"))
    second = await async_client.post(URL.format(account_id="acc-target"))

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "manual_warmup_cooldown"
    assert len(upstream.calls) == 1
    assert len(await _attempts()) == 1


@pytest.mark.asyncio
async def test_concurrent_manual_requests_send_one_upstream_request(
    async_client: AsyncClient, upstream: _MockUpstream
) -> None:
    await _seed_account("acc-target")
    upstream.delay = 0.05

    responses = await asyncio.gather(*(async_client.post(URL.format(account_id="acc-target")) for _ in range(4)))

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 409, 409, 409]
    assert {response.json()["error"]["code"] for response in responses if response.status_code == 409} <= {
        "manual_warmup_cooldown",
        "manual_warmup_in_progress",
    }
    assert len(upstream.calls) == 1
    assert len(await _attempts()) == 1


@pytest.mark.asyncio
async def test_failed_manual_warmup_returns_502_and_can_be_retried(
    async_client: AsyncClient, upstream: _MockUpstream
) -> None:
    await _seed_account("acc-target")
    upstream.terminal = "response.failed"

    failed = await async_client.post(URL.format(account_id="acc-target"))

    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "manual_warmup_failed"
    upstream.terminal = "response.completed"
    retried = await async_client.post(URL.format(account_id="acc-target"))
    assert retried.status_code == 200
    assert [attempt.status for attempt in await _attempts()] == ["failed", "succeeded"]
    assert [log.status for log in await _warmup_logs()] == ["error", "success"]
    assert {log.account_id for log in await _warmup_logs()} == {"acc-target"}


@pytest.mark.asyncio
async def test_manual_warmup_does_not_require_automatic_opt_in(
    async_client: AsyncClient, upstream: _MockUpstream
) -> None:
    await _seed_account("acc-target", limit_warmup_enabled=False)

    response = await async_client.post(URL.format(account_id="acc-target"))

    assert response.status_code == 200
    assert len(upstream.calls) == 1
    async with SessionLocal() as session:
        account = await session.get(Account, "acc-target")
    assert account is not None and account.limit_warmup_enabled is False


@pytest.mark.parametrize("status", [AccountStatus.PAUSED, AccountStatus.RATE_LIMITED, AccountStatus.DEACTIVATED])
@pytest.mark.asyncio
async def test_manual_warmup_rejects_inactive_account(
    async_client: AsyncClient, upstream: _MockUpstream, status: AccountStatus
) -> None:
    await _seed_account("acc-target", status=status)

    response = await async_client.post(URL.format(account_id="acc-target"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "manual_warmup_account_not_active"
    assert upstream.calls == []
    assert await _attempts() == []


@pytest.mark.parametrize("deleted", [False, True], ids=["missing", "pending-deletion"])
@pytest.mark.asyncio
async def test_manual_warmup_unknown_account_is_404(
    async_client: AsyncClient, upstream: _MockUpstream, deleted: bool
) -> None:
    if deleted:
        await _seed_account("acc-target", deleted=True)

    response = await async_client.post(URL.format(account_id="acc-target"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"
    assert upstream.calls == []


@pytest.mark.asyncio
async def test_manual_warmup_requires_authentication(async_client: AsyncClient, upstream: _MockUpstream) -> None:
    await _seed_account("acc-target")
    setup = await async_client.post("/api/dashboard-auth/password/setup", json={"password": "password123"})
    assert setup.status_code == 200
    await async_client.post("/api/dashboard-auth/logout", json={})

    response = await async_client.post(URL.format(account_id="acc-target"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert upstream.calls == []


@pytest.mark.asyncio
async def test_manual_warmup_requires_accounts_write(
    app_instance: FastAPI,
    async_client: AsyncClient,
    upstream: _MockUpstream,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_account("acc-target")
    assert Permission.ACCOUNTS_WRITE in ADMIN_GRANTS
    _use_principal(app_instance, monkeypatch, _principal_without(Permission.ACCOUNTS_WRITE))

    response = await async_client.post(URL.format(account_id="acc-target"))

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "permission_required"
    assert error["param"] == Permission.ACCOUNTS_WRITE.value
    assert upstream.calls == []
    assert await _attempts() == []
