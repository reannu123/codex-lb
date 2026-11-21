## 1. Effective pricing and persistence

- [ ] 1.1 Add catalog provenance through live merge, bundled and built-in selection, and last-good restore. Verify v1 cache compatibility, newer-bundle precedence, partial refresh, compatible tier supplementation, and offline restart.
- [x] 1.2 Add an additive SQLite/PostgreSQL migration for exact-ID base overrides and recorded subscription cost data. Verify migration topology on current main and upgrade/downgrade with legacy NULL, zero, and positive rows.
- [ ] 1.3 Compose exact overrides with existing upstream matching and tier precedence. Cover exact case folding, dated and alias independence, unknown minor IDs, override-only IDs, cached-input zero and inheritance, Priority/Fast, Flex, long-context threshold boundaries, and multipliers.

## 2. Future request accounting and retained history

- [ ] 2.1 Capture and carry the admission price view through canonical subscription HTTP, streaming and bridge, WebSocket, retry, and delayed persistence paths, including limit-free keys and image relabeling. Verify an override committed mid-request cannot change the in-flight view, an admitted request on a peer sees the commit after processing invalidation, and signed owner forwards preserve the selected pricing.
- [ ] 2.2 Use the pinned view in budget estimation, direct usage recording, and settlement. Cover requested versus upstream tier, unknown hold, explicit zero, positive sub-microdollar rounding, cancelled or failed requests, and exactly-once settlement. Verify source-backed text and audio retain their own pricing and request logging.
- [ ] 2.3 Write unrounded subscription cost outcomes and read recorded totals/components. Keep upstream-only repair for eligible legacy NULLs, with bounded rollup mirroring and retry/restart coverage. Prove local saves/clears and catalog updates preserve recorded unknown, zero and positive rows, rolled-up values, and settled limit counters.

## 3. Settings and request display

- [x] 3.1 Add dashboard settings routes and Settings → Model prices. Cover permitted reads, write authorization, source and scope labels, exact known unpriced IDs, validator boundaries, atomic replacement, clear/reset, auditing, restart persistence, and query refresh after mutation.
- [x] 3.2 Render request-time missing-price, unavailable usage, unclassified legacy missing, exact zero, and tiny positive values in the request table/details. Verify the external API preserves raw nullable totals and that known-cost aggregates read recorded estimates.
- [ ] 3.3 Verify the end-to-end flow using synthetic complete-usage `gpt-6.2-sol` traffic with missing catalog rates. Save a hypothetical override, exercise tier and settlement behavior, refresh and restart, clear the override, and verify earlier requests are unchanged. Inspect the real dashboard before and after override changes and verify pricing adds no request-path database read.

## 4. Verify the implemented change

- [ ] 4.1 Run focused backend and frontend suites, migration lint/topology checks, and strict OpenSpec validation. Verify the implementation against the change requirements before syncing specs and archiving.

## Local implementation status (2026-11-22)

Unchecked items have remaining implementation or verification work.

- 1.1: Source labels cover live, last-good cache, bundled, and built-in. No new tests for merge, restore, or partial-refresh provenance.
- 1.2: SQLite and PostgreSQL 16 preserve legacy NULL, zero, and positive costs across upgrade and downgrade. Both engines reapply cleanly over an override table created from ORM metadata, preserving its row. Topology passes against fork main at `cf47701c`. The SQLite test's handwritten bootstrap DDL had omitted `NOT NULL` from `model_id`; the parent had no unrelated schema drift.
- 1.3: Exact-ID override, dated-ID independence, override-only IDs, and the catalog-tier flag are tested. Flex, Priority multiplier, and long-context boundary cases are not.
- 2.1: Admission view is pinned for HTTP (including mid-request save), WebSocket per turn (reservation and finalization, mutation-checked), internal bridge origin quotes, and signed forward headers. Peer reload goes through the invalidation poller. Image relabeling has no price-specific handling or test.
- 2.2: HTTP route tests verify the unknown-price hold, pinned positive settlement, zero hold, one-microdollar minimum hold for a tiny positive estimate, and refunds after cancellation or a failed upstream event. Replaying finalization and release leaves the original charge and limit counter unchanged. Full route-level verification of tier-specific and direct accounting with overrides and same-ID Model Source pricing remains open.
- 2.3: Unrounded totals/components and cost status are recorded. Repair is limited to legacy unclassified NULLs at upstream-only prices. Rollup mirroring retry/restart is not newly tested.
- 3.3: Browser save, zero, six-decimal, restart persistence, override-over-catalog, and clear-to-catalog/missing all verified against a local instance. Synthetic GPT-6.2 Sol requests exercise accounting through the HTTP route with a stubbed upstream. The combined dashboard, traffic, and restart flow and the request-path database-read check remain open.
- 4.1: Focused backend/frontend suites, lint, ty, migration topology, and strict validation pass. Complete requirement coverage remains open as listed above.
