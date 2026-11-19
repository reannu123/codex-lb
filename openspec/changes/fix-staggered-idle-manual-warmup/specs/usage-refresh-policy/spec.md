## MODIFIED Requirements

### Requirement: Reset-confirmed limit warm-up

The system SHALL support an optional limit warm-up mechanism that is disabled by default. When enabled globally and for an account, background usage refresh MAY send one minimal upstream Responses request after it confirms that a selected quota window moved into a newly available reset window. Eligibility SHALL depend on a real reset transition and the configured post-reset availability gate, not on whether the previous window was exhausted. The legacy `limit_warmup_exhausted_threshold_percent` setting MUST NOT gate reset-confirmed eligibility.

Background usage refresh MUST complete any applicable blocked-status reconciliation before warm-up evaluation. Candidate evaluation and the sender's fresh preflight check MUST both require the account to be `active`; paused, deactivated, `reauth_required`, `rate_limited`, and `quota_exceeded` accounts MUST NOT receive warm-up traffic. When a reset-confirmed recovery uses persisted transition evidence, warm-up SHALL reuse that same before/after pair so the new account/window/reset tuple enters the ordinary durable deduplication path.

The configured `limit_warmup_cooldown_seconds` SHALL gate only staggered idle warm-up candidates. It MUST NOT suppress a reset-confirmed candidate for a distinct account/window/reset tuple, which remains protected by the durable atomic attempt claim for that tuple.

#### Scenario: Warm-up follows a real reset regardless of prior usage
- **GIVEN** limit warm-up is enabled globally and for an active account
- **AND** the account's previous usage sample for a selected window reports any usage below or at exhaustion
- **WHEN** background usage refresh records a newer sample that proves a real reset for that window and satisfies the configured availability gate
- **THEN** the system sends at most one warm-up request for that account/window/reset tuple

#### Scenario: Staggered idle cooldown does not suppress a distinct reset tuple
- **GIVEN** an account has a recent warm-up attempt inside `limit_warmup_cooldown_seconds`
- **AND** background usage refresh confirms a different selected account/window/reset tuple
- **WHEN** reset-confirmed warm-up evaluates the new tuple
- **THEN** the staggered idle cooldown MUST NOT suppress that candidate
- **AND** the durable attempt claim MUST still prevent another send for an already claimed identical tuple

#### Scenario: Warm-up is skipped unless reset is confirmed
- **GIVEN** limit warm-up is enabled globally and for an account
- **WHEN** background usage refresh records a newer available sample without a real selected-window reset transition
- **THEN** the system MUST NOT send a reset-confirmed warm-up request for that sample

#### Scenario: Warm-up is not triggered by upstream reset_at timestamp jitter
- **GIVEN** limit warm-up is enabled globally and for an account
- **WHEN** background usage refresh records a newer sample whose `reset_at` advanced by less than 60 seconds as upstream timestamp jitter
- **THEN** the system MUST NOT send a warm-up request for that account/window/reset tuple

#### Scenario: Warm-up is opt-in and safe by default
- **GIVEN** background usage refresh is preparing to evaluate limit warm-up candidates
- **WHEN** global limit warm-up is disabled
- **OR** the account is not opted in
- **THEN** background usage refresh MUST NOT send warm-up traffic

#### Scenario: Warm-up uses fresh opt-in state after usage refresh
- **GIVEN** an account was loaded before a background usage refresh cycle
- **AND** the account's limit warm-up opt-in changes while the refresh cycle is running
- **WHEN** the scheduler evaluates warm-up candidates after writing usage samples
- **THEN** the scheduler MUST evaluate the latest persisted opt-in value rather than the stale in-session account object

#### Scenario: Warm-up respects unsafe account states
- **WHEN** an account is paused, deactivated, `reauth_required`, rate-limited, quota-exceeded, or in an auth-refresh failure path
- **THEN** limit warm-up MUST NOT send traffic for that account

#### Scenario: Reset recovery completes before warm-up
- **GIVEN** an opted-in Free account is `rate_limited` and has qualifying monthly reset evidence
- **WHEN** marker-guarded recovery succeeds
- **THEN** the scheduler first persists the account as `active` and clears its block markers
- **AND** only then may it evaluate the same monthly reset tuple for warm-up

