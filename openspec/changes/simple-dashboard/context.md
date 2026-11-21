## Source checkpoints

- [Upstream main at `72630bbf`](https://github.com/Soju06/codex-lb/tree/72630bbfeee9e3b0d9acfb95e2b1e706b8b0188e) matches the inspected worktree. `components/layout/nav-items.ts` is the five-item core nav budget input, and `App.tsx` owns the default redirect and permission guard.
- [Phase 1 PR #1 inspected head](https://github.com/reannu123/codex-lb/tree/24825dcaa64053aa4992e590667538d3d389d539) wires `AccountActions`, `AccountsPage`, and `useAccounts` to `POST /api/accounts/{account_id}/limit-warmup/manual`. The action warns about quota use. The current PR uses a 300-second rolling manual cooldown and reports an in-progress attempt separately. Recheck those details at the accepted merge head.
- `frontend/src/features/dashboard` contains `AccountCard`, `AccountCards`, `useRequestLogs`, and the table/filter composition in `DashboardPage`. `account-usage-panel.tsx` and `utils/formatters.ts` already format quota resets. [Quota semantics](../../specs/account-quota-presentation/spec.md) cover free-tier monthly windows and refresh continuity.
- `frontend/src/features/api-keys/components/api-key-edit-dialog.tsx` owns the native draft and conditional payload. `app/modules/api_keys/service.py` commits assignment replacement and the mode flag together today and invalidates auth after commit. `app/modules/accounts/repository.py` already removes assignments when marking deletion and leaves the mode flag intact. `test_api_keys_api.py` covers legacy assignment clears, assignment rollback, and no account fallback after deletion.
- `app/core/auth/dependencies.py` serves cached key policy on HTTP hits. The API-key invalidation poller described in [query caching](../../specs/query-caching/context.md) converges asynchronously. The change updates that capability to require a narrow committed read at admission while preserving full-policy caching. The Responses WebSocket mixin already calls `get_key_by_id` for new responses, and the HTTP bridge reuse helper checks the proposed account against key assignments. Existing bridge tests cover scope refresh and owner mismatches. [Account routing](../../specs/account-routing/spec.md) governs eligibility, and [proxy warmup](../../specs/proxy-warmup/spec.md) already derives its account pool from key scope.

## Example

A key scoped to A is opened in both the card and the native editor. The card sends `{"accountScopeUpdate":{"accountAssignmentScopeEnabled":true,"assignedAccountIds":[],"expected":{"accountAssignmentScopeEnabled":true,"assignedAccountIds":["A"]}}}` and receives the scoped-empty state. An already running stream can finish while the next authenticated request gets the scope error. If the stale editor submits an account change against A, it gets a conflict. After refreshing, granting B reopens new traffic on eligible B. A continuation pinned to A still requires A under the existing owner rules.

## Coordination before implementation

- Reconfirm the Phase 1 contract and permission matrix once the owner clears Phase 1. Share the confirmation component and mutation rather than asking Phase 1 to redesign its endpoint.
- Confirm the Advanced placement with the roadmap owner if top-level tab prominence is required. Moving an existing item would change navigation for current users. A sixth core item would need the project's budget approval path.
- Confirm the scope freshness plan with the proxy owner. A measured committed read is the proposed starting point, including warmed authentication caches on a second replica. Asynchronous invalidation alone cannot meet immediate denial. Confirm the mixed-version deployment and rollback sequence separately from this local proposal.
- Confirm operator messaging for installations that allow unauthenticated access. The scope change applies when a request authenticates as the key. Local and explicitly allowlisted anonymous access still follows the existing global auth contract.

## Local verification evidence (2026-11-22)

Two-replica stale-policy check. Two real backend processes (A and B) ran this branch against one fresh
local PostgreSQL 16 database with a shared `encryption.key`. B's keyed policy was warmed with `GET /v1/models`
(200). A then saved an explicit empty scope through `PATCH /api/api-keys/{id}`. B's next request returned
403 `api_key_account_scope_empty` about 3 ms after the save returned, with no poller wait. Both streaming and
non-streaming `POST /v1/responses` on B returned the same 403 before upstream dispatch. A save using the
stale baseline returned 409. Reopening on A made B's next request return 200.

SQLite cannot run this check. A second process on the same SQLite file fails at startup on the SQLite
lifetime lock (`SqliteRunStateLockError`), so multi-replica deployments are PostgreSQL-only by design.

Keyed admission cost, measured on replica B with `GET /v1/models` (cached key, PostgreSQL on loopback,
N=300 sequential requests, two alternating rounds against baseline `24825dca`):

| Build | SQL statements per request | p50 ms | p95 ms |
|---|---|---|---|
| baseline | 3.01 | 4.56 / 5.26 | 5.46 / 6.38 |
| this change | 4.01 | 5.86 / 5.99 | 7.51 / 7.53 |

The one added statement is the committed scope read
(`api_keys LEFT JOIN api_key_accounts WHERE id = ?`) on its own background session. The baseline's
existing per-request reads come from limit enforcement (`is_active`/`expires_at` and limits) and the model
source list. About 2 background statements per second ran while idle, which accounts for the fractional
counts. Cache misses now join assignments instead of issuing a separate selectin query; their cost was not
measured.

Considered reduction: fold the scope read into the limit-enforcement read to save one round trip. Not done.
Enforcement runs later in a separate session and does not feed account selection, so merging would re-thread
fresh scope through every admission call site, including WebSocket, and move the denial point. Re-measure
against a production-like database before deciding. Cache-only checks cannot provide the immediate
cross-replica denial.

Not yet verified locally: forwarded bridge reuse across replicas, WebSocket admission across replicas,
latency on a non-loopback database, and frontend unit coverage for the 3.x edge cases.
