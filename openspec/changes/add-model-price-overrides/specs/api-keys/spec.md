## MODIFIED Requirements

### Requirement: GPT-5.6 usage cost pricing matches the current published rates

When computing new API-key usage, request-log, reservation, or aggregate cost for canonical GPT-5.6 models, the system MUST use effective rates from the model-price-settings capability, including the validated active pricing catalog and offline fallbacks specified by upstream-metadata and any applicable exact local base override. Existing non-NULL historical request costs MUST remain unchanged when the active price catalog changes.

The `priority` and `fast` service-tier aliases MUST use explicit catalog Priority rates when present. Long-context rates MUST apply only above the catalog's explicit input-token threshold. Explicit tier-specific long-context prices MUST take precedence over legacy Flex multipliers. Upstream fallback for model aliases with a version or snapshot suffix MUST preserve canonical resolution when an exact catalog entry is absent. Upstream fallback for bare `gpt-5.6` MUST resolve to Sol.

Batch rates and cache-write rates MUST NOT be used without corresponding proxy request and usage fields.

#### Scenario: Sol uses a refreshed rate
- **GIVEN** the active catalog specifies Sol standard input/cached/output rates of `4 / 0.4 / 20` USD per million tokens
- **WHEN** a standard-tier `gpt-5.6-sol` request uses 200,000 input and 1,000,000 output tokens without cached input
- **THEN** its token cost is `$20.80`

#### Scenario: Terra standard usage uses the current rate
- **GIVEN** the active catalog specifies Terra standard input/output rates of `2 / 12` USD per million tokens
- **WHEN** a standard-tier `gpt-5.6-terra` request has 200,000 input tokens and 1,000,000 output tokens without cached input
- **THEN** the token cost is `$12.40`

#### Scenario: Luna Fast and Flex usage use their tier rates
- **GIVEN** the active catalog specifies Luna Priority input/cached/output rates of `0.4 / 0.04 / 2.4` and Flex rates of `0.1 / 0.01 / 0.6` USD per million tokens
- **WHEN** a `gpt-5.6-luna` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **AND** the request uses `priority` or `fast`
- **THEN** the token cost is `$2.444`
- **WHEN** the same usage uses `flex`
- **THEN** the token cost is `$0.611`

#### Scenario: Terra standard long-context usage uses the current long-context rate
- **GIVEN** the active catalog specifies Terra long-context input/cached/output rates of `4 / 0.4 / 18` USD per million tokens above 272,000 input tokens
- **WHEN** a standard-tier `gpt-5.6-terra` request has 300,000 input tokens, 50,000 cached input tokens, and 100,000 output tokens
- **THEN** the token cost is `$2.82`

#### Scenario: Versioned aliases use canonical GPT-5.6 pricing
- **WHEN** the requested model is `gpt-5.6-luna-2026-07-13`
- **THEN** cost accounting resolves it to the `gpt-5.6-luna` price entry

## ADDED Requirements

### Requirement: Distinguish unknown rates from a known zero in cost reservations

Subscription cost reservations MUST use the existing conservative fallback for an unresolved pricing estimate. They MUST reserve zero for a known zero estimate and one microdollar for a positive estimate below one microdollar. Final subscription settlement MUST retain existing truncation to integer microdollars, release or reconcile the held amount exactly once, and distinguish a missing estimate from a priced zero before conversion to the ledger unit.

#### Scenario: Unknown, zero, and sub-microdollar estimates
- **WHEN** eligible requests under a cost limit have an unresolved price, a known zero estimate, and a positive estimate below one microdollar
- **THEN** admission uses the conservative fallback, zero, and one microdollar, respectively
- **AND** settlement reconciles the reservation once and preserves the distinct request-log cost outcomes
