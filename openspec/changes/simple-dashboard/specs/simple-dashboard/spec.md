## Purpose

Provide a dedicated operator view for account health, key account scope, routing strategy and current proxy request activity.

## ADDED Requirements

### Requirement: Separate permission-aware dashboard destination

The SPA SHALL expose a distinct Simple Dashboard destination to sessions with dashboard read access. It SHALL retain the current root and sign-in landing behavior. The page SHALL order visible sections as accounts, API keys, global routing strategy, and Request Logs. Each section and action MUST apply the permission checks of its existing endpoint and MUST avoid requesting data the viewer lacks permission to read.

#### Scenario: Open Simple Dashboard from navigation
- **WHEN** a dashboard reader selects Simple Dashboard
- **THEN** the browser opens the dedicated view and it is directly addressable
- **AND** visiting the root still opens the existing Dashboard

#### Scenario: View without account or key permissions
- **WHEN** a dashboard reader lacks account and key read permissions
- **THEN** the page shows permitted settings and log surfaces without fetching account or API-key data
- **AND** the reader cannot use the account or key controls

### Requirement: Account cards show quota and reset timing

The page SHALL show account status and remaining 5h and weekly quota when those windows are reported. It SHALL honor normalized quota window labels and presence. Each valid reset timestamp SHALL drive a visible live countdown and an exact date and time in the browser's local timezone with a zone or UTC offset indicator. Missing or invalid reset values SHALL show timing as unavailable. A countdown SHALL stop at zero until a fresh timestamp is reported.

#### Scenario: One instant is rendered two ways
- **GIVEN** the browser runs in a different timezone than the server
- **WHEN** a valid quota reset is displayed
- **THEN** the countdown and localized date/time refer to the same instant
- **AND** a new reported reset updates both values together

### Requirement: Account cards offer confirmed manual warmup

Authorized users SHALL have a per-account Warm up now action using the existing manual warmup eligibility, confirmation, mutation feedback, and server cooldown. Canceling confirmation MUST leave the account untouched.

#### Scenario: Warm up an active account
- **WHEN** an authorized operator confirms Warm up now for an eligible account
- **THEN** the existing manual operation targets that account
- **AND** a second attempt inside the server cooldown surfaces the existing cooldown feedback

### Requirement: API-key cards reuse the native editor

The page SHALL show permitted API-key cards without revealing key secrets. Each card SHALL provide an authorized Edit action that opens the native API-key editor.

#### Scenario: Edit a key from its card
- **WHEN** an authorized operator selects Edit on an API-key card
- **THEN** the existing API-key edit dialog opens for that key
- **AND** no key secret is shown on the card

### Requirement: API-key cards edit account scope drafts

Scope controls on each API-key card SHALL distinguish dynamic all-accounts mode, explicit selected accounts, and a saved empty scope. Choosing “Use all accounts, including future accounts” SHALL explicitly select dynamic scope.

#### Scenario: Stop and reopen a key
- **GIVEN** a key is scoped to one account
- **WHEN** the operator switches that account off and saves
- **THEN** the card shows a saved empty scope and explains that new keyed proxy work is denied
- **WHEN** the operator switches an account back on and saves
- **THEN** the card shows a fixed selection again and newly admitted work can use eligible accounts in that selection

### Requirement: Account toggles change one account at a time

Each toggle SHALL change only the chosen account's membership in the draft. Switching an account off while using all accounts SHALL initialize the fixed selection from currently assignable accounts and remove the chosen account. Selecting every current account individually SHALL keep a fixed selection.

#### Scenario: Turn one account off under dynamic scope
- **GIVEN** a key uses all accounts and accounts A and B are assignable
- **WHEN** the operator switches A off
- **THEN** the draft becomes a fixed selection containing only B

#### Scenario: Explicitly grant future accounts
- **GIVEN** every currently assignable account is selected individually
- **WHEN** a further account is added
- **THEN** it is initially off for the fixed selection
- **WHEN** the operator saves “Use all accounts, including future accounts”
- **THEN** the new account and future accounts are included subject to normal eligibility

### Requirement: API-key scope saves confirm committed state

Saving SHALL persist scope atomically, show pending and committed state distinctly, and show save errors. The UI MUST confirm the returned committed scope before reporting a successful change. A stale scope draft SHALL surface the conflict and require review against current scope before saving again.

#### Scenario: Stale scope draft is rejected
- **GIVEN** an operator has an unsaved scope draft
- **WHEN** another editor commits a different scope and the operator saves
- **THEN** the card shows the conflict and the current committed scope
- **AND** nothing is reported as saved until the operator reviews and saves again

#### Scenario: A successful HTTP response does not confirm the requested scope
- **WHEN** the card or native editor submits a scope change and the successful HTTP response omits either scope field or returns a different scope
- **THEN** the UI shows an account-scope confirmation error and reloads the committed key state
- **AND** the UI does not report the change as saved

### Requirement: Existing routing strategy and request logs are available

The page SHALL allow operators with existing settings write access to change the global routing strategy using its existing choices, validation and conflict handling. Changes SHALL appear on other settings surfaces and preserve unrelated settings. The page SHALL present existing Request Logs with the same data, filters, pagination and access rules as Dashboard.

#### Scenario: Change strategy and inspect requests
- **WHEN** an authorized operator saves a valid strategy in Simple Dashboard
- **THEN** Settings reflects that strategy
- **AND** filtering and paging Request Logs operates on the same records as the existing Dashboard

#### Scenario: Settings change concurrently
- **WHEN** an operator saves a strategy using an outdated settings version
- **THEN** the page shows the conflict and preserves the newer settings
