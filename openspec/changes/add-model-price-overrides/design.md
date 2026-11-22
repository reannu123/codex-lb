## Context

[Phase 3 pricing audit](context.md) traces the current resolver, budgets, request logging, and the GPT-6.2 Sol evidence. [Upstream metadata](../../specs/upstream-metadata/spec.md), [API keys](../../specs/api-keys/spec.md), and [dashboard authorization](../../specs/admin-auth/spec.md) govern existing behavior.

## Goals / Non-Goals

**Goals:** Make subscription base prices and their origin visible. Let operators set a durable exact-ID price for future usage, with consistent accounting and stable history.

**Non-Goals:** Tier and long-context overrides, changing configured Model Source billing, route or model discovery changes, upstream invoice reconciliation, and historical local repricing.

## Decisions

### Settings and validation

Add a section within Settings and a model-price collection under `/api/settings`, modeled on context-window overrides. List the union of validated catalog/built-in exact IDs, known subscription model-registry IDs, exact subscription IDs observed in a bounded recent-log lookup, and existing overrides. Never show a configured external provider's price as a subscription price. Return the exact ID, resolved catalog ID, effective base triple, inherited base triple, origin of the base triple, cached-input inheritance when applicable, and whether catalog tier/context rates can supersede it. Use source labels for local override, live catalog (provider where tracked), last-good cache, bundled snapshot, built-in, or missing. Restore old cache records with a truthful last-good label. Track origins in memory alongside catalog merges and label restored prices as cache entries with the existing v1 snapshot format. Do not infer a provider from the v1 URL list. The matching ID and pricing layer answer different questions.

Use dashboard read authorization for inspection and `require_dashboard_write_access` for changes. Audit successful saves and clears with actor, normalized model ID and action. No change to proxy API-key permissions. Upsert one row per normalized exact ID, replacing all three fields atomically. Accept decimal values from 0 through 1,000,000 USD per million, with up to six fractional digits. Accept explicit zero in any field. Reject absent fields, empty strings, nulls, booleans, negatives, non-finite numbers, excess precision/range, and extra fields. Use a bounded literal identifier with the repo's model-slug convention, case-normalized for identity, and reject pattern syntax and IDs outside the known subscription set. An ID already overridden remains editable even if it ages out of discovery. Delete is an idempotent clear of the whole row. The effective response after clear resolves against the current catalog and can return missing. An empty form field is a validation error, never clear or zero. Send/display decimal rates at their supported precision, independently of the request-cost formatter.

### Exact match and tier behavior

Select the local triple only when the pricing model ID exactly matches its key after case normalization. Canonical ID, dated IDs, and other aliases have independent override keys. Thus a canonical save cannot silently reprice an alias or a dated sibling. Apply the local base triple over the catalog entry found by the unchanged exact/date/longest-alias fallback chain to retain its tier metadata. Give an override-only ID a base-only entry. Existing explicit Priority, Flex and long-context groups still take precedence, and existing Priority multipliers operate on the chosen base. Use the actual upstream tier for settlement where available and the post-policy request tier for estimation. For an override-only ID, all tiers use its base rates until catalog tier metadata becomes available. Show the base scope and applicability of catalog tiers beside the editable fields.

### Durability and request boundary

Store local rates in the shared application DB. Warm an immutable override snapshot during startup and refresh it through the existing settings invalidation poller. Commit the shared invalidation version in the same transaction as the override mutation, then reload the writing process before it responds. Peers apply the update on the next successful poll. Rate resolution does no database or network I/O on the request path. Settings uses committed rows and refreshes the query from the mutation response.

Capture the upstream and override snapshots for the lifetime of an HTTP request or individual WebSocket turn. In-process bridge finalization, retries, and detached persistence carry that view. Cross-replica bridge forwards include an authenticated price for the forwarded model, including a representable missing price. Older peers omit or ignore this optional field during mixed-version rollout and retain their local behavior. The owner uses the origin price when both peers support it. Same-request image relabeling uses the captured local view where the existing route reprices the public model ID. Keep external Model Sources on their existing pricing and settlement path. Existing stale-reservation recovery releases abandoned reservations when no owner can finalize their usage.

Represent unresolved pricing separately from known zero before conversion. At admission use the existing conservative unknown-price fallback only for unresolved pricing, reserve zero for a known zero estimate, and reserve one microdollar when a positive estimate would truncate to zero. At settlement keep existing integer truncation and zero-delta accounting for an unresolved price, with the request estimate marked missing. Ordinary positive settlements retain existing rounding. This keeps cost calculation, display, and ledger units explicit.

### Recorded history

Persist subscription cost status and cost components with the unrounded total in the normal finalization transaction. Distinguish missing price, unavailable usage, and priced. Read historical subscription values from storage. A legacy row with only a total returns that total and omits unavailable components. Legacy NULL remains unavailable until upstream-only repair records a result. Restrict existing automatic repair to legacy unclassified NULLs and resolve against upstream-only pricing. New request-time missing outcomes stay NULL even if a price arrives later. A save or clear never triggers repair, replays settled limits, or modifies rollups. Keep the older Alembic backfill independent of dashboard overrides. New migrations are additive and support both SQLite and PostgreSQL.

Render an explicit missing-price label when the recorded status identifies the cause, distinguish unavailable usage and legacy unknown, render true zero as zero, and show positive values below display precision as a positive threshold or with additional digits. Preserve raw nullable and numeric semantics through the request API. Existing aggregate totals remain sums of recorded estimates and describe known cost only.

## Risks / Trade-offs

- Zero or unusually low overrides affect future cost limits. The form shows inherited values and describes the accounting effect before saving. Auditing provides an operator trail.
- A request may span a save or refresh. Pinning the pricing view at admission also covers limit-free and queued requests, avoiding a split estimate and settlement.
- Restored prices are labeled at the cache layer. Snapshot v1 carries no reliable provider per model.
- Existing legacy rows will lose price components previously inferred from current rates. Their recorded total remains available and future rows carry recorded components.
- The commit-to-poll interval matters across replicas, and mixed-version bridge peers lack a shared price until both sides upgrade. Route coverage must exercise existing cancellation and settlement order.
