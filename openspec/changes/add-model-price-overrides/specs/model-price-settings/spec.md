## Purpose

Expose effective subscription-model base prices and their provenance to dashboard operators, with persistent local overrides and stable recorded cost estimates.

## ADDED Requirements

### Requirement: Inspect effective subscription model prices

Settings → Model prices MUST list exact subscription model IDs from the pricing catalog, known subscription models, recent subscription usage, and existing overrides. Each row MUST show effective standard input, cached-input, and output rates in USD per million tokens, the associated source, and the resolved catalog ID when it differs. The source MUST distinguish local override, live catalog, last-good cache, bundled snapshot, built-in price, and missing. The UI MUST identify cached input inherited from the input rate, show the inherited base rates while a local override is active, and indicate when catalog tier or long-context pricing may take precedence. Missing pricing MUST be represented separately from a numeric zero. Existing dashboard read and write authorization MUST apply to inspection and mutation, respectively.

#### Scenario: Known subscription model without a rate
- **WHEN** an authorized dashboard reader opens Model prices for a known, unresolved subscription ID without an override
- **THEN** its row shows missing price with no numeric rates
- **AND** a read-only dashboard session cannot save or clear a price

#### Scenario: Offline fallback and cached rate inheritance
- **WHEN** the active price is restored from a last-good cache and its cached-input field is absent
- **THEN** Settings shows the effective cached-input rate inherited from input and labels the price as last-good cache

### Requirement: Persist and clear exact model base overrides

A write-authorized dashboard user MUST be able to atomically replace all three base rates for a known literal subscription model ID, or clear the entire override. The system MUST identify override keys case-insensitively and MUST reject unsupported IDs, patterns, missing or invalid values, and extra rate fields. Rates MUST accept finite decimal values from 0 through 1,000,000 inclusive, with at most six fractional digits. Zero MUST be stored and displayed as a rate. Overrides MUST survive restart and upstream price changes, remain editable after discovery changes, and be independent of configured Model Source pricing. A clear MUST be idempotent and immediately expose the current inherited rates or missing-price state. Successful changes MUST be audited with actor and exact model ID.

#### Scenario: Save a triple and clear after refresh
- **WHEN** a write-authorized user saves a valid triple with zero cached input and the catalog later refreshes or the app restarts
- **THEN** the saved values and local provenance remain visible and effective
- **AND** clearing the override resolves against the refreshed catalog

#### Scenario: Invalid rate or target
- **WHEN** a user submits a wildcard, a source-only model, a missing or null field, a negative or non-finite number, excessive precision, or a tier-specific override field
- **THEN** the mutation is rejected and the stored override is unchanged

### Requirement: Apply local rates consistently to new requests

The service MUST capture the effective pricing inputs at logical subscription request admission and use that view for reservation estimates, final settlement, and recorded request estimates, including in-flight retries and deferred finalization. After a save or clear returns successfully, the writing replica MUST use the committed override state for subsequent admissions. Peer replicas sharing the application database MUST apply the mutation after processing its durable settings invalidation. A signed bridge forward between supporting replicas MUST carry the origin price for the forwarded ID. A local triple MUST apply only to its exact pricing ID, independent of other aliases and dated IDs. Requests without an exact override MUST retain existing upstream exact, dated, and alias resolution. Explicit catalog tier and long-context rates MUST retain their existing precedence, and applicable multipliers MUST use the selected base rates. An override-only ID MUST use its base triple in the absence of applicable catalog tier rates. The estimator MUST use the post-policy requested tier and settlement MUST use the effective request tier, preferring the upstream-reported tier when available. Configured Model Source pricing MUST continue to use its source's existing rules.

#### Scenario: Exact override with tier and dated variants
- **GIVEN** a model has catalog Priority rates and an exact local base override
- **WHEN** standard and Priority requests use the overridden ID and a dated sibling has no exact override
- **THEN** eligible standard traffic on the exact ID uses the override, Priority uses the explicit catalog rates, and the dated sibling uses upstream resolution

#### Scenario: Override changes during a request
- **GIVEN** a request is admitted before a rate save or clear commits
- **WHEN** it finalizes after the mutation and a subsequent request is admitted on a peer replica that processed the invalidation
- **THEN** the first request uses its admission pricing view and the subsequent request sees the committed mutation

### Requirement: Preserve and distinguish recorded cost estimates

The service MUST persist the outcome of new subscription cost calculations, including unrounded numeric estimates and available components or the reason an estimate is unavailable. Request-log reads MUST use recorded subscription cost data and MUST preserve legacy stored totals, including zero. A local price mutation MUST NOT rewrite existing rows, historical components, rollups, or settled limits. The request UI MUST distinguish a missing price, unavailable usage, and an unclassified missing legacy estimate from a known zero and a small positive value below display precision.

#### Scenario: History across an override
- **GIVEN** subscription logs contain stored priced estimates, an explicit zero, and a recorded missing-price outcome
- **WHEN** an operator saves or clears an override and then reloads history
- **THEN** all recorded outcomes stay the same
- **AND** a positive recorded cost below display precision is shown as positive rather than zero
