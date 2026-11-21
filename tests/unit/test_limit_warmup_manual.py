"""Manual ("Warm up now") limit warm-up with a mocked upstream sender."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from app.core.openai.requests import ResponsesRequest
from app.db.models import Account, AccountStatus
from app.modules.limit_warmup import service as limit_warmup_service
from app.modules.limit_warmup.service import (
    LimitWarmupSendResult,
    LimitWarmupService,
    ManualWarmupUnavailableError,
    StreamingLimitWarmupSender,
)
from tests.unit.test_limit_warmup import (
    FakeRequestLogsRepo,
    FakeSender,
    FakeWarmupRepo,
    _account,
    _settings,
    _WarmupAccountsRepo,
)

pytestmark = pytest.mark.unit


def _at(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    current = [1_800_000_000]
    monkeypatch.setattr(limit_warmup_service, "utcnow", lambda: _at(current[0]))
    return current


def _service(sender: object, repo: FakeWarmupRepo | None = None, logs: FakeRequestLogsRepo | None = None):
    return LimitWarmupService(repo or FakeWarmupRepo(), logs or FakeRequestLogsRepo(), sender=cast(Any, sender))


@pytest.mark.asyncio
async def test_manual_warmup_sends_once_and_logs_against_the_selected_account(clock: list[int]) -> None:
    repo, logs, sender = FakeWarmupRepo(), FakeRequestLogsRepo(), FakeSender()
    account = _account("acc_selected")

    result = await _service(sender, repo, logs).run_manual_warmup(account=account, settings=_settings())

    assert result.succeeded is True
    assert sender.calls == [("acc_selected", "gpt-5.1-codex-mini")]
    assert result.attempt.window == "manual"
    assert result.attempt.status == "succeeded"
    assert result.request_id == "warmup-1"
    (log,) = logs.logs
    assert log["account_id"] == "acc_selected"
    assert log["request_id"] == "warmup-1"
    assert log["source"] == "limit_warmup"
    assert log["request_kind"] == "warmup"


@pytest.mark.asyncio
async def test_manual_double_click_is_rejected_by_the_rolling_cooldown(clock: list[int]) -> None:
    repo, sender = FakeWarmupRepo(), FakeSender()
    service = _service(sender, repo)
    account = _account()
    # One second before a 5-minute UTC boundary: fixed buckets would split
    # these two clicks into separate buckets and send twice.
    clock[0] = 1_800_000_299 - 1_800_000_299 % 300 + 299

    await service.run_manual_warmup(account=account, settings=_settings())
    clock[0] += 2
    with pytest.raises(ManualWarmupUnavailableError) as excinfo:
        await service.run_manual_warmup(account=account, settings=_settings())

    assert excinfo.value.code == "manual_warmup_cooldown"
    assert len(sender.calls) == 1
    assert len(repo.rows) == 1


@pytest.mark.asyncio
async def test_manual_cooldown_is_rolling_five_minutes(clock: list[int]) -> None:
    sender = FakeSender()
    service = _service(sender)
    account = _account()
    start = clock[0]

    await service.run_manual_warmup(account=account, settings=_settings())
    clock[0] = start + 299
    with pytest.raises(ManualWarmupUnavailableError):
        await service.run_manual_warmup(account=account, settings=_settings())
    clock[0] = start + 300
    second = await service.run_manual_warmup(account=account, settings=_settings())

    assert second.succeeded is True
    assert len(sender.calls) == 2


@pytest.mark.asyncio
async def test_concurrent_manual_requests_send_one_upstream_request(clock: list[int]) -> None:
    repo = FakeWarmupRepo()
    release = asyncio.Event()

    class SlowSender(FakeSender):
        async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
            await release.wait()
            return await super().send(account, model=model, prompt=prompt)

    sender = SlowSender()
    account = _account()

    async def click() -> str:
        try:
            await _service(sender, repo).run_manual_warmup(account=account, settings=_settings())
        except ManualWarmupUnavailableError as exc:
            return exc.code
        return "sent"

    tasks = [asyncio.create_task(click()) for _ in range(5)]
    await asyncio.sleep(0)
    release.set()
    outcomes = await asyncio.gather(*tasks)

    assert sorted(outcomes).count("sent") == 1
    assert set(outcomes) - {"sent"} <= {"manual_warmup_cooldown", "manual_warmup_in_progress"}
    assert len(sender.calls) == 1
    assert len(repo.rows) == 1


@pytest.mark.asyncio
async def test_failed_manual_attempt_can_be_retried_immediately(clock: list[int]) -> None:
    repo, logs = FakeWarmupRepo(), FakeRequestLogsRepo()
    failing = FakeSender(success=False, error_code="usage_limit_reached")
    account = _account()

    failed = await _service(failing, repo, logs).run_manual_warmup(account=account, settings=_settings())
    clock[0] += 5
    retried = await _service(FakeSender(), repo, logs).run_manual_warmup(account=account, settings=_settings())

    assert failed.succeeded is False
    assert failed.attempt.status == "failed"
    assert failed.attempt.error_code == "quota_still_exhausted"
    assert retried.succeeded is True
    assert [row.status for row in repo.rows] == ["failed", "succeeded"]
    assert [log["status"] for log in logs.logs] == ["error", "success"]


@pytest.mark.asyncio
async def test_sender_exception_marks_attempt_failed_and_allows_retry(clock: list[int]) -> None:
    repo = FakeWarmupRepo()

    class ExplodingSender:
        async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
            raise RuntimeError("connection reset")

    result = await _service(ExplodingSender(), repo).run_manual_warmup(account=_account(), settings=_settings())

    assert result.succeeded is False
    assert result.request_id is None
    assert repo.rows[0].status == "failed"
    assert repo.rows[0].error_code == "warmup_send_failed"
    clock[0] += 1
    assert (await _service(FakeSender(), repo).run_manual_warmup(account=_account(), settings=_settings())).succeeded


@pytest.mark.asyncio
async def test_cancelled_manual_warmup_is_marked_failed(clock: list[int]) -> None:
    repo = FakeWarmupRepo()
    started = asyncio.Event()

    class HangingSender:
        async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    task = asyncio.create_task(
        _service(HangingSender(), repo).run_manual_warmup(account=_account(), settings=_settings())
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert repo.rows[0].status == "failed"
    assert repo.rows[0].error_code == "manual_warmup_interrupted"


@pytest.mark.parametrize(
    "status",
    [
        AccountStatus.PAUSED,
        AccountStatus.DEACTIVATED,
        AccountStatus.REAUTH_REQUIRED,
        AccountStatus.RATE_LIMITED,
        AccountStatus.QUOTA_EXCEEDED,
    ],
)
@pytest.mark.asyncio
async def test_manual_warmup_rejects_inactive_accounts_without_sending(clock: list[int], status: AccountStatus) -> None:
    repo, sender = FakeWarmupRepo(), FakeSender()
    with pytest.raises(ManualWarmupUnavailableError) as excinfo:
        await _service(sender, repo).run_manual_warmup(account=_account(status=status), settings=_settings())
    assert excinfo.value.code == "manual_warmup_account_not_active"
    assert sender.calls == []
    assert repo.rows == []


@pytest.mark.asyncio
async def test_manual_warmup_does_not_require_automatic_opt_in(clock: list[int]) -> None:
    sender = FakeSender()
    result = await _service(sender).run_manual_warmup(
        account=_account(enabled=False),
        settings=_settings(limit_warmup_enabled=False),
    )
    assert result.succeeded is True
    assert len(sender.calls) == 1


@pytest.mark.asyncio
async def test_manual_warmup_rejects_while_a_scheduled_warmup_is_in_flight(clock: list[int]) -> None:
    repo, sender = FakeWarmupRepo(), FakeSender()
    await repo.try_create_attempt(
        account_id="acc_1", window="primary_idle", reset_at=123, model="m", attempted_at=_at(clock[0] - 10)
    )
    with pytest.raises(ManualWarmupUnavailableError) as excinfo:
        await _service(sender, repo).run_manual_warmup(account=_account(), settings=_settings())
    assert excinfo.value.code == "manual_warmup_in_progress"
    assert sender.calls == []


@pytest.mark.asyncio
async def test_manual_warmup_reports_unavailable_model(clock: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    sender = FakeSender()
    service = _service(sender)
    monkeypatch.setattr(service, "_resolve_model", lambda configured, account: None)
    with pytest.raises(ManualWarmupUnavailableError) as excinfo:
        await service.run_manual_warmup(account=_account(), settings=_settings(limit_warmup_model="auto"))
    assert excinfo.value.code == "manual_warmup_model_unavailable"
    assert sender.calls == []


@pytest.mark.parametrize(("require_opt_in", "sends"), [(True, False), (False, True)])
@pytest.mark.asyncio
async def test_streaming_sender_pins_the_selected_account(
    monkeypatch: pytest.MonkeyPatch, require_opt_in: bool, sends: bool
) -> None:
    account = _account("acc_selected", enabled=False)
    account.chatgpt_account_id = "chatgpt_selected"
    calls: dict[str, Any] = {}
    sender = StreamingLimitWarmupSender(
        cast(Any, _WarmupAccountsRepo(account=account)),
        require_limit_warmup_opt_in=require_opt_in,
    )

    async def ensure_fresh(current: Account) -> Account:
        return current

    async def no_route(*args: object, **kwargs: object) -> None:
        return None

    async def stream(
        payload: ResponsesRequest, headers: dict[str, str], access_token: str, chatgpt_account_id: str, **kwargs: object
    ):
        calls.update(payload=payload, chatgpt_account_id=chatgpt_account_id, kwargs=kwargs, headers=headers)
        yield 'data: {"type":"response.completed","response":{"id":"resp_1"}}\n\n'

    monkeypatch.setattr(sender._auth_manager, "ensure_fresh", ensure_fresh)
    monkeypatch.setattr(sender._encryptor, "decrypt", lambda value: "access")
    monkeypatch.setattr(limit_warmup_service, "resolve_upstream_route", no_route)
    monkeypatch.setattr(limit_warmup_service, "stream_responses", stream)

    result = await sender.send(account, model="gpt-5.1-codex-mini", prompt="Say OK.")

    assert result.success is sends
    if not sends:
        assert result.error_code == "account_not_active"
        assert calls == {}
        return
    assert calls["chatgpt_account_id"] == "chatgpt_selected"
    assert calls["kwargs"]["codex_lb_account_id"] == "acc_selected"
    assert calls["headers"]["x-codex-lb-limit-warmup"] == "1"
    upstream_payload = calls["payload"].to_payload()
    assert upstream_payload["model"] == "gpt-5.1-codex-mini"
    assert upstream_payload["stream"] is True
    assert upstream_payload["store"] is False
    # The Codex Responses endpoint rejects max_output_tokens; it must be stripped.
    assert "max_output_tokens" not in upstream_payload


@pytest.mark.asyncio
async def test_retry_after_failure_is_keyed_off_the_last_manual_attempt(clock: list[int]) -> None:
    """An automatic attempt between a failed manual attempt and its retry must not cause a collision."""
    repo = FakeWarmupRepo()
    account = _account()

    failed = await _service(FakeSender(success=False, error_code="server_error"), repo).run_manual_warmup(
        account=account, settings=_settings()
    )
    scheduled = await repo.try_create_attempt(
        account_id=account.id, window="primary_idle", reset_at=123, model="m", attempted_at=_at(clock[0])
    )
    assert scheduled is not None
    await repo.complete_attempt(scheduled.id, status="succeeded", completed_at=_at(clock[0]))

    retried = await _service(FakeSender(), repo).run_manual_warmup(account=account, settings=_settings())

    assert failed.succeeded is False
    assert retried.succeeded is True
    assert retried.attempt.reset_at == failed.attempt.reset_at + 1
