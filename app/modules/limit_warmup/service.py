from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AsyncContextManager, Callable, Mapping, Protocol

from app.core import usage as usage_core
from app.core.auth.refresh import RefreshError
from app.core.clients.proxy import UpstreamProxyRouteTrace, override_stream_timeouts, stream_responses
from app.core.crypto import TokenEncryptor
from app.core.openai.model_registry import get_model_registry
from app.core.openai.models import OpenAIError, ResponseUsage
from app.core.openai.parsing import parse_sse_event
from app.core.openai.requests import ResponsesRequest
from app.core.plan_types import account_plan_matches_allowed, normalize_account_plan_type
from app.core.resilience.toggles import bind_resilience_toggles
from app.core.upstream_proxy import ResolvedUpstreamRoute, UpstreamProxyRouteError, resolve_upstream_route
from app.core.usage.pricing import get_pricing_for_model
from app.core.utils.time import naive_utc_to_epoch, utcnow
from app.db.models import Account, AccountLimitWarmup, AccountStatus, DashboardSettings, UsageHistory
from app.modules.accounts.auth_manager import AuthManager
from app.modules.accounts.repository import AccountsRepository
from app.modules.usage.mappers import usage_history_to_window_row

logger = logging.getLogger(__name__)

LIMIT_WARMUP_SOURCE = "limit_warmup"
LIMIT_WARMUP_REQUEST_KIND = "warmup"
LIMIT_WARMUP_HEADER = "x-codex-lb-limit-warmup"
_DEFAULT_WARMUP_INSTRUCTIONS = "Reply with OK only."
_TERMINAL_ERROR_EVENTS = {"response.failed", "response.incomplete", "error"}
_QUOTA_ERROR_CODES = {"insufficient_quota", "quota_exceeded", "rate_limit_exceeded", "usage_limit_reached"}
_MAX_CONCURRENT_WARMUP_SENDS = 4
_ROLLING_WINDOW_SECONDS = 300 * 60
_SHORT_WINDOW_MAX_MINUTES = 24 * 60
_STAGGER_SLOT_GRACE_SECONDS = 60
# Upper bound on how long after its slot opens an idle account may still be
# pre-started, so a delayed refresh does not skip the whole cycle.
_STAGGER_CATCH_UP_MAX_SECONDS = 15 * 60
# A not-started short window reports reset_at = observed_at + window. Allow
# for the fetch-to-write delay and upstream rounding of reset_after_seconds.
_SLIDING_RESET_TOLERANCE_SECONDS = 30
# Operator-excluded states leave the stagger cohort. Transient blocks
# (rate_limited, quota_exceeded) keep their slot so phases stay stable.
_STAGGER_COHORT_EXCLUDED_STATUSES = frozenset(
    {AccountStatus.PAUSED, AccountStatus.DEACTIVATED, AccountStatus.REAUTH_REQUIRED}
)
_IDLE_PRIMARY_WINDOW = "primary_idle"
# Minimum reset_at forward jump (in seconds) to confirm a real quota window reset.
# Upstream timestamp jitter of ~1 second must not trigger a warm-up.
_RESET_CONFIRMED_MIN_JUMP_SECONDS = 60
# Persist the upstream value, but treat nearby values as the same reset. This
# avoids duplicate attempts when reset_at jitters between refresh cycles.
_RESET_AT_JITTER_TOLERANCE_SECONDS = 5


@dataclass(frozen=True, slots=True)
class LimitWarmupSendResult:
    request_id: str
    success: bool
    latency_ms: int
    usage: ResponseUsage | None = None
    error_code: str | None = None
    error_message: str | None = None
    upstream_proxy_route_mode: str | None = None
    upstream_proxy_pool_id: str | None = None
    upstream_proxy_endpoint_id: str | None = None
    upstream_proxy_fallback_used: bool | None = None
    upstream_proxy_fail_closed_reason: str | None = None


@dataclass(frozen=True, slots=True)
class LimitWarmupSendOutcome:
    attempt: AccountLimitWarmup
    account: Account
    model: str
    result: LimitWarmupSendResult | None
    error_message: str | None = None


MANUAL_WARMUP_WINDOW = "manual"
MANUAL_WARMUP_COOLDOWN_SECONDS = 300
# Attempts in these states hold the manual cooldown; a failed attempt does not,
# so an operator can retry after an auth or transport failure.
_MANUAL_WARMUP_BLOCKING_STATUSES = ("pending", "succeeded")


class ManualWarmupUnavailableError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ManualWarmupResult:
    attempt: AccountLimitWarmup
    request_id: str | None
    succeeded: bool


class LimitWarmupSender(Protocol):
    async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult: ...


