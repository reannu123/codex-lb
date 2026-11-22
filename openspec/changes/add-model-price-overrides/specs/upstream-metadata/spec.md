## MODIFIED Requirements

### Requirement: Safe missing-cost repair
The service SHALL automatically fill only legacy unclassified NULL costs for retained subscription request logs with sufficient token usage and recognized upstream pricing. It SHALL resolve repair prices without local overrides and SHALL preserve recorded request-time missing outcomes. It SHALL skip external model-source logs and preserve non-NULL costs, including zero. Repairs SHALL execute in bounded transactions under the fold-state lock and mirror the exact cost deltas into lifetime account/key, hourly usage, quarter-hour demand, and report aggregates according to their existing filters, deduplication, dimensions, and watermark boundaries. A partial index SHALL support the bounded eligible-row scan, and PostgreSQL SHALL build that index concurrently with recovery of invalid interrupted builds. Repeated execution SHALL NOT double-count costs or rewrite request counts, token counts, or admission/limit counters. Unexpected refresh and backfill failures SHALL defer retries independently for five minutes while allowing the other operation to proceed.

#### Scenario: Folded history
- **WHEN** a retained Astra request with NULL cost has already been folded
- **THEN** its raw cost and each affected aggregate gain the same correction atomically
- **AND** pruned history and already priced rows remain unchanged

#### Scenario: Local price is added after a request finishes
- **GIVEN** a legacy subscription row has an unclassified NULL cost and a new subscription row has a recorded missing-price outcome
- **WHEN** only a local override supplies the model price
- **THEN** neither row is repaired
- **AND** if upstream later supplies a valid price, only the legacy row is eligible for repair
