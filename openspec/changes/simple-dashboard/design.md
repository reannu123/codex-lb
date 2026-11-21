## Context

See [proposal.md](proposal.md). The worktree matches upstream main at `72630bbf`. [Phase 1 PR #1](https://github.com/reannu123/codex-lb/pull/1) adds the confirmed, pinned manual warmup flow. The API-key model already distinguishes unrestricted from scoped-empty after account deletion, while the legacy PATCH derives scope from list length.

## Goals / Non-Goals

- Compose an operator view with existing data, permissions, dialogs, and transport lifecycles.
- Make account scope a reversible admission control for authenticated keys. Keep proxy authentication policy, landing defaults, automatic warmup policy and production rollout outside Phase 2.

## Decisions

### Use the existing navigation and feature boundaries

Add `/simple-dashboard` in `ADVANCED_NAV_ITEMS` so the existing Advanced menu, responsive navigation, and route guard handle it. Use `dashboard:read` at the route and gate each section by its feature access. Accounts use `accounts:read`; manual warmup also needs `accounts:write`. Key reads need `api_keys:read`; key PATCH uses the existing dashboard write guard. Controls that need account IDs also need account-read access. Preserve the native editor's other permitted fields when account reads are unavailable. Settings and ordinary Request Logs use the dashboard session guard. Use the existing dashboard write capability for routing and retain permission-dependent log facets and conversation access. An unavailable section should neither fetch its protected data nor block the other sections.

Use the existing Accounts query and account-card quota/status rendering, adapting the same AccountSummary as needed. Share the narrowest existing presentation and action code that fits. Derive exact date/time with browser-local formatting and the live countdown from one parsed reset instant per reported window. Retain existing normalization for weekly-only and monthly-only accounts. Put PR #1's confirmation and mutation behind both account surfaces, sharing pending/error feedback and server cooldown. Refresh existing account/overview queries on success using the established invalidation paths.

Reuse `useApiKeys` and `ApiKeyEditDialog`. The cards and the native editor's scope controls use the same PATCH semantics. Own the card's scope draft until Save and show saved and pending states distinctly. In all-accounts mode, the first account switched off seeds a selected set from currently listed eligible-to-assign accounts minus that account. All individually selected remains a fixed list. Return to dynamic all-accounts mode only by selecting “Use all accounts, including future accounts”. Warn inline when a saved empty selection will deny traffic. After a failed or ambiguous save, reload committed server state and keep the user able to recover. Never retry by dropping the explicit fields.

Reuse `useSettings` and the existing routing strategy labels, validation and settings cache. Send a narrow versioned update with the current `expectedVersion`. Preserve the required account picker and same-write `singleAccountId` when selecting single-account mode. Share the existing Request Logs hook, filters and table composition from `DashboardPage`, extracting only the smallest common panel if needed. Keep its query contract, recent filters, pagination and privacy behavior.

### Extend the existing key PATCH

Add one optional `accountScopeUpdate` object to the existing PATCH. Inside it, reuse the response field names for the desired boolean and array, with an `expected` object carrying the prior boolean and array. Mode true stores the requested list including an empty list. Mode false requires an empty list and restores unrestricted mode. Reject invalid combinations, including explicit updates mixed with the legacy top-level assignment field. Keep legacy list-only `null` or `[]` as unrestricted and legacy nonempty lists as scoped. A PATCH without a scope update or assignment list leaves scope alone. Key creation and response shapes keep their current contract.

Keeping explicit updates inside an object lets a legacy server ignore the new payload without processing its empty list as a legacy clear. Scope saves must verify the returned persisted tuple before claiming success. An older writer may still accept unrelated fields without applying scope, so match the frontend to compatible management writers before using the combined edit flow.

Compare normalized sets plus mode inside the same serialized transaction as flag and assignment replacement. Use existing key and account locking and SQLite writer/retry patterns. Serialize with legacy assignment writes and deletion, revalidate target accounts under the deletion invariant, and return a dashboard `409` scope conflict for a changed baseline. A stale edit cannot re-add a deleting account. Keep scope and unrelated changes in one PATCH transaction. An untouched editor omits all scope fields; on a conflict show the saved state, retain unrelated draft edits, and require the operator to review and reapply scope. An editor open during a refetch must keep its original scope baseline. Legacy clients retain their existing unconditional assignment writes.

### Observe scope at admission

Define admission for this change as the fresh scope decision for a new logical unit of proxy work. A scope commit must be visible to admission reads beginning after the commit, including on other replicas. Keep the existing API-key invalidation and local cache updates, but use a committed primary-backed policy read at authenticated proxy API admission (including metadata reads) wherever the present data can be stale. A check only for cached scoped keys misses unrestricted-to-empty saves. Read flag and assignments from one committed snapshot. Reuse the current key-policy read and per-message WebSocket refresh where they meet that guarantee, and consolidate reads only where the same admission already has a fresh policy. Keep pure in-memory bridge account-health reuse checks and avoid re-reading on every chunk or retry.

Deny empty scope before dispatch, source selection, affinity reuse, or reservation/lease acquisition. Use the route's existing OpenAI-style error serialization with a stable proposed `api_key_account_scope_empty` code, a clear message, and HTTP 403 where headers have not been sent. On established transports use their existing per-request error forms. Apply scope to new work on open native WebSockets, local and forwarded bridge requests, and owner-bound or sticky continuation. A forwarded new admission must carry or revalidate a trusted current decision before using an upstream session. Keep owner checks for narrowed nonempty scopes. Audit account control, reset-credit and proxy warmup routes, plus Realtime create and attach. Treat protocol frames that continue already admitted work as part of that work, and treat new response creation on an open Responses connection as a separate admission. An open Realtime sideband keeps its connect-time access until it disconnects, as on `main`. Its scope applies when the next voice connection opens. A single-account global setting, a preferred or file-pinned owner, a durable bridge binding and model-source fallback cannot override the deny. Requests admitted earlier keep their request scope and existing ownership, retry and settlement rules. Rejecting a later unit must not close a shared transport or affect unrelated pending responses.

## Risks / Trade-offs

- A fresh read adds work to keyed admissions. Measure query count and routing latency against representative HTTP and WebSocket traffic. Reuse an already-fresh lookup and keep admission independent from usage history and per-chunk processing.
- A mixed-version fleet can still admit work using stale policy. An old PATCH handler can ignore the explicit update and fail to apply it. Keep the new UI and explicit payloads away from old writers and admission replicas. Serve the new UI only after both paths are upgraded, and remove it before any downgrade.
- Auth-disabled paths that currently ignore Bearer credentials continue to do so. Surface that scope affects authenticated key traffic and keep the existing API-key auth control in its current home.
- An account added after a fixed selection is saved stays outside that selection. A deleted final assignment stays scoped-empty, including if a matching account is later imported.

## Migration Plan

Reuse stored keys, flags and join rows with no schema or backfill. Recheck the live Phase 1 merge head and its permission/endpoint contract before implementation. Verify every reachable management writer and routing replica can enforce the contract before exposing scope saves in a shared environment. Coordinate any rollback to an older fleet with an admission drain if scoped-empty guarantees still apply. Never broaden a key as a rollback step. Production actions require separate user approval.