#### Scenario: Recovery race prevents warm-up from stale evidence
- **GIVEN** reset evidence makes a blocked account appear recoverable
- **AND** a concurrent write changes its status or block markers before recovery persists
- **WHEN** the recovery compare-and-set misses
- **THEN** the stale scheduler snapshot remains ineligible for warm-up

#### Scenario: Sender rejects an account re-blocked after candidate creation
- **GIVEN** an active account produced a valid warm-up candidate
- **AND** the account becomes blocked before upstream warm-up traffic begins
- **WHEN** the sender reloads the account state
- **THEN** it does not send the warm-up request

#### Scenario: Warm-up attempts are durable and deduplicated
- **WHEN** multiple refresh workers observe the same account/window/reset candidate
- **THEN** the database permits at most one persisted attempt for that tuple
- **AND** later refresh cycles skip that tuple after a prior attempt exists

#### Scenario: Persisted recovery evidence shares the warm-up tuple
- **GIVEN** a scheduler restart causes recovery to use a persisted monthly before/after transition
- **WHEN** the recovered active account reaches warm-up evaluation
- **THEN** warm-up derives the candidate from that same transition's new reset deadline
- **AND** an existing attempt for the account/monthly/reset tuple prevents another send

#### Scenario: Staggered idle warm-up pre-starts rolling primary windows
- **GIVEN** limit warm-up and staggered idle warm-up are enabled globally
- **AND** an active account is opted into limit warm-up and belongs to the short-window stagger cohort
- **AND** its primary sample written by the current refresh slice reports a short window (any duration over 24 hours is not eligible) with `used_percent` at or below `limit_warmup_idle_threshold_percent`
- **AND** that sample reports `reset_at` within 30 seconds of its observation time plus the window duration (defaulting to 300 minutes when duration metadata is missing)
- **AND** the account's previous primary observation either reported the same sliding shape or described a window whose `reset_at` had passed by the new observation
- **AND** no prior warm-up attempt places the account inside the configured cooldown
- **WHEN** background usage refresh evaluates that account at or after its slot and within the slot's catch-up period
- **THEN** the system MUST attempt to send one minimal upstream warm-up request for that account
- **AND** the durable attempt identity MUST be the account, the `primary_idle` window, and the end of the current UTC grid cycle, so no other staggered idle warm-up is sent for that account in that cycle across refreshes, restarts, or replicas

#### Scenario: Stagger slots are evenly spaced on the UTC grid
- **GIVEN** the short-window stagger cohort has N accounts sorted by account id
- **WHEN** the scheduler computes slots
- **THEN** grid cycles MUST start at whole multiples of the window duration since the Unix epoch
- **AND** the account at sorted index `i` MUST have slot offset `i * window / N` within each cycle
- **AND** a slot MUST be claimable only from its offset until its catch-up period ends, where the catch-up period is the larger of two refresh intervals and the smaller of 15 minutes and half the slot spacing
- **AND** for two eligible 300-minute accounts the slots MUST be 150 minutes apart

#### Scenario: Stagger cohort contains only short-window-eligible accounts
- **GIVEN** opted-in accounts whose latest primary sample reports a short window, a window longer than 24 hours, or no sample at all
- **WHEN** the scheduler builds the stagger cohort
- **THEN** only accounts with a short-window primary sample MUST receive slots
- **AND** accounts that are paused, deactivated, `reauth_required`, opted out, or pending deletion MUST NOT receive or hold slots
- **AND** `rate_limited` and `quota_exceeded` accounts MUST keep their slot without receiving warm-up traffic while blocked
- **AND** cohort membership and slot order MUST NOT depend on account enumeration order
- **AND** while the short-window eligibility of any includable account is unknown, the scheduler MUST NOT send staggered idle warm-ups

#### Scenario: An active short window is never warmed by the stagger
- **GIVEN** an account's primary sample reports a `reset_at` that does not track its observation time, or its previous observation described a window that had not yet ended
- **WHEN** the scheduler evaluates staggered idle warm-up
- **THEN** it MUST NOT send a staggered idle warm-up for that sample
- **AND** real traffic that starts a window MUST NOT cause any staggered idle warm-up until that window has ended and the account's next slot is reached

