# Change: Fix sliding-window staggered idle warm-up and expose manual warm-up

## Why
Upstream #1976 documents two defects: a never-started 5-hour window can continually slide its `reset_at` forward so nonzero stagger slots never fire; weekly-only accounts can occupy short-window stagger slots. Operators also need a deliberate one-click warm-up on a selected account without waiting for the scheduler.

## Scope
- Use a deterministic UTC short-window grid only for freshly observed sliding/unstarted samples; retain upstream reset deadlines for fixed, already-started windows.
- Build the stagger cohort from safe, opted-in accounts with an observed eligible short-window sample.
- Reuse the existing audited, account-pinned warm-up sender and durable attempt repository for a manual dashboard action.
- Throttle manual attempts to one per account per five-minute UTC bucket; display request completion without claiming a quota-window reset.
- Add a manual GHCR test-image workflow rather than publishing images from every pull request.

## Non-goals
- Do not modify load-balancer routing, quota pacing, or weekly-window staggering.
- Do not promise that a 2xx warm-up response started a quota window.
- No database schema migration or new required settings.

## Verification
Unit regression tests cover sliding 5h resets, durable deduplication, mixed short/weekly cohorts, and manual request cooldown; UI tests cover manual button eligibility. PR CI must pass before merge.
