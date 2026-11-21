## 1. Confirm the implementation baseline

- [x] 1.1 After Phase 1 clearance, verify PR #1's merged endpoint, confirmation, cooldown and permission coverage on the intended base. Run the existing manual-warmup API and frontend tests.
- [ ] 1.2 Confirm the Advanced placement and the committed-read deployment plan. Run the dashboard nav budget checker on the chosen base and record an ordinary-route keyed admission baseline for query count and latency.

## 2. Persist scope and enforce it on new work

- [x] 2.1 Extend the existing PATCH and its frontend schema with explicit mode and a conditional scope baseline. Reuse flag and join rows. Verify canonical and trailing-slash collection behavior, existing creation and PATCH payloads, empty/null legacy clears, untouched scope, validation envelopes, old-handler no-op without legacy broadening, reopen, atomic rollback, competing editors and last-assignment deletion on SQLite and PostgreSQL.
- [ ] 2.2 Enforce fresh scope on new authenticated proxy requests before dispatch or reservation, including source-routed paths and local proxy API reads. Verify HTTP/compact, SSE, proxy warmup and account-bound control paths using real route entry points with fake upstreams. Assert the scope-specific envelope, zero upstream work, and no waits, fallback, leases or stranded reservations. Exercise the existing authentication modes and route aliases.
- [ ] 2.3 Verify native WebSocket, Realtime and HTTP bridge entry points, including an open socket, local and forwarded bridge reuse, sticky/previous-response/file-pinned owners and single-account routing. Warm replica B's auth policy before saving on A and assert B denies the next new request without waiting for poller convergence. Verify a concurrent admitted stream finishes and settles once, narrower scope preserves owner checks, and reopening never crosses owners. Measure admission cost against the baseline.

## 3. Compose the dashboard

- [ ] 3.1 Add the guarded Advanced destination and compose existing account card and manual warmup behaviors. Test direct navigation, unchanged default, read/write role differences, both reset formats from one timestamp in a non-server browser timezone including a DST offset, rollover/unknown timestamps, monthly-only accounts, confirmation cancel and shared cooldown feedback.
- [ ] 3.2 Add key cards and wire Edit to the native dialog. Reuse scope state and save semantics in both. Test independent controls, explicit dynamic scope, fixed all-current scope, scoped-empty save/reopen, delete while open, stale dialogs and refetches, rollback/error feedback, and hidden or disabled permission-gated controls.
- [ ] 3.3 Compose the global strategy and Request Logs. Test the same strategy reaches Settings without overwriting unrelated or concurrently changed fields, including single-account selection. Verify log filters, pagination and restricted metadata and facets through both dashboard views.

## 4. Verify and document

- [x] 4.1 Run strict OpenSpec validation and the relevant dashboard, proxy, permission and simplicity checks. Capture comparable before/after screenshots using the same seeded data and viewport, with an after screenshot showing the empty scope and both reset formats. Confirm the old landing remains reachable and the Advanced entry works on desktop and narrow screens.
- [ ] 4.2 Record operator behavior and rollout/rollback sequencing in the owning OpenSpec context and any published documentation linked to it. Verify before archiving. Keep production changes pending separate approval.