#### Scenario: Stale usage never triggers a staggered idle warm-up
- **GIVEN** the selected account's primary sample was not written by the current refresh slice
- **WHEN** the scheduler evaluates staggered idle warm-up
- **THEN** it MUST NOT send a staggered idle warm-up for that account

#### Scenario: Staggered idle warm-up is skipped for accounts with real usage
- **GIVEN** staggered idle warm-up is enabled globally
- **AND** an active opted-in account has a short-window primary usage sample with `used_percent` above the configured `limit_warmup_idle_threshold_percent`
- **WHEN** background usage refresh evaluates that account
- **THEN** the system MUST NOT send staggered idle warm-up traffic for that account

#### Scenario: Staggered idle warm-up remains opt-in
- **GIVEN** limit warm-up is enabled globally and for an account
- **AND** staggered idle warm-up is disabled
- **WHEN** background usage refresh observes an idle short-window primary sample that is not a reset-confirmed transition
- **THEN** limit warm-up MUST NOT send synthetic traffic for that idle sample

### Requirement: Background usage refresh is staggered across accounts

Background usage refresh MUST distribute account refresh attempts across the fixed 60-second usage refresh interval (`USAGE_REFRESH_INTERVAL_SECONDS` in `app/core/usage/refresh_policy.py`, which also derives the 180-second usage freshness horizon) instead of refreshing every eligible account in one burst. Background usage refresh MUST always run; the request-path refreshes (account import, post-`usage_limit_reached` request refresh) MUST NOT be gated by an operator switch, and `CODEX_LB_USAGE_REFRESH_ENABLED` / `CODEX_LB_USAGE_REFRESH_INTERVAL_SECONDS` are removed settings that startup reports and ignores. Each scheduler slice MUST attempt at most one eligible account. Over a full cycle, all eligible accounts SHOULD be considered once.

Each slice MUST select its account before reading usage history and MUST scope its latest-usage lookups, updater input, warm-up candidate evaluation, and recoverable-status evaluation to that selected account. The scheduler MAY retain the full eligible account roster only to choose the deterministic rotation and calculate staggered warm-up phases, and MAY remember each account's short-window stagger eligibility from that account's own earlier slices; neither MUST cause usage-history reads, upstream refresh attempts, warm-up sends, or status mutations for an unrelated account in the slice. A selected-account refresh failure MUST NOT trigger same-slice fallback to another account. Database sessions used to load scheduler state MUST close before upstream network I/O begins, and concurrent follow-up work MUST NOT share an `AsyncSession`.

#### Scenario: Scheduler refreshes one account per slice

- **GIVEN** two active accounts are eligible for usage refresh
- **WHEN** the scheduler runs consecutive refresh slices
- **THEN** the first slice attempts one account
- **AND** the second slice attempts the other account
- **AND** cache invalidation for usage-derived routing state runs at the cycle boundary

#### Scenario: Unrefreshable accounts are skipped by scheduler rotation

- **GIVEN** one account is active
- **AND** one account is deactivated
- **AND** one account requires re-authentication
- **WHEN** the scheduler builds the refresh rotation
- **THEN** only the active account is considered

#### Scenario: Selected slot scopes usage history and follow-up work

- **GIVEN** two eligible accounts have stored primary, secondary, and monthly usage
- **AND** the first account is selected for the current scheduler slice
- **WHEN** the scheduler reads before/after usage and evaluates warm-up and recoverable status
- **THEN** every usage-history lookup is filtered to the first account
- **AND** only the first account is passed to usage refresh, warm-up candidate evaluation, and recoverable-status evaluation
- **AND** the second account cannot be mutated or contacted during that slice

#### Scenario: Warm-up phase cohort does not widen evaluation scope

- **GIVEN** multiple warm-up-enabled accounts participate in staggered-idle phase calculation
- **AND** one account is selected for the current usage-refresh slice
- **WHEN** refreshed usage is evaluated for warm-up
- **THEN** the phase calculation retains the eligible fleet cohort
- **AND** cohort eligibility comes from each account's own earlier slices, not from usage-history reads for other accounts in this slice
- **AND** only the selected account can create a warm-up attempt or send warm-up traffic

