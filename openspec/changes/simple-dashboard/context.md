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

The repeat on base `cf47701c` extended this check to real WebSockets. B warmed the key over
`GET /v1/models` and accepted a native Responses WebSocket before A committed an empty scope.
The next `response.create` on that socket returned the scope error in 6.05 ms, with no poller wait.
A fresh WebSocket handshake on B and B's next model and raw or streaming Responses requests all
returned 403 with the same code. A stale save returned 409, and a valid reopen restored model reads
on B. This used synthetic credentials and a fresh loopback PostgreSQL database, which was removed
after both processes stopped. The WebSocket was open and idle when the scope changed. A repeat also
sent a correctly signed forwarded continuation to B's internal bridge endpoint after the commit and
got the same 403 before bridge owner lookup. The harness generated that request with the normal
forwarding serializer and sent it directly to the receiving app.

Still unverified on two real replicas: automatic ring forwarding with live bridge-session reuse and
completion and settlement of concurrent in-flight work. The loopback latency measurements do not cover
a remote database or a cold key cache.

## Rollout and rollback (operator notes)

Operator-facing summary: `docs/api-keys.md` ("Rolling out and rolling back explicit account scope").

Rollout. Upgrade every replica before operators save scopes from Simple Dashboard. Older replicas parse the
PATCH with Pydantic's default `extra="ignore"`. Checked against `24825dca`: `accountScopeUpdate` is dropped,
`model_fields_set` is empty, and the update is a no-op that returns 200 with the stored scope. The new build
does not need a migration.

Rollback. Keys already saved scoped-empty stay closed on older builds. The baseline fails closed for an
enabled scope with no assignments: `test_select_account_empty_explicit_scope_fails_closed` and
`test_deleted_assigned_accounts_do_not_fall_back_to_other_accounts` pass on `24825dca`. Older builds lose the
`api_key_account_scope_empty` code and the per-admission committed read, so another replica may serve a
cached scope until its key cache refreshes. An older dashboard that saves an empty assignment list makes the
key unrestricted, so after a rollback, reopen keys by assigning accounts.

Scope confirmation. The card and native editor use the same PATCH client. It compares the two explicit
response fields to the desired mode and assignment set before a success toast. If either field is
missing or the tuple differs, it reports a scope confirmation error and refetches the key list. For
example, a scoped key switched to all accounts needs the server to return both `false` and `[]`.
Compatibility defaults used when reading ordinary key responses cannot confirm that write. The older
replica may still apply unrelated fields on a combined edit.

## Verification on `cf47701c`

- The branch's two existing patches survived the rebase unchanged according to `git range-diff`.
  The merged manual warm-up has a 300-second cooldown and an account write permission guard.
- The broad SQLite API-key, proxy, warm-up, permission, and simplicity selection passed (625 tests).
  PostgreSQL API-key and scope-specific bridge, sticky and WebSocket coverage passed (104 tests).
  The focused contract rerun passed 10 tests each on SQLite and PostgreSQL, including null and empty
  legacy clears, name-only edits, invalid explicit scope, contention, and deletion. The 102 API-key
  service and manual warm-up tests also passed.
- The four API-key hook tests passed. The missing-mode and missing-list cases reproduced false success
  before the fix. The hook now reports failure without a success toast, reloads the list, and retains
  the previous scope when the server ignored the update. All nine built-dashboard smoke tests passed,
  including a simulated old PATCH response followed by a real save and reopen on the local backend.
- The two Simple Dashboard screenshot scenarios passed, including New York DST, mobile menu navigation,
  and restricted reads. The existing before/after files were preserved. Backend and frontend lint and
  type checks passed. OpenSpec 1.11.0 strict change validation, all 67 standard specs, and the five-item
  core navigation budget passed.
- The full frontend suite exited 0 with 1,671 tests across 183 files. An earlier selected frontend run
  exited 1 after all assertions passed because a React Query notification reached the navigation test
  during jsdom teardown. The isolated navigation test and the full frontend suite both exited 0 on rerun.
