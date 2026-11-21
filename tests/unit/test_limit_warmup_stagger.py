"""Staggered idle warm-up against a mocked upstream short-window limiter.

The simulator mirrors the usage-refresh scheduler: one account is refreshed per
slice, each slice passes the selected account's previous and fresh primary
samples, and short-window eligibility is remembered per account exactly as the
scheduler does. Upstream is modelled as a 5-hour limiter whose window starts on
the first request; an idle account reports a sliding ``reset_at`` (upstream
issue #1976). No real upstream traffic is sent.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.db.models import Account, AccountStatus, UsageHistory
from app.modules.limit_warmup import service as limit_warmup_service
from app.modules.limit_warmup.service import LimitWarmupSendResult, LimitWarmupService
from tests.unit.test_limit_warmup import FakeRequestLogsRepo, FakeWarmupRepo, _account, _settings

pytestmark = pytest.mark.unit

W = 18_000
BASE = 100 * W  # aligned with the epoch UTC grid
INTERVAL = 60


def _at(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)


def _sample(
    account_id: str,
    *,
    observed: int,
    reset_at: int | None,
    used: float = 0.0,
    window_minutes: int | None = 300,
) -> UsageHistory:
    return UsageHistory(
        account_id=account_id,
        used_percent=used,
        reset_at=reset_at,
        window="primary",
        window_minutes=window_minutes,
        recorded_at=_at(observed),
    )


def _sliding(account_id: str, observed: int, *, jitter: int = 0, used: float = 0.0) -> UsageHistory:
    return _sample(account_id, observed=observed, reset_at=observed + W + jitter, used=used)


@dataclass
class UpstreamLimiter:
    """A mocked short-window limiter: the first request starts a W-second window."""

    window_minutes: dict[str, int | None] = field(default_factory=dict)
    started: dict[str, int] = field(default_factory=dict)
    jitter: int = 0
    rng: random.Random | None = None

    def request(self, account_id: str, at: int) -> None:
        if not self.active(account_id, at):
            self.started[account_id] = at

    def active(self, account_id: str, at: int) -> bool:
        started = self.started.get(account_id)
        return started is not None and started <= at < started + W

    def sample(self, account_id: str, at: int) -> UsageHistory | None:
        if account_id not in self.window_minutes:
            return None
        minutes = self.window_minutes[account_id]
        if minutes is not None and minutes > 24 * 60:
            return _sample(account_id, observed=at, reset_at=at + 3 * 86_400, window_minutes=minutes)
        if self.active(account_id, at):
            return _sample(account_id, observed=at, reset_at=self.started[account_id] + W, used=0.5)
        jitter = self.rng.randint(-self.jitter, self.jitter) if self.rng is not None else self.jitter
        return _sample(account_id, observed=at, reset_at=at + W + jitter)


class LimiterSender:
    def __init__(self, limiter: UpstreamLimiter, clock: list[int]) -> None:
        self.limiter = limiter
        self.clock = clock
        self.sent: list[tuple[str, int]] = []

    async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
        now = self.clock[0]
        self.sent.append((account.id, now))
        self.limiter.request(account.id, now)
        return LimitWarmupSendResult(request_id=f"warmup-{len(self.sent)}", success=True, latency_ms=5)


@dataclass
class StaggerSimulation:
    """Drives ``run_after_usage_refresh`` the way the usage-refresh scheduler does."""

    accounts: list[Account]
    limiter: UpstreamLimiter
    clock: list[int]
    repo: FakeWarmupRepo = field(default_factory=FakeWarmupRepo)
    eligibility: dict[str, bool] = field(default_factory=dict)
    last_sample: dict[str, UsageHistory] = field(default_factory=dict)
    rotation: int = 0

    def __post_init__(self) -> None:
        self.sender = LimiterSender(self.limiter, self.clock)
        self.service = self.new_service()

    def new_service(self) -> LimitWarmupService:
        return LimitWarmupService(self.repo, FakeRequestLogsRepo(), sender=self.sender)

    def restart(self) -> None:
        """Process restart: in-memory scheduler state is lost, the database is not."""
        self.service = self.new_service()
        self.eligibility = {}
        self.rotation = 0

    async def slice(self, at: int) -> None:
        roster = sorted(
            (
                account
                for account in self.accounts
                if account.status
                not in (AccountStatus.PAUSED, AccountStatus.REAUTH_REQUIRED, AccountStatus.DEACTIVATED)
            ),
            key=lambda account: account.id,
        )
        if not roster:
            return
        selected = roster[self.rotation % len(roster)]
        self.rotation += 1
        roster_ids = {account.id for account in roster}
        for account_id in list(self.eligibility):
            if account_id not in roster_ids:
                del self.eligibility[account_id]
        before = self.last_sample.get(selected.id)
        self.eligibility[selected.id] = limit_warmup_service.stagger_short_window_eligible(before)
        after = self.limiter.sample(selected.id, at + 1)
        if after is not None:
            self.last_sample[selected.id] = after
        self.eligibility[selected.id] = limit_warmup_service.stagger_short_window_eligible(
            self.last_sample.get(selected.id)
        )
        self.clock[0] = at + 2
        await self.service.run_after_usage_refresh(
            accounts=[selected],
            stagger_accounts=list(self.accounts),
            stagger_short_window_eligibility=dict(self.eligibility),
            settings=_settings(
                limit_warmup_windows="secondary",
                limit_warmup_staggered_idle_enabled=True,
            ),
            before_primary={selected.id: before} if before is not None else {},
            before_secondary={},
            after_primary={selected.id: after} if after is not None else {},
            after_secondary={},
            refresh_started_at=_at(at),
            usage_refresh_interval_seconds=INTERVAL,
        )

    async def run(self, start: int, end: int) -> None:
        at = start
        while at < end:
            roster_size = max(1, len(self.accounts))
            await self.slice(at)
            at += max(1, INTERVAL // roster_size)


def _new_simulation(
    monkeypatch: pytest.MonkeyPatch,
    accounts: list[Account],
    *,
    window_minutes: dict[str, int | None] | None = None,
    jitter: int = 0,
    rng: random.Random | None = None,
) -> StaggerSimulation:
    clock = [BASE]
    monkeypatch.setattr(limit_warmup_service, "utcnow", lambda: _at(clock[0]))
    minutes: dict[str, int | None] = {account.id: 300 for account in accounts}
    minutes.update(window_minutes or {})
    return StaggerSimulation(
        accounts=accounts,
        limiter=UpstreamLimiter(window_minutes=minutes, jitter=jitter, rng=rng),
        clock=clock,
    )


def _sends_for(simulation: StaggerSimulation, account_id: str) -> list[int]:
    return [at for sent_id, at in simulation.sender.sent if sent_id == account_id]


def _catch_up(cohort_size: int) -> int:
    return limit_warmup_service._stagger_catch_up_seconds(
        window_seconds=W, cohort_size=cohort_size, usage_refresh_interval_seconds=INTERVAL
    )


def _assert_in_slot(at: int, *, index: int, cohort_size: int) -> None:
    elapsed = (at - BASE) % W
    offset = index * W // cohort_size
    assert offset <= elapsed < offset + _catch_up(cohort_size), (at, elapsed, offset)


@pytest.mark.asyncio
async def test_two_sliding_accounts_settle_half_a_window_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    simulation = _new_simulation(monkeypatch, [_account("acc_1"), _account("acc_2")])

    await simulation.run(BASE, BASE + 3 * W)

    first, second = _sends_for(simulation, "acc_1"), _sends_for(simulation, "acc_2")
    assert len(first) == 3 and len(second) == 3
    for at in first:
        _assert_in_slot(at, index=0, cohort_size=2)
    for at in second:
        _assert_in_slot(at, index=1, cohort_size=2)
    # The two accounts' windows start about 150 minutes apart in every cycle.
    for first_at, second_at in zip(first, second, strict=True):
        assert abs((second_at - first_at) - W // 2) <= 3 * INTERVAL
    # One durable attempt per account per grid cycle, keyed by the cycle end.
    keys = sorted((row.account_id, row.reset_at) for row in simulation.repo.rows)
    assert keys == sorted((account_id, BASE + cycle * W) for account_id in ("acc_1", "acc_2") for cycle in (1, 2, 3))
    assert {row.window for row in simulation.repo.rows} == {"primary_idle"}


@pytest.mark.parametrize("cohort_size", [3, 4, 5])
@pytest.mark.asyncio
async def test_n_sliding_accounts_are_spread_evenly(monkeypatch: pytest.MonkeyPatch, cohort_size: int) -> None:
    accounts = [_account(f"acc_{index}") for index in range(cohort_size)]
    simulation = _new_simulation(monkeypatch, accounts)

    await simulation.run(BASE, BASE + 2 * W)

    for index, account in enumerate(accounts):
        sends = _sends_for(simulation, account.id)
        assert len(sends) == 2, account.id
        for at in sends:
            _assert_in_slot(at, index=index, cohort_size=cohort_size)


@pytest.mark.asyncio
async def test_mixed_cohort_spaces_only_short_window_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    accounts = [_account("a_weekly"), _account("b_short"), _account("c_missing"), _account("d_short")]
    simulation = _new_simulation(
        monkeypatch,
        accounts,
        window_minutes={"a_weekly": 10_080},
    )
    del simulation.limiter.window_minutes["c_missing"]

    await simulation.run(BASE, BASE + W)

    assert _sends_for(simulation, "a_weekly") == []
    assert _sends_for(simulation, "c_missing") == []
    (b_at,) = _sends_for(simulation, "b_short")
    (d_at,) = _sends_for(simulation, "d_short")
    # Only the two eligible accounts form the cohort: slots 0 and W/2.
    _assert_in_slot(b_at, index=0, cohort_size=2)
    _assert_in_slot(d_at, index=1, cohort_size=2)


@pytest.mark.asyncio
async def test_active_fixed_window_is_never_warmed(monkeypatch: pytest.MonkeyPatch) -> None:
    simulation = _new_simulation(monkeypatch, [_account("acc_1"), _account("acc_2")])
    # Real traffic started acc_2's window before its slot; it stays fixed until BASE + 3000 + W.
    simulation.limiter.request("acc_2", BASE + 3_000)

    await simulation.run(BASE, BASE + 2 * W)

    second = _sends_for(simulation, "acc_2")
    # No warm-up while the traffic-started window is running, and the first
    # pre-start lands on acc_2's next grid slot rather than at the window end.
    assert all(at >= BASE + 3_000 + W for at in second)
    assert len(second) == 1
    _assert_in_slot(second[0], index=1, cohort_size=2)


@pytest.mark.asyncio
async def test_real_traffic_after_a_prestart_does_not_add_warmups(monkeypatch: pytest.MonkeyPatch) -> None:
    simulation = _new_simulation(monkeypatch, [_account("acc_1"), _account("acc_2")])
    await simulation.run(BASE, BASE + W // 2 - 600)
    baseline = list(simulation.sender.sent)

    # Real traffic hits both accounts repeatedly; their windows are active.
    for at in range(BASE + W // 2 - 600, BASE + W, 900):
        simulation.limiter.request("acc_1", at)
        simulation.limiter.request("acc_2", at)
    await simulation.run(BASE + W // 2 - 600, BASE + W)

    assert simulation.sender.sent == baseline


@pytest.mark.asyncio
async def test_jittered_sliding_observations_are_still_scheduled(monkeypatch: pytest.MonkeyPatch) -> None:
    simulation = _new_simulation(monkeypatch, [_account("acc_1"), _account("acc_2")], jitter=20, rng=random.Random(7))

    await simulation.run(BASE, BASE + 2 * W)

    assert len(_sends_for(simulation, "acc_1")) == 2
    assert len(_sends_for(simulation, "acc_2")) == 2


@pytest.mark.asyncio
async def test_reset_that_does_not_track_the_observation_is_never_warmed(monkeypatch: pytest.MonkeyPatch) -> None:
    # A reset deadline far from observed_at + window is not the not-started
    # signature; the scheduler stays conservative and sends nothing.
    simulation = _new_simulation(monkeypatch, [_account("acc_1"), _account("acc_2")], jitter=-600)

    await simulation.run(BASE, BASE + W)

    assert simulation.sender.sent == []


@pytest.mark.asyncio
async def test_scheduler_restart_keeps_slots_and_does_not_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    simulation = _new_simulation(monkeypatch, [_account("acc_1"), _account("acc_2")])
    # acc_2's slot opens at W/2; restart shortly after its first pre-start.
    await simulation.run(BASE, BASE + W // 2 + 90)
    assert len(_sends_for(simulation, "acc_2")) == 1

    simulation.restart()
    await simulation.run(BASE + W // 2 + 90, BASE + 2 * W)

    first, second = _sends_for(simulation, "acc_1"), _sends_for(simulation, "acc_2")
    assert len(first) == 2 and len(second) == 2
    for at in second:
        _assert_in_slot(at, index=1, cohort_size=2)


@pytest.mark.asyncio
async def test_restart_holds_stagger_until_the_cohort_is_known(monkeypatch: pytest.MonkeyPatch) -> None:
    now = BASE + W // 2 + 5
    monkeypatch.setattr(limit_warmup_service, "utcnow", lambda: _at(now))
    sender = LimiterSender(UpstreamLimiter(), [now])
    service = LimitWarmupService(FakeWarmupRepo(), FakeRequestLogsRepo(), sender=sender)
    accounts = [_account("acc_1"), _account("acc_2")]
    selected = accounts[1]

    async def evaluate(eligibility: dict[str, bool]) -> None:
        await service.run_after_usage_refresh(
            accounts=[selected],
            stagger_accounts=accounts,
            stagger_short_window_eligibility=eligibility,
            settings=_settings(limit_warmup_windows="secondary", limit_warmup_staggered_idle_enabled=True),
            before_primary={selected.id: _sliding(selected.id, now - 61)},
            before_secondary={},
            after_primary={selected.id: _sliding(selected.id, now - 1)},
            after_secondary={},
            refresh_started_at=_at(now - 2),
        )

    # acc_1 has not been observed since the restart: membership is unknown.
    await evaluate({"acc_2": True})
    assert sender.sent == []

    await evaluate({"acc_1": True, "acc_2": True})
    assert [account_id for account_id, _ in sender.sent] == ["acc_2"]


@pytest.mark.asyncio
async def test_concurrent_scheduler_runs_claim_one_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    now = BASE + W // 2 + 5
    monkeypatch.setattr(limit_warmup_service, "utcnow", lambda: _at(now))
    repo = FakeWarmupRepo()
    sender = LimiterSender(UpstreamLimiter(), [now])
    accounts = [_account("acc_1"), _account("acc_2")]
    selected = accounts[1]

    async def run_once() -> None:
        await LimitWarmupService(repo, FakeRequestLogsRepo(), sender=sender).run_after_usage_refresh(
            accounts=[selected],
            stagger_accounts=accounts,
            stagger_short_window_eligibility={"acc_1": True, "acc_2": True},
            settings=_settings(
                limit_warmup_windows="secondary",
                limit_warmup_staggered_idle_enabled=True,
                limit_warmup_cooldown_seconds=0,
            ),
            before_primary={selected.id: _sliding(selected.id, now - 61)},
            before_secondary={},
            after_primary={selected.id: _sliding(selected.id, now - 1)},
            after_secondary={},
            refresh_started_at=_at(now - 2),
        )

    await asyncio.gather(run_once(), run_once(), run_once())

    assert [account_id for account_id, _ in sender.sent] == ["acc_2"]
    assert [(row.window, row.reset_at) for row in repo.rows] == [("primary_idle", BASE + W)]


@pytest.mark.asyncio
async def test_account_added_and_removed_mid_cycle_never_double_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    accounts = [_account("acc_1"), _account("acc_3")]
    simulation = _new_simulation(monkeypatch, accounts)
    simulation.limiter.window_minutes["acc_2"] = 300
    await simulation.run(BASE, BASE + W // 2 + 120)
    assert len(_sends_for(simulation, "acc_3")) == 1

    # acc_2 joins between them in sort order; acc_3 moves to index 2.
    accounts.insert(1, _account("acc_2"))
    await simulation.run(BASE + W // 2 + 120, BASE + W)
    # acc_3 was already pre-started this grid cycle: no second send for it.
    assert len(_sends_for(simulation, "acc_3")) == 1

    await simulation.run(BASE + W, BASE + 2 * W)
    for index, account_id in enumerate(("acc_1", "acc_2", "acc_3")):
        cycle_sends = [at for at in _sends_for(simulation, account_id) if at >= BASE + W]
        assert len(cycle_sends) == 1, account_id
        _assert_in_slot(cycle_sends[0], index=index, cohort_size=3)

    # Removing acc_2 moves acc_3's slot earlier than the window it is still
    # running, so acc_3 skips one cycle rather than touching an active window,
    # then settles on the two-account spacing.
    accounts.pop(1)
    await simulation.run(BASE + 2 * W, BASE + 4 * W)
    assert [at for at in _sends_for(simulation, "acc_3") if BASE + 2 * W <= at < BASE + 3 * W] == []
    for index, account_id in enumerate(("acc_1", "acc_3")):
        cycle_sends = [at for at in _sends_for(simulation, account_id) if at >= BASE + 3 * W]
        assert len(cycle_sends) == 1, account_id
        _assert_in_slot(cycle_sends[0], index=index, cohort_size=2)
    rows = [(row.account_id, row.reset_at) for row in simulation.repo.rows]
    assert len(rows) == len(set(rows))


@pytest.mark.asyncio
async def test_paused_and_opted_out_accounts_are_neither_warmed_nor_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    accounts = [
        _account("acc_1"),
        _account("acc_2", status=AccountStatus.PAUSED),
        _account("acc_3", enabled=False),
        _account("acc_4"),
    ]
    simulation = _new_simulation(monkeypatch, accounts)

    await simulation.run(BASE, BASE + W)

    assert _sends_for(simulation, "acc_2") == []
    assert _sends_for(simulation, "acc_3") == []
    (first_at,) = _sends_for(simulation, "acc_1")
    (fourth_at,) = _sends_for(simulation, "acc_4")
    _assert_in_slot(first_at, index=0, cohort_size=2)
    _assert_in_slot(fourth_at, index=1, cohort_size=2)
    for account in accounts:
        assert account.reset_at is None and account.blocked_at is None


def test_cohort_membership_is_deterministic_and_skips_unsafe_states() -> None:
    accounts = [
        _account("acc_c"),
        _account("acc_a"),
        _account("acc_rate_limited", status=AccountStatus.RATE_LIMITED),
        _account("acc_quota", status=AccountStatus.QUOTA_EXCEEDED),
        _account("acc_paused", status=AccountStatus.PAUSED),
        _account("acc_deactivated", status=AccountStatus.DEACTIVATED),
        _account("acc_reauth", status=AccountStatus.REAUTH_REQUIRED),
        _account("acc_opted_out", enabled=False),
        _account("acc_weekly"),
    ]
    deleted = _account("acc_deleted")
    deleted.delete_requested_at = _at(BASE)
    accounts.append(deleted)
    eligibility = {account.id: account.id != "acc_weekly" for account in accounts}

    cohort = limit_warmup_service._stagger_cohort(accounts, short_window_eligibility=eligibility)
    reversed_cohort = limit_warmup_service._stagger_cohort(
        list(reversed(accounts)), short_window_eligibility=eligibility
    )

    # Transient blocks keep their slot so a rate limit does not reshuffle phases.
    assert cohort == ["acc_a", "acc_c", "acc_quota", "acc_rate_limited"]
    assert reversed_cohort == cohort
    # An excluded account with unknown eligibility does not hold the cohort.
    assert (
        limit_warmup_service._stagger_cohort(
            accounts, short_window_eligibility={key: value for key, value in eligibility.items() if key != "acc_paused"}
        )
        == cohort
    )
    # An includable account with unknown eligibility does.
    assert (
        limit_warmup_service._stagger_cohort(
            accounts, short_window_eligibility={key: value for key, value in eligibility.items() if key != "acc_a"}
        )
        is None
    )


def test_grid_slots_are_stable_and_evenly_spaced() -> None:
    cohort = ["acc_3", "acc_1", "acc_2"]
    offsets = []
    for account_id in ("acc_1", "acc_2", "acc_3"):
        offset = next(
            due.slot_offset_seconds
            for second in range(BASE, BASE + W, INTERVAL)
            if (due := limit_warmup_service._staggered_idle_due(account_id, cohort, now=_at(second))) is not None
        )
        offsets.append(offset)
    assert offsets == [0, 6_000, 12_000]

    # The slot depends only on the UTC grid and the cohort, not on when it is asked.
    later = limit_warmup_service._staggered_idle_due("acc_2", ["acc_1", "acc_2"], now=_at(BASE + 7 * W + W // 2))
    assert later is not None
    assert later.slot_offset_seconds == W // 2
    assert later.cycle_end == BASE + 8 * W


def test_grid_uses_the_observed_window_duration() -> None:
    window_seconds = 3_600
    start = 1_000 * window_seconds
    due = limit_warmup_service._staggered_idle_due(
        "acc_2", ["acc_1", "acc_2"], now=_at(start + 1_800), window_seconds=window_seconds
    )
    assert due is not None
    assert due.slot_offset_seconds == 1_800
    assert due.cycle_end == start + window_seconds


def test_catch_up_window_keeps_slots_disjoint() -> None:
    for cohort_size in (2, 3, 5, 10, 50):
        assert _catch_up(cohort_size) <= max(2 * INTERVAL, W // (2 * cohort_size))
    late = limit_warmup_service._staggered_idle_due("acc_2", ["acc_1", "acc_2"], now=_at(BASE + W // 2 + _catch_up(2)))
    assert late is None


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        # Two sliding observations: the window has not started.
        (_sliding("a", BASE), _sliding("a", BASE + 60), True),
        # Jitter within tolerance is still sliding.
        (_sliding("a", BASE, jitter=-25), _sliding("a", BASE + 60, jitter=20), True),
        # The previous window ended before the new observation (genuine reset).
        (_sample("a", observed=BASE, reset_at=BASE + 30), _sliding("a", BASE + 60), True),
        # The previous window is still running: a new reset that looks
        # sliding is ambiguous with a window real traffic just started.
        (_sample("a", observed=BASE, reset_at=BASE + 600), _sliding("a", BASE + 60), False),
        # No corroborating observation yet.
        (None, _sliding("a", BASE + 60), False),
        # Out-of-order samples.
        (_sliding("a", BASE + 120), _sliding("a", BASE + 60), False),
        # A fixed reset deadline is an active window.
        (_sliding("a", BASE), _sample("a", observed=BASE + 60, reset_at=BASE + 10_000), False),
        # Outside the sliding tolerance.
        (_sliding("a", BASE), _sliding("a", BASE + 60, jitter=45), False),
    ],
)
def test_not_started_inference(before: UsageHistory | None, after: UsageHistory, expected: bool) -> None:
    assert limit_warmup_service._short_window_not_started(before=before, after=after) is expected


async def _single_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    after: UsageHistory | None,
    before: UsageHistory | None = None,
    refresh_started_at: datetime | None,
    staggered: bool = True,
) -> list[tuple[str, int]]:
    now = BASE + W // 2 + 5
    monkeypatch.setattr(limit_warmup_service, "utcnow", lambda: _at(now))
    sender = LimiterSender(UpstreamLimiter(), [now])
    service = LimitWarmupService(FakeWarmupRepo(), FakeRequestLogsRepo(), sender=sender)
    accounts = [_account("acc_1"), _account("acc_2")]
    await service.run_after_usage_refresh(
        accounts=[accounts[1]],
        stagger_accounts=accounts,
        stagger_short_window_eligibility={"acc_1": True, "acc_2": True},
        settings=_settings(limit_warmup_windows="secondary", limit_warmup_staggered_idle_enabled=staggered),
        before_primary={"acc_2": before or _sliding("acc_2", now - 61)},
        before_secondary={},
        after_primary={"acc_2": after} if after is not None else {},
        after_secondary={},
        refresh_started_at=refresh_started_at,
    )
    return sender.sent


@pytest.mark.asyncio
async def test_fresh_sliding_sample_at_slot_is_warmed(monkeypatch: pytest.MonkeyPatch) -> None:
    now = BASE + W // 2 + 5
    sent = await _single_evaluation(monkeypatch, after=_sliding("acc_2", now - 1), refresh_started_at=_at(now - 2))
    assert [account_id for account_id, _ in sent] == ["acc_2"]


@pytest.mark.parametrize(
    "refresh_offset",
    [None, 0],
    ids=["no-refresh-start", "sample-older-than-refresh"],
)
@pytest.mark.asyncio
async def test_stale_usage_never_triggers_a_warmup(monkeypatch: pytest.MonkeyPatch, refresh_offset: int | None) -> None:
    now = BASE + W // 2 + 5
    refresh_started_at = None if refresh_offset is None else _at(now + refresh_offset)
    sent = await _single_evaluation(
        monkeypatch, after=_sliding("acc_2", now - 1), refresh_started_at=refresh_started_at
    )
    assert sent == []


@pytest.mark.parametrize(
    "after",
    [
        _sliding("acc_2", BASE + W // 2 + 4, used=5.0),
        _sample("acc_2", observed=BASE + W // 2 + 4, reset_at=None),
        _sample("acc_2", observed=BASE + W // 2 + 4, reset_at=BASE + W // 2 + 4 + 90_000, window_minutes=1_500),
        None,
    ],
    ids=["used-above-idle-threshold", "missing-reset", "long-nonstandard-window", "missing-sample"],
)
@pytest.mark.asyncio
async def test_ineligible_samples_are_not_warmed(monkeypatch: pytest.MonkeyPatch, after: UsageHistory | None) -> None:
    sent = await _single_evaluation(monkeypatch, after=after, refresh_started_at=_at(BASE + W // 2 + 3))
    assert sent == []


@pytest.mark.asyncio
async def test_staggered_idle_remains_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    now = BASE + W // 2 + 5
    sent = await _single_evaluation(
        monkeypatch, after=_sliding("acc_2", now - 1), refresh_started_at=_at(now - 2), staggered=False
    )
    assert sent == []


@pytest.mark.asyncio
async def test_recent_manual_warmup_suppresses_the_scheduled_prestart(monkeypatch: pytest.MonkeyPatch) -> None:
    now = BASE + W // 2 + 5
    monkeypatch.setattr(limit_warmup_service, "utcnow", lambda: _at(now))
    repo = FakeWarmupRepo()
    await repo.try_create_attempt(
        account_id="acc_2", window="manual", reset_at=now - 600, model="m", attempted_at=_at(now - 600)
    )
    sender = LimiterSender(UpstreamLimiter(), [now])
    accounts = [_account("acc_1"), _account("acc_2")]
    await LimitWarmupService(repo, FakeRequestLogsRepo(), sender=sender).run_after_usage_refresh(
        accounts=[accounts[1]],
        stagger_accounts=accounts,
        stagger_short_window_eligibility={"acc_1": True, "acc_2": True},
        settings=_settings(limit_warmup_windows="secondary", limit_warmup_staggered_idle_enabled=True),
        before_primary={"acc_2": _sliding("acc_2", now - 61)},
        before_secondary={},
        after_primary={"acc_2": _sliding("acc_2", now - 1)},
        after_secondary={},
        refresh_started_at=_at(now - 2),
    )
    assert sender.sent == []
