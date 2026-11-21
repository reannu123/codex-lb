## ADDED Requirements

### Requirement: Explicit API-key account scope updates

The existing API-key PATCH SHALL support an optional `accountScopeUpdate` object containing `accountAssignmentScopeEnabled`, an `assignedAccountIds` array, and an `expected` object containing the corresponding prior values. The mode and assignment set MUST commit atomically with the rest of a successful PATCH.

#### Scenario: Save an explicit empty account scope atomically
- **GIVEN** a key is scoped to account A
- **WHEN** an authorized PATCH specifies true, an empty assignment array, and the matching baseline
- **THEN** the returned and subsequently read key reports true with an empty assignment array
- **AND** no concurrent reader sees an unrestricted intermediate state

### Requirement: Explicit scope payloads are validated

With explicit mode true, the assignment array MAY be empty. With explicit mode false, the array MUST be empty. The server SHALL reject incomplete or contradictory explicit scope payloads, including an explicit update combined with top-level `assignedAccountIds`, using the existing dashboard validation envelope.

#### Scenario: Contradictory explicit payload is rejected
- **WHEN** a PATCH combines `accountScopeUpdate` with top-level `assignedAccountIds`, or sends explicit mode false with a nonempty array
- **THEN** the server returns the existing dashboard validation envelope and commits nothing

### Requirement: Explicit API-key scope saves are conditional

The server MUST compare the supplied baseline against committed scope, ignoring ordering, inside the same transaction as the scope update. A changed baseline MUST return HTTP 409 through the dashboard error envelope without committing any part of the PATCH. An explicit scope save MUST reject unknown or deleting account IDs. Account deletion MUST remove assignments while preserving scoped mode, including when it removes the last assignment.

#### Scenario: Stale save cannot overwrite a newer scope
- **GIVEN** two editors open the same key before one saves a different account scope
- **WHEN** the second submits an explicit scope change with its original baseline
- **THEN** the whole PATCH returns 409 and the newer scope remains committed

#### Scenario: Last assignment is deleted while editing
- **GIVEN** an editor opens a key scoped only to account A
- **WHEN** A is deleted before the editor saves
- **THEN** the key remains scoped-empty and a stale submission cannot restore A
- **AND** importing an account later does not reopen the key


### Requirement: Legacy API-key scope PATCH semantics remain compatible

Legacy PATCH semantics SHALL remain supported. A list-only nonempty assignment PATCH enables scoping, a list-only empty or null value makes the key unrestricted, and omission of both `accountScopeUpdate` and top-level `assignedAccountIds` preserves stored scope. Existing creation, routes, response fields, and stored scope meanings SHALL remain compatible.

#### Scenario: Legacy management clients retain their behavior
- **WHEN** a legacy client PATCHes only `assignedAccountIds` as a nonempty array, an empty array, or null
- **THEN** the nonempty array scopes the key and the empty array or null makes it unrestricted
- **AND** a subsequent PATCH of only a name or limits preserves its current scope

### Requirement: Empty API-key account scope denies new proxy work

A key with enabled account scope and zero assignments MUST deny all new proxy API requests authenticated with that key. All admissions after the save commits MUST observe that state, including on other replicas and on established connections. The denial MUST apply before upstream dispatch across HTTP, SSE, native WebSocket and the HTTP Responses bridge, including new continuations.

#### Scenario: New work is denied across transport and replica boundaries
- **GIVEN** previously unrestricted key policy is warm on a different replica and the key has a reusable session
- **WHEN** an empty scope is committed and the key starts a new request there
- **THEN** the request receives the scope error without upstream dispatch or fallback
- **AND** the result holds for raw HTTP, streaming HTTP, native WebSocket and bridge requests with or without a continuity owner

### Requirement: Routing state cannot bypass an empty scope

Global routing, preferred or pinned owners, sticky state, bridge aliases, retries and model-source routing MUST NOT bypass an empty account scope. A denied request MUST NOT fall back to, or broaden into, any other account.

#### Scenario: Sticky owner does not reopen a scoped-empty key
- **GIVEN** a key has sticky or previous-response affinity to account A
- **WHEN** its scope is saved empty and the key sends a continuation
- **THEN** the continuation receives the scope error without dispatch to A or any other account

### Requirement: Empty-scope denial uses the existing error envelope

The denial MUST use the existing transport error envelope with a stable code `api_key_account_scope_empty` and an actionable message. The HTTP form SHALL be 403 where an HTTP status is available. The same denial applies to authenticated proxy API reads. Dashboard administration remains available through the dashboard session and its existing permissions. Ordinary endpoints that allow unauthenticated traffic retain their existing authentication rules.

#### Scenario: Denied request receives a stable error
- **GIVEN** a key has a saved empty scope
- **WHEN** the key calls a proxy API over HTTP
- **THEN** the response is 403 with code `api_key_account_scope_empty` in the existing error envelope
- **AND** the operator can still manage the key through the dashboard session

### Requirement: Scope saves preserve admitted work and allow reopening

The save MUST preserve already admitted work and its settlement. Reopening the key by explicitly permitting accounts MUST allow new eligible requests without regenerating the key. Existing affinity and continuity rules SHALL remain in effect after reopening.

#### Scenario: Prior work finishes while later work is denied
- **GIVEN** an admitted response is streaming on a reusable connection before the scope commits
- **WHEN** the key becomes scoped-empty and submits a second request on that connection
- **THEN** the existing response can complete and settle once
- **AND** the second request receives the scope error without closing or reassigning the first response

#### Scenario: An open Realtime sideband is not interrupted by a scope change
- **GIVEN** a Realtime sideband was opened while the key's scope permitted the call's owner account
- **WHEN** the key becomes scoped-empty while the sideband is still open
- **THEN** the proxy SHALL continue relaying client and upstream events on that sideband until it disconnects
- **AND** a new Realtime sideband connection for the key MUST receive the scope error before any upstream connection is made

#### Scenario: Reopened key is limited to the newly permitted account
- **GIVEN** an empty scope has denied new work and an older affinity points elsewhere
- **WHEN** the operator grants account A and submits new work using the same key
- **THEN** only eligible account A is in scope
- **AND** an owner-bound continuation requiring another account follows the existing continuity error path
