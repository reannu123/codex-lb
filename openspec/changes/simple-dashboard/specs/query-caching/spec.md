## MODIFIED Requirements

### Requirement: Proxy API-key auth caching is invalidation-driven with a TTL backstop

The proxy API-key auth cache MUST be invalidated through the cross-instance cache-invalidation mechanism on every key mutation (create/update/delete/reassignment), and its TTL MUST be at least 60 seconds so interactive request turns can reuse validated key policy. A cached authentication MUST read the current account-scope flag and assignments from one committed snapshot at admission. The read MUST avoid hydrating unrelated key policy, limits, or usage history.

#### Scenario: Key mutations invalidate cached auth promptly

- **GIVEN** an API key validated and cached on an instance
- **WHEN** the key is updated or deleted (on any instance)
- **THEN** the mutation MUST bump the api_key invalidation namespace
- **AND** cached auth data for that key MUST be cleared via the poller, independent of the TTL

#### Scenario: Unchanged keys are served from cache across interactive turns

- **GIVEN** a key validated less than 60 seconds ago with no intervening mutation
- **WHEN** another request authenticates with the same key
- **THEN** validation MUST reuse cached key policy and read current account scope before admitting the request