#### Scenario: Selected-account failure does not fail over within the slice

- **GIVEN** two accounts are eligible for scheduler rotation
- **AND** the first account is selected
- **WHEN** that account's usage refresh fails
- **THEN** the scheduler does not attempt the second account in the same slice
- **AND** the second account remains eligible for its normal later slice

#### Scenario: Scheduler session closes before selected-account network work

- **GIVEN** the scheduler loaded the account roster and selected account usage
- **WHEN** the selected account's upstream refresh starts
- **THEN** the scheduler read session is already closed
- **AND** any concurrent warm-up follow-up owns an independent database session

## ADDED Requirements

### Requirement: Operators may send an account-pinned manual limit warm-up

The dashboard MUST expose `POST /api/accounts/{account_id}/limit-warmup/manual`, gated by `accounts:write`, and a "Warm up now" account action that asks for confirmation. The endpoint MUST send at most one minimal Responses request with the configured warm-up model and prompt through the selected account only, never through load-balancer selection or another account. It MUST require an existing, `active` account that is not pending deletion, and MUST NOT require the automatic warm-up opt-ins.

#### Scenario: Operator manually warms a selected account
- **WHEN** an authorized operator confirms the manual action for an active account
- **THEN** exactly one upstream request is sent with that account's credentials and upstream route
- **AND** no other account is contacted, including when the request fails

#### Scenario: Manual warm-up does not depend on automatic warm-up opt-in
- **GIVEN** an active account with global or per-account limit warm-up disabled
- **WHEN** an authorized operator confirms the manual action
- **THEN** the request is sent and the account's opt-in setting is unchanged

#### Scenario: Inactive or unauthorized requests do not send traffic
- **WHEN** the account is not `active` (`409` `manual_warmup_account_not_active`), does not exist or is pending deletion (`404`), or the caller has no session (`401`) or lacks `accounts:write` (`403`)
- **THEN** the endpoint rejects the request without sending upstream traffic or creating an attempt

### Requirement: Manual warm-up attempts are deduplicated by a rolling cooldown

Manual attempt claims MUST be atomic on SQLite and PostgreSQL. A pending or succeeded manual attempt for the account within the previous 300 seconds MUST reject a new request with `409` `manual_warmup_cooldown`, and a pending warm-up attempt of any kind started within 300 seconds MUST reject it with `409` `manual_warmup_in_progress`. A failed manual attempt MUST NOT block an immediate retry.

#### Scenario: Double click and concurrent requests send one request
- **WHEN** several manual requests for one account arrive within 300 seconds, including concurrently or across a five-minute clock boundary
- **THEN** only one upstream request is sent
- **AND** the other requests return `409` without contacting upstream

#### Scenario: Failed manual warm-up can be retried
- **GIVEN** a manual warm-up attempt failed
- **WHEN** the operator retries immediately
- **THEN** a new attempt is claimed and sent

#### Scenario: A scheduled warm-up in flight blocks a manual one
- **GIVEN** a staggered or reset-confirmed warm-up attempt for the account is pending
- **WHEN** the operator requests a manual warm-up
- **THEN** the endpoint returns `409` `manual_warmup_in_progress` without sending

### Requirement: Manual warm-up results are recorded without claiming a quota reset

Each manual send MUST persist a `manual` attempt and a `limit_warmup` request log attributed to the selected account. A completed upstream request MUST return `200` and MUST NOT be presented as a confirmed quota-window start or reset; a failed or interrupted send MUST mark the attempt failed and return `502` `manual_warmup_failed`. The action MUST NOT consume reset credits, write usage history, or change account status or quota-reset metadata.

#### Scenario: Successful manual warm-up is attributed to the selected account
- **WHEN** a manual warm-up completes upstream
- **THEN** the attempt is `succeeded` and the request log carries the selected account id and the warm-up request id
- **AND** the dashboard reports a completed request, not a started quota window

#### Scenario: Manual warm-up leaves quota metadata unchanged
- **WHEN** a manual warm-up succeeds or fails
- **THEN** the account's status, `reset_at`, and `blocked_at` are unchanged and no usage history is written
