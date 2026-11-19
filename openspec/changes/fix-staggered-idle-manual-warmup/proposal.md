# Change: Fix sliding-window staggered idle warm-up and add manual warm-up

## Why

Upstream #1976 describes two defects in staggered idle warm-up. A short window
that has not started can slide its `reset_at` forward on every poll, so no
stagger slot except index 0 is ever reached. Weekly-only accounts also take
short-window stagger slots. Operators additionally need a deliberate,
confirmed way to send one warm-up to a chosen account without waiting for the
scheduler.

## What Changes

- Detect a not-started short window from consecutive samples and schedule its
  stagger slot on an epoch-aligned UTC grid. Use the grid cycle as the durable
  dedupe identity.
- Never send a staggered warm-up into an active (fixed-deadline) window or
  from stale usage.
- Build the stagger cohort only from opted-in accounts with short-window
  eligibility. The scheduler remembers eligibility from each account's own
  slice, so slices still never read other accounts' usage history.
- Add `POST /api/accounts/{account_id}/limit-warmup/manual` and a confirmed
  "Warm up now" action. The request is pinned to the selected account, needs
  `accounts:write`, uses a rolling 300-second cooldown, records an attempt and
  a request log, and does not depend on the automatic opt-in.
- Add a branch-scoped GHCR test-image workflow that publishes only after CI
  passes on the exact commit.

## Non-goals

- No changes to load-balancer routing, quota pacing, or weekly-window
  warm-ups.
- A 2xx warm-up response is never treated as a started or reset quota window.
- No database migration and no new settings.

## Impact

- Specs: `usage-refresh-policy` (Reset-confirmed limit warm-up; Background
  usage refresh is staggered across accounts; new manual warm-up
  requirements).
- Code: `app/modules/limit_warmup`, `app/core/usage/refresh_scheduler.py`,
  `app/modules/accounts/api.py`, `app/dependencies.py`, and the Accounts page.
