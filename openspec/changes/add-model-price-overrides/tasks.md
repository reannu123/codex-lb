## 1. Effective pricing and persistence

- [x] 1.1 Add catalog provenance through live merge, bundled and built-in selection, and last-good restore. Verify v1 cache compatibility, newer-bundle precedence, partial refresh, compatible tier supplementation, and offline restart.
- [x] 1.2 Add an additive SQLite/PostgreSQL migration for exact-ID base overrides and recorded subscription cost data. Verify migration topology on current main and upgrade/downgrade with legacy NULL, zero, and positive rows.
- [x] 1.3 Compose exact overrides with existing upstream matching and tier precedence. Cover exact case folding, dated and alias independence, unknown minor IDs, override-only IDs, cached-input zero and inheritance, Priority/Fast, Flex, long-context threshold boundaries, and multipliers.

## 2. Future request accounting and retained history

- [x] 2.1 Capture and carry the admission price view through canonical subscription HTTP, streaming and bridge, WebSocket, retry, and delayed persistence paths, including limit-free keys and image relabeling. Verify an override committed mid-request cannot change the in-flight view, an admitted request on a peer sees the commit after processing invalidation, and signed owner forwards preserve the selected pricing.
- [x] 2.2 Use the pinned view in budget estimation, direct usage recording, and settlement. Cover requested versus upstream tier, unknown hold, explicit zero, positive sub-microdollar rounding, cancelled or failed requests, and exactly-once settlement. Verify source-backed text and audio retain their own pricing and request logging.
- [x] 2.3 Write unrounded subscription cost outcomes and read recorded totals/components. Keep upstream-only repair for eligible legacy NULLs, with bounded rollup mirroring and retry/restart coverage. Prove local saves/clears and catalog updates preserve recorded unknown, zero and positive rows, rolled-up values, and settled limit counters.

## 3. Settings and request display

- [x] 3.1 Add dashboard settings routes and Settings → Model prices. Cover permitted reads, write authorization, source and scope labels, exact known unpriced IDs, validator boundaries, atomic replacement, clear/reset, auditing, restart persistence, and query refresh after mutation.
- [x] 3.2 Render request-time missing-price, unavailable usage, unclassified legacy missing, exact zero, and tiny positive values in the request table/details. Verify the external API preserves raw nullable totals and that known-cost aggregates read recorded estimates.
- [x] 3.3 Verify the end-to-end flow with synthetic complete-usage `gpt-6.2-sol` traffic through the HTTP route and a stubbed upstream: missing catalog rates, a hypothetical override save, tier and settlement behavior, persistence across reload and restart, and clear back to catalog or missing, with earlier requests unchanged. Inspect the real dashboard before and after override changes, and verify the request path issues no query against the override table.

## 4. Verify the implemented change

- [x] 4.1 Run focused backend and frontend suites, migration lint/topology checks, and strict OpenSpec validation. Verify the implementation against the change requirements before syncing specs and archiving.

## Verification evidence (2026-11-22, rebased on `279a24ca`)

- 1.1: `tests/unit/test_pricing_provenance.py` drives scheduler startup against a temporary data dir. It covers offline restart without a usable cache (missing, corrupt, or unsupported schema) labeling bundled and built-in prices, a v1 last-good cache newer than the bundle winning with `last_good_cache` labels, a newer bundle beating an older cache while keeping cache-only models, and live merge plus partial refresh keeping per-model sources. Compatible tier supplementation is covered by existing catalog tests.
- 1.3: `tests/unit/test_price_overrides.py` covers case folding, cached-input zero, explicit Priority/Fast and Flex precedence, the Priority multiplier on override base rates, the long-context threshold boundary and Flex uplift, and override-only IDs. It also covers unknown minor IDs staying missing (never priced through the legacy `gpt-5` family), dated siblings, and alias independence in both directions: an alias override leaves its target alone, and a target override leaves the alias on upstream resolution.
- 2.1: HTTP (including a mid-request save), WebSocket per turn, WebSocket retry on another account, signed owner forwards that reuse one reader, rejected forwards that recover locally, image relabeling, and limit-free keys all keep the admission view across a mid-request save. Peer reload goes through the invalidation poller. The image, forward-retry, and WebSocket-retry tests fail when the request-scoped binding is bypassed.
- 2.2: Route settlement with an override uses catalog Priority and Flex rates when requested and reported, and the override when the upstream reports standard. Unknown, zero, tiny-positive, cancelled, failed, and replayed-finalization cases are covered. A same-ID Model Source keeps its own text and audio pricing while a subscription override exists for that ID.
- 2.3: A recorded missing price stays NULL across an override and a later upstream rate. An interrupted repair rolls back raw rows and every rollup, then a restarted scheduler repairs each eligible row exactly once at upstream-only rates. A save, a catalog change, and a clear leave the folded account, API-key, hourly, demand, and report rollups, settled reservations, limit counters, recorded components, and request-log API values unchanged.
- 4.1: SQLite focused backend suites pass with 791 tests and 1 PostgreSQL-only skip. PostgreSQL 16 passes 23 pricing, migration, repair, bridge, WebSocket, and Model Source tests. The frontend Settings and request-table suites pass 407 tests. Ruff, ty, the architecture scripts, migration topology, and `openspec@1.11.0` strict validation pass. Spec sync and archive wait for maintainer approval.
- 3.3: An SQLAlchemy engine listener observes the whole request and its persistence and finds no statement against `model_price_overrides`. Synthetic `gpt-6.2-sol` route traffic covers save, zero, tiny positive, clear-to-missing, tier settlement, and unchanged history. The earlier local browser pass covered save, zero, six-decimal values, restart persistence, override over catalog, and clear to catalog or missing.
- Finding outside this change: settlement converts with `int(cost_usd * 1_000_000)`, which already exists on `main`. A float total such as 0.0047 USD settles as 4,699 µ$. Tests use float-exact rates, and the conversion is left unchanged here.

## Deferred verification

- A single combined live session (real dashboard, live synthetic traffic, and a process restart in one run) is out of scope for this change. Each part is verified separately above, and the combined run moves to rollout verification for the deployed image.
