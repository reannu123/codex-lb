# Tasks

- [x] Detect not-started short windows from consecutive samples; never warm active windows or stale samples.
- [x] Anchor stagger slots on an epoch-aligned UTC grid with even spacing and a bounded catch-up period.
- [x] Build the cohort from short-window-eligible accounts using per-slice remembered eligibility (no cross-account usage reads).
- [x] Add the pinned, `accounts:write`-gated manual endpoint with an atomic rolling cooldown, in-flight guard, and retry after failure.
- [x] Add the confirmed "Warm up now" action with quota/limitations copy.
- [x] Add unit, API integration (SQLite and PostgreSQL), and frontend tests with mocked upstream.
- [ ] Hosted PR CI green on the final head.
- [ ] Verify staggering and manual warm-up against a non-production deployment of the test image.
