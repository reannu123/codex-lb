## Why

Switchboard operators need to see which token rates codex-lb actually uses and supply a local price when the upstream catalog has no suitable entry. Today a missing price can appear as a blank request cost or as zero in budget accounting, and the dashboard offers no way to inspect or correct the rates used for future requests.

## What Changes

- Add **Settings → Model prices** for effective standard input, cached-input, and output rates in USD per million tokens, with source and resolved model ID.
- Allow authorized operators to save or clear a persistent base-rate triple for one exact subscription model ID. A save survives refresh and restart. Clearing restores current catalog resolution, including a missing-price result.
- Apply a consistent pricing view to future request estimates and API-key cost accounting. Preserve recorded history and distinguish missing, exact zero, and small positive costs.
- Keep configured Model Source pricing and existing catalog tier precedence. Phase 3 adds three base-rate fields.

## Verification Scope

Requirements are verified by unit, route, migration, and component tests on disposable SQLite and PostgreSQL stores, plus a local browser pass. One combined live session covering the dashboard, synthetic traffic, and a process restart together is deferred to rollout verification of the deployed image (see `tasks.md`).

## Capabilities

### New Capabilities

- `model-price-settings` covers dashboard inspection, exact-ID overrides, provenance, future request accounting, and cost presentation.

### Modified Capabilities

- `upstream-metadata` keeps automatic missing-cost repair on upstream data while preserving new request-time outcomes.
- `api-keys` allows local base rates for GPT-5.6 and distinguishes unknown pricing from known zero in reservation estimates.

## Impact

Dashboard Settings and request-cost display, pricing resolution and provenance, shared database persistence, subscription request finalization, API-key budgets, and missing-cost repair. No new environment variable or primary navigation item is needed.
