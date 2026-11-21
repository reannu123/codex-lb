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

## Local implementation status (2026-11-22, rebased on `279a24ca`)

Unchecked items have remaining implementation or verification work.

- 1.1: Source labels cover live, last-good cache, bundled, and built-in. No new tests for merge, restore, or partial-refresh provenance.
- 1.2: SQLite and PostgreSQL 16 preserve legacy NULL, zero, and positive costs across upgrade and downgrade. Both engines reapply cleanly over an override table created from ORM metadata, preserving its row. Topology passes against fork main at `cf47701c`. The SQLite test's handwritten bootstrap DDL had omitted `NOT NULL` from `model_id`; the parent had no unrelated schema drift.
- 1.3: Exact-ID override, dated-ID independence, override-only IDs, and the catalog-tier flag are tested. `tests/unit/test_price_overrides.py` covers case folding, cached-input zero, explicit Priority/Fast and Flex precedence, the Priority multiplier on override base rates, the long-context threshold boundary (equal stays standard, one above switches), the Flex long-context uplift, and override-only IDs under Priority and Flex. Unknown minor IDs and alias independence lack a dedicated case.
- 2.1: Admission view is pinned for HTTP (including mid-request save) and WebSocket per turn. Two signed turns on one owner bridge reader verify origin-priced holds, settlement, and persistence delayed past the response. Bypassing the per-turn finalizer bind causes the second charge to reuse the first quote. Peer reload goes through the invalidation poller. An image generation whose override changes mid-stream settles its hold and relabels its log row to `gpt-image-2` at the admission rates. An origin whose signed owner forward is rejected before dispatch quotes the admission price, then recovers locally and records that price despite a save landing during the forward. Both tests fail when the request-scoped binding is bypassed. Limit-free keys and WebSocket retry have no pricing-specific case.
- 2.2: HTTP route tests verify the unknown-price hold, pinned positive settlement, zero hold, one-microdollar minimum hold for a tiny positive estimate, and refunds after cancellation or a failed upstream event. Replaying finalization and release leaves the original charge and limit counter unchanged. Tier composition is verified at the pricing layer (see 1.3); route-level Priority/Flex settlement with overrides, direct accounting, and same-ID Model Source pricing remain open.
- 2.3: A previously recorded missing price stays NULL in storage and the request API while a local override is active and an upstream rate arrives. Repair fills an otherwise equivalent legacy unclassified row at the upstream rate. A repair batch interrupted mid-mirror rolls back raw rows and every rollup; a freshly constructed scheduler restarting at cursor zero repairs each eligible row exactly once at upstream-only rates while a local override is active, leaves a recorded missing-price row NULL, and mirrors rollups once. Preservation of folded rollups and settled counters across a save/clear is structural (mutations never touch them) without a dedicated assertion.
- 3.3: Browser save, zero, six-decimal, restart persistence, override-over-catalog, and clear-to-catalog/missing all verified against a local instance. Synthetic GPT-6.2 Sol requests exercise accounting through the HTTP route with a stubbed upstream. The combined dashboard, traffic, and restart flow and the request-path database-read check remain open.
- 4.1: Focused backend/frontend suites, lint, ty, migration topology, and strict validation pass. Complete requirement coverage remains open as listed above.
