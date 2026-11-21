# Context: staggered idle warm-up on a UTC grid, and manual warm-up

## Purpose

Staggered idle warm-up exists to keep several accounts' short (5-hour) quota
windows out of phase, so that when one account's window is exhausted another
is part-way through its own. Upstream issue Soju06/codex-lb#1976 showed that
it never worked for any slot except index 0: an account whose short window has
not started reports `reset_at = observed_at + window` on every poll, so a slot
anchored on `reset_at - window` never accumulates elapsed time. Weekly-only
accounts also took slots and pushed the only short-window account off index 0.

The manual action gives an operator a deliberate way to send the same
warm-up request to one chosen account now.

## Decisions

### Anchor: epoch-aligned UTC grid, not persisted per-account anchors

Slots are computed on a grid whose cycles start at whole multiples of the
window duration since the Unix epoch (`cycle_start = now - now % window`). The
cohort, sorted by account id, is spread evenly over each cycle
(`offset = index * window / N`), so two accounts are 150 minutes apart and N
accounts `window / N` apart.

Alternatives considered:

- **Persisted first-observed anchor per account/cycle.** Needs a new table or
  column (an Alembic migration), a write path from the scheduler, cleanup, and
  a rule for when an anchor expires. Two accounts' anchors are independent, so
  they still need a shared reference to be spaced 150 minutes apart, which
  brings the design back to a common grid.
- **UTC grid (chosen).** Stateless, identical on every replica and after every
  restart, no migration, and the spacing is exact by construction. The durable
  dedupe identity is `(account, primary_idle, cycle_end)`, which is the same
  value however many times the scheduler evaluates the account in a cycle.

### Only not-started windows are warmed

A sample is treated as a not-started window only when `reset_at` is within 30
seconds of `recorded_at + window` and the previous observation corroborates it
(it slid too, or the window it described had already ended). Anything else is
treated as an active window and left alone. A warm-up cannot move an active
window; it would only spend quota, so the previous behaviour of warming idle
fixed-deadline windows at their slot is removed.

A single sliding-looking sample is ambiguous with a window that real traffic
started a few seconds earlier, which is why the previous observation is
required. The remaining false-positive case is traffic that starts the window
within 30 seconds of the poll *and* after a corroborating observation; the
worst outcome is one warm-up into a window that just started, which the
account's slot would have sent anyway.

Only a sample written by the current refresh slice may trigger a warm-up.

### Catch-up period

A slot is claimable from its offset for `max(2 * refresh interval,
min(15 min, slot spacing / 2))`. One failed or slow refresh therefore does not
skip the whole cycle, while two slots are never claimable at the same time, so
a restart after downtime cannot fire several accounts together.

Because a pre-started window lasts exactly one window, the next cycle's send
happens slightly after the slot (the poll that first sees the window ended).
That lateness can accumulate by up to one refresh interval per cycle; once it
passes the catch-up period the account skips one cycle and the next send lands
on its slot again.

### Cohort

The cohort is every opted-in, non-deleted account in the refresh rotation
whose latest primary sample has a short window (`window_minutes` missing or
≤ 1440). Rate-limited and quota-exceeded accounts keep their slot so a rate
limit does not reshuffle every other account; paused, deactivated, and
reauth-required accounts leave it, matching the refresh rotation.

The scheduler spec forbids a slice from reading another account's usage
history (#1446), and the prior draft broke that with a roster-wide query on
every slice (the failing CI test). Eligibility is instead remembered in the
scheduler from each account's own slice. After a restart or a leadership
change the map is empty, and the scheduler sends no staggered warm-ups until
every includable account has been observed, which takes one rotation (about
60 seconds). This keeps membership deterministic and prevents slot shuffling
from a partial view.

Membership changes do move slots. The per-cycle dedupe identity prevents a
second send in the same cycle, and an account whose new slot falls inside its
own running window skips one cycle.

### Manual warm-up does not need the automatic opt-in

The per-account toggle opts an account into *automatic* warm-ups. Requiring it
for the manual action would force operators to enable automation (and its
reset-confirmed and idle warm-ups) just to send one request, which is more
synthetic traffic, not less. The manual action has its own consent: an
`accounts:write` permission and a confirmation dialog that says it consumes
quota. The account must still be `active`. The sender's fresh preflight keeps
the opt-in check for automatic warm-ups through a constructor flag.

### Rolling cooldown instead of fixed five-minute buckets

Fixed UTC buckets let two clicks seconds apart on either side of a boundary
both send. The claim now uses the attempt time as the key and a ±299-second
tolerance, which is a rolling 300-second window enforced by the existing
atomic claim (single `INSERT … SELECT … WHERE NOT EXISTS`, plus the per-account
advisory lock on PostgreSQL). Only `pending` and `succeeded` attempts hold the
cooldown, so an auth or transport failure can be retried at once; a crashed
`pending` row blocks for at most five minutes. A pending warm-up of any kind
also blocks a manual one, so an operator cannot stack a manual request on an
in-flight scheduled one. A manual attempt counts as the account's latest
attempt, so it also defers staggered idle warm-ups for the configured cooldown.

### Results and status codes

`200` means the upstream request completed. It is never presented as a
started or reset quota window, since only the next usage refresh can show
that. Upstream or transport failures return `502 manual_warmup_failed` after
the attempt and request log are recorded. Conflicts are `409` with a specific
code, unknown or deleting accounts `404`, and the permission gate gives `401`
and `403`.

### Sessions

The attempt claim and request log run sequentially on the request session.
Token refresh and upstream-route resolution use their own detached background
sessions (`detached_accounts_repo`), so the request session holds no open
write during upstream I/O and the account objects stay usable after those
sessions close.

## Relation to the Quota Planner "Warm Now"

`POST /api/quota-planner/warm-now` belongs to the quota planner. It is
governed by the planner's mode (shadow by default), dry-run, and daily
budgets. The manual action described here uses the limit warm-up pipeline and
records `manual` attempts. The two actions do not share state.

## Example

Two Plus accounts `acc_a` and `acc_b`, both idle, refresh interval 60 s,
grid cycle 10:00–15:00 UTC:

- 10:00–10:02: `acc_a` (index 0) shows sliding samples, its slot opens at
  10:00, and it is warmed once. Its window now ends at about 15:00.
- 12:30–12:32: `acc_b` (index 1, offset 150 min) is warmed. Its window ends
  at about 17:30.
- The usage panel then shows the two 5-hour windows ending about 2.5 hours
  apart. If someone uses `acc_b` at 11:00, its window is active, nothing is
  sent at 12:30, and `acc_b` is pre-started again at its next slot (17:30)
  after that window ends.

## Failure modes and residual risks

- If upstream ever reports a not-started window with a stable `reset_at`, the
  stagger sends nothing for that account. This fails safe.
- The 30-second sliding tolerance assumes upstream reports
  `reset_after_seconds` close to the full window for unused accounts, as seen
  in #1976.
- Slot drift (see Catch-up period) causes an occasional skipped cycle.
- No database migration: the `manual` window value and the grid-keyed
  `primary_idle` rows fit the existing `account_limit_warmups` schema.