class LimitWarmupAttemptsRepository(Protocol):
    async def latest_by_account(
        self, account_ids: list[str], *, window: str | None = None
    ) -> dict[str, AccountLimitWarmup]: ...

    async def try_create_attempt(
        self,
        *,
        account_id: str,
        window: str,
        reset_at: int,
        model: str,
        attempted_at,
        status: str = "pending",
        reset_at_tolerance_seconds: int = 0,
        require_no_prior_attempt: bool = False,
        blocking_statuses: tuple[str, ...] | None = None,
    ) -> AccountLimitWarmup | None: ...

    async def complete_attempt(
        self,
        attempt_id: int,
        *,
        status: str,
        completed_at,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AccountLimitWarmup | None: ...


class LimitWarmupRequestLogRepository(Protocol):
    async def add_log(
        self,
        *,
        account_id: str | None,
        request_id: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        latency_ms: int | None,
        status: str,
        error_code: str | None,
        latency_first_token_ms: int | None = None,
        error_message: str | None = None,
        requested_at: datetime | None = None,
        cached_input_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        reasoning_effort: str | None = None,
        service_tier: str | None = None,
        requested_service_tier: str | None = None,
        actual_service_tier: str | None = None,
        transport: str | None = None,
        upstream_transport: str | None = None,
        api_key_id: str | None = None,
        session_id: str | None = None,
        plan_type: str | None = None,
        source: str | None = None,
        useragent: str | None = None,
        useragent_group: str | None = None,
        client_ip: str | None = None,
        failure_phase: str | None = None,
        failure_detail: str | None = None,
        failure_exception_type: str | None = None,
        upstream_status_code: int | None = None,
        upstream_error_code: str | None = None,
        bridge_stage: str | None = None,
        request_kind: str = "normal",
        upstream_proxy_route_mode: str | None = None,
        upstream_proxy_pool_id: str | None = None,
        upstream_proxy_endpoint_id: str | None = None,
        upstream_proxy_fallback_used: bool | None = None,
        upstream_proxy_fail_closed_reason: str | None = None,
    ) -> object: ...


class StreamingLimitWarmupSender:
    def __init__(
        self,
        accounts_repo: AccountsRepository,
        *,
        accounts_repo_factory: Callable[[], AsyncContextManager[AccountsRepository]] | None = None,
        require_limit_warmup_opt_in: bool = True,
    ) -> None:
        self._accounts_repo = accounts_repo
        self._accounts_repo_factory = accounts_repo_factory
        # Automatic warm-ups require the per-account opt-in; an operator's
        # explicit manual warm-up does not (the account must still be active).
        self._require_opt_in = require_limit_warmup_opt_in
        self._auth_manager = AuthManager(accounts_repo)
        self._encryptor = TokenEncryptor()
        self._auth_lock = asyncio.Lock()

    async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
        request_id = f"limit-warmup-{uuid.uuid4().hex}"
        started = time.monotonic()
        try:
            async with self._auth_lock:
                fresh_account = await self._ensure_fresh(account)
                if (
                    fresh_account is None
                    or not _account_is_safe_candidate(fresh_account)
                    or not self._opted_in(fresh_account)
                ):
                    if fresh_account is None:
                        error_message = "Account no longer exists"
                    elif not self._opted_in(fresh_account):
                        error_message = "Limit warm-up is disabled for this account"
                    else:
                        error_message = f"Account status is {fresh_account.status.value}"
                    return LimitWarmupSendResult(
                        request_id=request_id,
                        success=False,
                        latency_ms=_elapsed_ms(started),
                        error_code="account_not_active",
                        error_message=error_message,
                    )
                access_token = self._encryptor.decrypt(fresh_account.access_token_encrypted)
                chatgpt_account_id = fresh_account.chatgpt_account_id
        except RefreshError as exc:
            return LimitWarmupSendResult(
                request_id=request_id,
                success=False,
                latency_ms=_elapsed_ms(started),
                error_code=f"auth_refresh_{exc.code}",
                error_message=exc.message,
            )

        try:
            route = await self._resolve_upstream_route(fresh_account)
        except UpstreamProxyRouteError as exc:
            return LimitWarmupSendResult(
                request_id=request_id,
                success=False,
                latency_ms=_elapsed_ms(started),
                error_code="upstream_proxy_unavailable",
                error_message=f"Upstream proxy route unavailable: {exc.reason}",
                upstream_proxy_fail_closed_reason=exc.reason,
            )

        payload = ResponsesRequest.model_validate(
            {
                "model": model,
                "instructions": _DEFAULT_WARMUP_INSTRUCTIONS,
                "input": prompt,
                "tools": [],
                "parallel_tool_calls": False,
                "stream": True,
                "store": False,
                "max_output_tokens": 4,
            }
        )
        headers = {
            "x-request-id": request_id,
            LIMIT_WARMUP_HEADER: "1",
            "user-agent": "codex-lb-limit-warmup",
        }
        usage: ResponseUsage | None = None
        route_trace = UpstreamProxyRouteTrace()
        with override_stream_timeouts(
            connect_timeout_seconds=5.0,
            idle_timeout_seconds=10.0,
            total_timeout_seconds=30.0,
        ):
            async for event_block in stream_responses(
                payload,
                headers,
                access_token,
                chatgpt_account_id,
                upstream_stream_transport_override="http",
                route=route,
                route_trace=route_trace,
                allow_direct_egress=route is None,
                codex_lb_account_id=fresh_account.id,
            ):
                event = parse_sse_event(event_block)
                if event is None:
                    continue
                if event.response is not None and event.response.usage is not None:
                    usage = event.response.usage
                if event.type == "response.completed":
                    return LimitWarmupSendResult(
                        request_id=request_id,
                        success=True,
                        latency_ms=_elapsed_ms(started),
                        usage=usage,
                        upstream_proxy_route_mode=route_trace.mode,
                        upstream_proxy_pool_id=route_trace.pool_id,
                        upstream_proxy_endpoint_id=route_trace.endpoint_id,
                        upstream_proxy_fallback_used=route_trace.fallback_used,
                    )
                if event.type in _TERMINAL_ERROR_EVENTS:
                    error = _event_error(event.error, event.response.error if event.response is not None else None)
                    return LimitWarmupSendResult(
                        request_id=request_id,
                        success=False,
                        latency_ms=_elapsed_ms(started),
                        usage=usage,
                        error_code=error.code or event.type,
                        error_message=error.message or event.type,
                        upstream_proxy_route_mode=route_trace.mode,
                        upstream_proxy_pool_id=route_trace.pool_id,
                        upstream_proxy_endpoint_id=route_trace.endpoint_id,
                        upstream_proxy_fallback_used=route_trace.fallback_used,
                    )

        return LimitWarmupSendResult(
            request_id=request_id,
            success=False,
            latency_ms=_elapsed_ms(started),
            usage=usage,
            error_code="stream_incomplete",
            error_message="Warm-up stream ended without a terminal event",
            upstream_proxy_route_mode=route_trace.mode,
            upstream_proxy_pool_id=route_trace.pool_id,
            upstream_proxy_endpoint_id=route_trace.endpoint_id,
            upstream_proxy_fallback_used=route_trace.fallback_used,
        )

    def _opted_in(self, account: Account) -> bool:
        return account.limit_warmup_enabled or not self._require_opt_in

    async def _ensure_fresh(self, account: Account) -> Account | None:
        if self._accounts_repo_factory is None:
            current = await self._accounts_repo.get_by_id_fresh(account.id)
            if current is None or not _account_is_safe_candidate(current) or not self._opted_in(current):
                return current
            await self._auth_manager.ensure_fresh(current)
            return await self._accounts_repo.get_by_id_fresh(account.id)
        async with self._accounts_repo_factory() as accounts_repo:
            current = await accounts_repo.get_by_id_fresh(account.id)
            if current is None or not _account_is_safe_candidate(current) or not self._opted_in(current):
                return current
            await AuthManager(
                accounts_repo,
                refresh_repo_factory=self._accounts_repo_factory,
            ).ensure_fresh(current)
        async with self._accounts_repo_factory() as accounts_repo:
            return await accounts_repo.get_by_id_fresh(account.id)

    async def _resolve_upstream_route(self, account: Account) -> ResolvedUpstreamRoute | None:
        if self._accounts_repo_factory is not None:
            async with self._accounts_repo_factory() as accounts_repo:
                return await resolve_upstream_route(
                    accounts_repo.session,
                    account_id=account.id,
                    operation="limit_warmup",
                    scope="account",
                    encryptor=self._encryptor,
                )
        return await resolve_upstream_route(
            self._accounts_repo.session,
            account_id=account.id,
            operation="limit_warmup",
            scope="account",
            encryptor=self._encryptor,
        )


class LimitWarmupService:
    def __init__(
        self,
        warmup_repo: LimitWarmupAttemptsRepository,
        request_logs_repo: LimitWarmupRequestLogRepository,
        *,
        sender: LimitWarmupSender | None = None,
    ) -> None:
        self._warmup_repo = warmup_repo
        self._request_logs_repo = request_logs_repo
        self._sender = sender

    async def run_manual_warmup(
        self,
        *,
        account: Account,
        settings: DashboardSettings,
    ) -> ManualWarmupResult:
        """Send one operator-requested warm-up pinned to ``account``.

        The attempt claim is atomic and rolling: a pending or succeeded manual
        attempt for the account within the last ``MANUAL_WARMUP_COOLDOWN_SECONDS``
        rejects the request, so double clicks and concurrent requests send at
        most one upstream request. A failed attempt can be retried at once. A
        completed upstream request is not proof that a quota window started.
        """
        if not _account_is_safe_candidate(account):
            raise ManualWarmupUnavailableError(
                "manual_warmup_account_not_active",
                f"Manual warm-up requires an active account (status is {account.status.value})",
            )
        sender = self._sender
        if sender is None:
            raise RuntimeError("LimitWarmupService requires a sender")
        model = self._resolve_model(settings.limit_warmup_model, account)
        if model is None:
            raise ManualWarmupUnavailableError(
                "manual_warmup_model_unavailable",
                "No eligible priced text model is available for warm-up",
            )

        bind_resilience_toggles(settings)
        now = utcnow()
        latest_attempt = (await self._warmup_repo.latest_by_account([account.id])).get(account.id)
        if (
            latest_attempt is not None
            and latest_attempt.status == "pending"
            and now - latest_attempt.attempted_at < timedelta(seconds=MANUAL_WARMUP_COOLDOWN_SECONDS)
        ):
            raise ManualWarmupUnavailableError(
                "manual_warmup_in_progress",
                "A warm-up for this account is already in progress",
            )
        claim_key = naive_utc_to_epoch(now)
        latest_manual = (await self._warmup_repo.latest_by_account([account.id], window=MANUAL_WARMUP_WINDOW)).get(
            account.id
        )
        if latest_manual is not None:
            # A retry right after a failed manual attempt must not collide with
            # that attempt's exact (account, window, second) tuple, even if an
            # automatic attempt landed in between.
            claim_key = max(claim_key, latest_manual.reset_at + 1)
        attempt = await self._warmup_repo.try_create_attempt(
            account_id=account.id,
            window=MANUAL_WARMUP_WINDOW,
            reset_at=claim_key,
            model=model,
            attempted_at=now,
            reset_at_tolerance_seconds=MANUAL_WARMUP_COOLDOWN_SECONDS - 1,
            blocking_statuses=_MANUAL_WARMUP_BLOCKING_STATUSES,
        )
        if attempt is None:
            raise ManualWarmupUnavailableError(
                "manual_warmup_cooldown",
                "A manual warm-up was already sent for this account in the last five minutes",
            )
        try:
            outcome = await self._send_warmup(
                attempt,
                account=account,
                model=model,
                prompt=settings.limit_warmup_prompt,
                sender=sender,
                semaphore=asyncio.Semaphore(1),
            )
            completed = await self._complete_warmup(outcome)
        except BaseException:
            await self._mark_aborted_warmup(
                attempt,
                error_code="manual_warmup_interrupted",
                error_message="Manual warm-up interrupted before completion",
            )
            raise
        return ManualWarmupResult(
            attempt=completed or attempt,
            request_id=outcome.result.request_id if outcome.result is not None else None,
            succeeded=outcome.result is not None and outcome.result.success,
        )

    async def run_after_usage_refresh(
        self,
        *,
        accounts: list[Account],
        stagger_accounts: list[Account] | None = None,
        stagger_short_window_eligibility: Mapping[str, bool] | None = None,
        settings: DashboardSettings,
        before_primary: dict[str, UsageHistory],
        before_secondary: dict[str, UsageHistory],
        after_primary: dict[str, UsageHistory],
        after_secondary: dict[str, UsageHistory],
        previous_plan_types: dict[str, str | None] | None = None,
        refresh_started_at: datetime | None = None,
        usage_refresh_interval_seconds: int = _STAGGER_SLOT_GRACE_SECONDS,
    ) -> None:
        if not settings.limit_warmup_enabled:
            return
        # C2-3 resilience toggles: bound before the warmup fan-out so the
        # upstream probes gate their breaker on the dashboard value.
        bind_resilience_toggles(settings)
        selected_windows = _selected_windows(settings.limit_warmup_windows)
        if not selected_windows:
            return

        account_ids = [account.id for account in accounts]
        latest_attempts = await self._warmup_repo.latest_by_account(account_ids)
        sender = self._sender
        if sender is None:
            raise RuntimeError("LimitWarmupService requires a sender")
        send_tasks: dict[asyncio.Task[LimitWarmupSendOutcome], AccountLimitWarmup] = {}
        send_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_WARMUP_SENDS)
        stagger_source = accounts if stagger_accounts is None else stagger_accounts
        if stagger_short_window_eligibility is None:
            # Callers without a remembered roster view supply every cohort
            # member's latest primary sample; a missing sample is ineligible.
            stagger_short_window_eligibility = {
                account.id: stagger_short_window_eligible(after_primary.get(account.id)) for account in stagger_source
            }
        stagger_cohort = _stagger_cohort(
            stagger_source,
            short_window_eligibility=stagger_short_window_eligibility,
        )
        now = utcnow()

        for account in accounts:
            if not _account_is_safe_candidate(account):
                continue
            if not account.limit_warmup_enabled:
                continue
            latest_attempt = latest_attempts.get(account.id)

            windows_to_evaluate = list(selected_windows)
            if settings.limit_warmup_staggered_idle_enabled and "primary" not in windows_to_evaluate:
                windows_to_evaluate.append("primary")
            for window in windows_to_evaluate:
                candidate = None
                if window in selected_windows:
                    candidate = _build_candidate(
                        account=account,
                        window=window,
                        before_primary=before_primary,
                        before_secondary=before_secondary,
                        after_primary=after_primary,
                        after_secondary=after_secondary,
                        min_pre_reset_usage_percent=settings.limit_warmup_exhausted_threshold_percent,
                        min_available_percent=settings.limit_warmup_min_available_percent,
                    )
                if candidate is None and window == "secondary":
                    candidate = _build_paid_to_free_transition_candidate(
                        account=account,
                        previous_plan_type=(previous_plan_types or {}).get(account.id),
                        after_secondary=after_secondary,
                        refresh_started_at=refresh_started_at,
                        min_available_percent=settings.limit_warmup_min_available_percent,
                    )
                if candidate is None and window == "secondary":
                    candidate = _build_initial_free_quota_candidate(
                        account=account,
                        previous_plan_type=(previous_plan_types or {}).get(account.id),
                        latest_attempt=latest_attempt,
                        after_secondary=after_secondary,
                        refresh_started_at=refresh_started_at,
                    )
                if (
                    candidate is None
                    and _account_is_safe_candidate(account)
                    and settings.limit_warmup_staggered_idle_enabled
                    and window == "primary"
                    and stagger_cohort is not None
                ):
                    candidate = _build_staggered_idle_candidate(
                        account=account,
                        cohort_account_ids=stagger_cohort,
                        now=now,
                        before_primary=before_primary,
                        after_primary=after_primary,
                        refresh_started_at=refresh_started_at,
                        usage_refresh_interval_seconds=usage_refresh_interval_seconds,
                        idle_threshold_percent=settings.limit_warmup_idle_threshold_percent,
                    )
                if candidate is None:
                    continue
                if candidate.window == _IDLE_PRIMARY_WINDOW and _in_cooldown(
                    latest_attempt,
                    cooldown_seconds=settings.limit_warmup_cooldown_seconds,
                ):
                    continue

                model = self._resolve_model(settings.limit_warmup_model, account)
                if model is None:
                    skipped = await self._warmup_repo.try_create_attempt(
                        account_id=account.id,
                        window=candidate.window,
                        reset_at=candidate.reset_at,
                        model="auto",
                        attempted_at=utcnow(),
                        reset_at_tolerance_seconds=_attempt_reset_at_tolerance(candidate),
                        require_no_prior_attempt=candidate.require_no_prior_attempt,
                    )
                    if skipped is not None:
                        completed = await self._warmup_repo.complete_attempt(
                            skipped.id,
                            status="skipped",
                            completed_at=utcnow(),
                            error_code="model_unavailable",
                            error_message="No eligible priced text model was available for warm-up",
                        )
                        latest_attempt = completed or skipped
                        latest_attempts[account.id] = latest_attempt
                    elif candidate.require_no_prior_attempt:
                        break
                    continue

                attempt = await self._warmup_repo.try_create_attempt(
                    account_id=account.id,
                    window=candidate.window,
                    reset_at=candidate.reset_at,
                    model=model,
                    attempted_at=utcnow(),
                    reset_at_tolerance_seconds=_attempt_reset_at_tolerance(candidate),
                    require_no_prior_attempt=candidate.require_no_prior_attempt,
                )
                if attempt is None:
                    if candidate.require_no_prior_attempt:
                        break
                    continue
                latest_attempt = attempt
                latest_attempts[account.id] = attempt

                send_task = asyncio.create_task(
                    self._send_warmup(
                        attempt,
                        account=account,
                        model=model,
                        prompt=settings.limit_warmup_prompt,
                        sender=sender,
                        semaphore=send_semaphore,
                    ),
                    name=f"limit-warmup:{attempt.id}",
                )
                send_tasks[send_task] = attempt

        pending_send_tasks = set(send_tasks)
        try:
            while pending_send_tasks:
                completed_send_tasks, pending_send_tasks = await asyncio.wait(
                    pending_send_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                completion_error: BaseException | None = None
                for send_task in completed_send_tasks:
                    outcome = await send_task
                    try:
                        completed = await self._complete_warmup(outcome)
                    except Exception as exc:
                        completion_error = completion_error or exc
                        await self._mark_aborted_warmup(
                            outcome.attempt,
                            error_code="warmup_completion_failed",
                            error_message="Limit warm-up completion failed",
                        )
                        continue
                    latest_attempts[outcome.account.id] = completed or outcome.attempt
                if completion_error is not None:
                    raise completion_error
        finally:
            if pending_send_tasks:
                for send_task in pending_send_tasks:
                    send_task.cancel()
                drained_results = await asyncio.gather(*pending_send_tasks, return_exceptions=True)
                for send_task, drained_result in zip(pending_send_tasks, drained_results, strict=True):
                    if isinstance(drained_result, LimitWarmupSendOutcome):
                        try:
                            completed = await self._complete_warmup(drained_result)
                        except Exception:
                            await self._mark_aborted_warmup(
                                drained_result.attempt,
                                error_code="warmup_completion_failed",
                                error_message="Limit warm-up completion failed",
                            )
                            continue
                        latest_attempts[drained_result.account.id] = completed or drained_result.attempt
                        continue
                    await self._mark_aborted_warmup(
                        send_tasks[send_task],
                        error_code=(
                            "warmup_cancelled"
                            if isinstance(drained_result, asyncio.CancelledError)
                            else "warmup_send_failed"
                        ),
                        error_message=(
                            "Limit warm-up cancelled after another warm-up completion failed"
                            if isinstance(drained_result, asyncio.CancelledError)
                            else (_truncate(str(drained_result)) or "Limit warm-up send failed")
                        ),
                    )

    def _resolve_model(self, configured_model: str, account: Account) -> str | None:
        normalized = configured_model.strip()
        if normalized and normalized.lower() != "auto":
            return normalized

        candidates: list[tuple[float, str]] = []
        for model in get_model_registry().get_models_with_fallback().values():
            if not model.supported_in_api:
                continue
            if model.input_modalities and "text" not in {modality.lower() for modality in model.input_modalities}:
                continue
            if model.available_in_plans and not account_plan_matches_allowed(
                account.plan_type, model.available_in_plans
            ):
                continue
            resolved_price = get_pricing_for_model(model.slug)
            if resolved_price is None:
                continue
            _, price = resolved_price
            candidates.append((price.input_per_1m + price.output_per_1m, model.slug))
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item[0], item[1]))[1]

    async def _send_warmup(
        self,
        attempt: AccountLimitWarmup,
        *,
        account: Account,
        model: str,
        prompt: str,
        sender: LimitWarmupSender,
        semaphore: asyncio.Semaphore,
    ) -> LimitWarmupSendOutcome:
        try:
            async with semaphore:
                result = await sender.send(account, model=model, prompt=prompt)
        except Exception as exc:
            logger.warning(
                "Limit warm-up send failed account_id=%s window=%s", account.id, attempt.window, exc_info=True
            )
            return LimitWarmupSendOutcome(
                attempt=attempt,
                account=account,
                model=model,
                result=None,
                error_message=str(exc),
            )

        return LimitWarmupSendOutcome(attempt=attempt, account=account, model=model, result=result)

    async def _complete_warmup(self, outcome: LimitWarmupSendOutcome) -> AccountLimitWarmup | None:
        if outcome.result is None:
            return await self._warmup_repo.complete_attempt(
                outcome.attempt.id,
                status="failed",
                completed_at=utcnow(),
                error_code="warmup_send_failed",
                error_message=_truncate(outcome.error_message),
            )

        result = outcome.result
        await self._record_request_log(
            account=outcome.account,
            model=outcome.model,
            result=result,
        )
        status = "succeeded" if result.success else "failed"
        error_code = result.error_code
        if error_code in _QUOTA_ERROR_CODES:
            error_code = "quota_still_exhausted"
        return await self._warmup_repo.complete_attempt(
            outcome.attempt.id,
            status=status,
            completed_at=utcnow(),
            error_code=error_code,
            error_message=_truncate(result.error_message),
        )

    async def _mark_aborted_warmup(
        self,
        attempt: AccountLimitWarmup,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        try:
            await self._warmup_repo.complete_attempt(
                attempt.id,
                status="failed",
                completed_at=utcnow(),
                error_code=error_code,
                error_message=error_message,
            )
        except Exception:
            logger.warning(
                "Failed to mark aborted limit warm-up attempt_id=%s error_code=%s",
                attempt.id,
                error_code,
                exc_info=True,
            )

    async def _record_request_log(
        self,
        *,
        account: Account,
        model: str,
        result: LimitWarmupSendResult,
    ) -> None:
        usage = result.usage
        input_tokens = usage.input_tokens if usage is not None else None
        output_tokens = usage.output_tokens if usage is not None else None
        cached_input_tokens = (
            usage.input_tokens_details.cached_tokens
            if usage is not None and usage.input_tokens_details is not None
            else None
        )
        reasoning_tokens = (
            usage.output_tokens_details.reasoning_tokens
            if usage is not None and usage.output_tokens_details is not None
            else None
        )
        await self._request_logs_repo.add_log(
            account_id=account.id,
            request_id=result.request_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            reasoning_tokens=reasoning_tokens,
            latency_ms=result.latency_ms,
            status="success" if result.success else "error",
            error_code=result.error_code,
            error_message=_truncate(result.error_message),
            transport="http",
            plan_type=account.plan_type,
            source=LIMIT_WARMUP_SOURCE,
            request_kind=LIMIT_WARMUP_REQUEST_KIND,
            upstream_proxy_route_mode=result.upstream_proxy_route_mode,
            upstream_proxy_pool_id=result.upstream_proxy_pool_id,
            upstream_proxy_endpoint_id=result.upstream_proxy_endpoint_id,
            upstream_proxy_fallback_used=result.upstream_proxy_fallback_used,
            upstream_proxy_fail_closed_reason=result.upstream_proxy_fail_closed_reason,
        )


@dataclass(frozen=True, slots=True)
class _WarmupCandidate:
    reset_at: int
    window: str
    require_no_prior_attempt: bool = False


def _selected_windows(value: str) -> tuple[str, ...]:
    normalized = value.strip().lower()
    if normalized == "both":
        return ("primary", "secondary")
    if normalized in {"primary", "secondary"}:
        return (normalized,)
    return ()


def _account_is_safe_candidate(account: Account) -> bool:
    return account.status == AccountStatus.ACTIVE


def _in_cooldown(attempt: AccountLimitWarmup | None, *, cooldown_seconds: int) -> bool:
    if attempt is None:
        return False
    return utcnow() - attempt.attempted_at < timedelta(seconds=cooldown_seconds)


def _build_candidate(
    *,
    account: Account,
    window: str,
    before_primary: dict[str, UsageHistory],
    before_secondary: dict[str, UsageHistory],
    after_primary: dict[str, UsageHistory],
    after_secondary: dict[str, UsageHistory],
    min_pre_reset_usage_percent: float,
    min_available_percent: float,
) -> _WarmupCandidate | None:
    before = _effective_usage_entry(
        account.id,
        window=window,
        primary=before_primary,
        secondary=before_secondary,
    )
    after = _effective_usage_entry(
        account.id,
        window=window,
        primary=after_primary,
        secondary=after_secondary,
    )
    if before is None or after is None:
        return None
    if not math.isfinite(before.used_percent) or before.used_percent < min_pre_reset_usage_percent:
        return None
    available_percent = 100.0 - after.used_percent
    if min_available_percent < 100.0 and available_percent < min_available_percent:
        return None
    if not usage_reset_confirmed(before=before, after=after):
        return None
    assert after.reset_at is not None
    candidate_window = "monthly" if after.window == "monthly" else window
    return _WarmupCandidate(reset_at=after.reset_at, window=candidate_window)


def usage_reset_confirmed(*, before: UsageHistory | None, after: UsageHistory | None) -> bool:
    """Return whether consecutive samples prove a real, newly available quota window."""
    if before is None or after is None:
        return False
    if before.reset_at is None or after.reset_at is None:
        return False
    if (before.window or "primary") != (after.window or "primary"):
        return False
    if after.used_percent >= 100.0:
        return False
    reset_at_jump = after.reset_at - before.reset_at
    if reset_at_jump < _RESET_CONFIRMED_MIN_JUMP_SECONDS:
        return False
    before_observed_at = naive_utc_to_epoch(before.recorded_at)
    observed_at = naive_utc_to_epoch(after.recorded_at)
    window_started_at = after.reset_at - _rolling_window_seconds(after)
    quota_recovered = after.used_percent < before.used_percent
    crossed_previous_reset = before_observed_at <= before.reset_at <= observed_at < after.reset_at
    reanchored_between_samples = (
        quota_recovered and before_observed_at <= window_started_at <= observed_at < after.reset_at
    )
    # Scheduled resets cross the previous boundary. Early resets can happen
    # when upstream restores quota and reanchors a complete window from the
    # sampling interval. A reset_at update outside that interval is not a reset.
    if not crossed_previous_reset and not reanchored_between_samples:
        return False
    return True


def _build_paid_to_free_transition_candidate(
    *,
    account: Account,
    previous_plan_type: str | None,
    after_secondary: dict[str, UsageHistory],
    refresh_started_at: datetime | None,
    min_available_percent: float,
) -> _WarmupCandidate | None:
    normalized_previous_plan = normalize_account_plan_type(previous_plan_type)
    if normalized_previous_plan is None or normalized_previous_plan == "free":
        return None
    if normalize_account_plan_type(account.plan_type) != "free":
        return None
    if refresh_started_at is None:
        return None
    after = after_secondary.get(account.id)
    if after is None or after.window != "monthly" or after.reset_at is None:
        return None
    if after.recorded_at < refresh_started_at:
        return None
    if after.used_percent >= 100.0:
        return None
    available_percent = 100.0 - after.used_percent
    if min_available_percent < 100.0 and available_percent < min_available_percent:
        return None
    return _WarmupCandidate(reset_at=after.reset_at, window="monthly")


def _build_initial_free_quota_candidate(
    *,
    account: Account,
    previous_plan_type: str | None,
    latest_attempt: AccountLimitWarmup | None,
    after_secondary: dict[str, UsageHistory],
    refresh_started_at: datetime | None,
) -> _WarmupCandidate | None:
    if latest_attempt is not None:
        return None
    if normalize_account_plan_type(account.plan_type) != "free":
        return None
    if normalize_account_plan_type(previous_plan_type) != "free":
        return None
    if refresh_started_at is None:
        return None
    after = after_secondary.get(account.id)
    if after is None or after.window != "monthly" or after.reset_at is None:
        return None
    if after.recorded_at < refresh_started_at:
        return None
    if after.used_percent != 0.0:
        return None
    return _WarmupCandidate(
        reset_at=after.reset_at,
        window="monthly",
        require_no_prior_attempt=True,
    )


def _build_staggered_idle_candidate(
    *,
    account: Account,
    cohort_account_ids: list[str],
    now: datetime,
    before_primary: dict[str, UsageHistory],
    after_primary: dict[str, UsageHistory],
    refresh_started_at: datetime | None,
    usage_refresh_interval_seconds: int,
    idle_threshold_percent: float = 1.0,
) -> _WarmupCandidate | None:
    after = after_primary.get(account.id)
    if after is None or after.reset_at is None:
        return None
    if not stagger_short_window_eligible(after):
        # Any long window (weekly, monthly, or a nonstandard duration over
        # 24h) has no short phase to pre-start.
        return None
    if after.used_percent > idle_threshold_percent:
        return None
    # Only a sample written by this refresh slice may trigger synthetic
    # traffic; stale or carried-over usage history never does.
    if refresh_started_at is None or after.recorded_at < refresh_started_at:
        return None
    window_seconds = _rolling_window_seconds(after)
    if not _short_window_not_started(before=before_primary.get(account.id), after=after):
        return None
    due = _staggered_idle_due(
        account.id,
        cohort_account_ids,
        now=now,
        window_seconds=window_seconds,
        usage_refresh_interval_seconds=usage_refresh_interval_seconds,
    )
    if due is None:
        return None
    # A not-started window has no stable upstream reset identity, so the
    # UTC grid cycle is the durable dedupe identity. It is identical across
    # refreshes, restarts, and replicas.
    return _WarmupCandidate(reset_at=due.cycle_end, window=_IDLE_PRIMARY_WINDOW)


def stagger_short_window_eligible(entry: UsageHistory | None) -> bool:
    """Whether a latest primary sample places an account in the short-window stagger cohort."""
    if entry is None:
        return False
    return entry.window_minutes is None or entry.window_minutes <= _SHORT_WINDOW_MAX_MINUTES


def _stagger_cohort(
    accounts: list[Account],
    *,
    short_window_eligibility: Mapping[str, bool],
) -> list[str] | None:
    """Return the sorted short-window cohort, or ``None`` while membership is unknown.

    Membership depends only on account state and known eligibility, never on
    enumeration order. Transiently blocked accounts keep their slot so that a
    rate limit does not reshuffle every other account's phase; operator-
    excluded states (paused, deactivated, reauth required) and opted-out or
    deleted accounts leave the cohort.
    """
    members: set[str] = set()
    for account in accounts:
        if not account.limit_warmup_enabled or account.status in _STAGGER_COHORT_EXCLUDED_STATUSES:
            continue
        if account.delete_requested_at is not None:
            continue
        eligible = short_window_eligibility.get(account.id)
        if eligible is None:
            return None
        if eligible:
            members.add(account.id)
    return sorted(members)


def _reset_slides_with_observation(entry: UsageHistory) -> bool:
    if entry.reset_at is None or entry.recorded_at is None:
        return False
    observed_at = naive_utc_to_epoch(entry.recorded_at)
    return abs(entry.reset_at - observed_at - _rolling_window_seconds(entry)) <= _SLIDING_RESET_TOLERANCE_SECONDS


def _short_window_not_started(*, before: UsageHistory | None, after: UsageHistory) -> bool:
    """Whether consecutive samples show a short window that has not started.

    A not-started window reports ``reset_at ~= observed_at + window`` on every
    poll (upstream #1976). A single such sample is ambiguous with a window
    that started moments ago, so the previous observation must corroborate
    it: either it slid as well, or the window it described had already ended
    by the time of the new observation. A previous window that is still
    running means real usage owns the account's phase and is never touched.
    """
    if not _reset_slides_with_observation(after):
        return False
    if before is None or before.reset_at is None or before.recorded_at is None:
        return False
    if before.recorded_at > after.recorded_at:
        return False
    if _reset_slides_with_observation(before):
        return True
    return before.reset_at <= naive_utc_to_epoch(after.recorded_at) + _SLIDING_RESET_TOLERANCE_SECONDS


@dataclass(frozen=True, slots=True)
class _StaggeredIdleDue:
    cycle_end: int
    slot_offset_seconds: int


def _rolling_window_seconds(entry: UsageHistory) -> int:
    # Derive the rolling cycle from the observed primary window duration so
    # the stagger tracks whatever short window upstream reports; 300 minutes
    # remains the fallback when duration metadata is missing.
    if entry.window_minutes is not None and entry.window_minutes > 0:
        return int(entry.window_minutes) * 60
    return _ROLLING_WINDOW_SECONDS


def _stagger_catch_up_seconds(*, window_seconds: int, cohort_size: int, usage_refresh_interval_seconds: int) -> int:
    # A slot stays claimable for a bounded time after it opens so one failed or
    # delayed refresh does not skip a whole cycle. Capping it at half the slot
    # spacing keeps two slots from both being claimable after a restart.
    spread_bound = window_seconds // (2 * cohort_size)
    refresh_bound = 2 * max(_STAGGER_SLOT_GRACE_SECONDS, usage_refresh_interval_seconds)
    return max(refresh_bound, min(_STAGGER_CATCH_UP_MAX_SECONDS, spread_bound))


def _staggered_idle_due(
    account_id: str,
    account_ids: list[str],
    *,
    now: datetime,
    window_seconds: int = _ROLLING_WINDOW_SECONDS,
    usage_refresh_interval_seconds: int = _STAGGER_SLOT_GRACE_SECONDS,
) -> _StaggeredIdleDue | None:
    """Return the account's slot on the epoch-aligned UTC grid if it is claimable now.

    Cycles start at multiples of ``window_seconds`` since the Unix epoch and
    the sorted cohort is spread evenly across each cycle, so two accounts sit
    half a window apart and N accounts ``window / N`` apart.
    """
    ordered_account_ids = sorted(set(account_ids))
    if account_id not in ordered_account_ids:
        return None
    account_index = ordered_account_ids.index(account_id)
    cohort_size = len(ordered_account_ids)

    now_epoch = naive_utc_to_epoch(now)
    cycle_start = now_epoch - now_epoch % window_seconds
    slot_offset = account_index * window_seconds // cohort_size
    elapsed = now_epoch - cycle_start
    catch_up = _stagger_catch_up_seconds(
        window_seconds=window_seconds,
        cohort_size=cohort_size,
        usage_refresh_interval_seconds=usage_refresh_interval_seconds,
    )
    if not slot_offset <= elapsed < slot_offset + catch_up:
        return None
    return _StaggeredIdleDue(cycle_end=cycle_start + window_seconds, slot_offset_seconds=slot_offset)


def _effective_usage_entry(
    account_id: str,
    *,
    window: str,
    primary: dict[str, UsageHistory],
    secondary: dict[str, UsageHistory],
) -> UsageHistory | None:
    if window == "primary":
        primary_entry = primary.get(account_id)
        if primary_entry is None or usage_core.is_weekly_window_minutes(primary_entry.window_minutes):
            return None
        return primary_entry

    primary_entry = primary.get(account_id)
    secondary_entry = secondary.get(account_id)
    if primary_entry is not None and usage_core.is_weekly_window_minutes(primary_entry.window_minutes):
        if secondary_entry is None:
            return primary_entry
        if usage_core.should_use_weekly_primary(
            usage_history_to_window_row(primary_entry),
            usage_history_to_window_row(secondary_entry),
        ):
            return primary_entry
    return secondary_entry


def _event_error(*errors: OpenAIError | None) -> OpenAIError:
    for error in errors:
        if error is not None:
            return error
    return OpenAIError(message=None, code=None)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _truncate(value: str | None, limit: int = 1000) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "..."


def _attempt_reset_at_tolerance(candidate: _WarmupCandidate) -> int:
    return _RESET_AT_JITTER_TOLERANCE_SECONDS
