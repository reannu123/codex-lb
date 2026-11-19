## MODIFIED Requirements

### Requirement: Staggered idle warm-up pre-starts rolling primary windows

When staggered idle warm-up is enabled globally and an active opted-in account has a freshly refreshed eligible short-window primary usage sample at or below the idle threshold, the scheduler MUST assign a deterministic account slot across the observed short-window duration. It MUST exclude accounts with a missing, invalid, or long-window-only sample from the stagger cohort.

For a fresh, not-yet-started sample whose upstream `reset_at` is approximately the observation time plus the window duration, the scheduler MUST use a stable UTC window grid for slot eligibility and the durable idle-attempt identity; successive sliding `reset_at` observations MUST NOT indefinitely defer a nonzero slot. For fixed, already-started windows, the scheduler MUST preserve the upstream reset anchor. Deduplication MUST prevent repeat idle sends in a scheduling cycle.

#### Scenario: Sliding 5-hour reset reaches the second of two slots
- **GIVEN** two safe, opted-in accounts with eligible 300-minute usage windows
- **AND** each poll reports the second account's `reset_at = observed_at + 18000`
- **WHEN** the scheduler reaches the second deterministic 150-minute offset
- **THEN** the second account is due
- **AND** later polls in the same stable grid cycle MUST NOT send another idle attempt

#### Scenario: Weekly-only accounts do not consume short-window slots
- **GIVEN** one opted-in account has an eligible short primary window
- **AND** two other opted-in accounts have only long-window usage samples
- **WHEN** the scheduler builds the stagger cohort
- **THEN** only the eligible short-window account MUST receive a short-window slot

#### Scenario: Existing active quota window retains its anchor
- **GIVEN** a sampled short-window reset deadline does not slide with the latest observation
- **WHEN** the scheduler evaluates the stagger slot
- **THEN** the actual upstream reset deadline MUST remain the scheduling anchor

## ADDED Requirements

### Requirement: Operators may request an account-pinned manual limit warm-up

The dashboard MUST expose an `accounts:write`-protected `POST /api/accounts/{account_id}/limit-warmup/manual` endpoint and an account-level action. The action MUST require an active account with per-account warm-up enabled, send a single minimal Responses request with the existing warm-up model/prompt/sender directly through that account, and persist an attempt and request log. The endpoint MUST NOT consume reset credits or change quota-window reset metadata. A single account MUST have at most one manual attempt per five-minute UTC bucket, including concurrent requests.

A successful response MUST indicate that the upstream warm-up request completed, not assert that the rolling quota window started. The dashboard SHOULD clearly communicate this distinction and prompt for confirmation before consuming quota.

#### Scenario: Operator manually warms a selected account
- **WHEN** an authorized operator confirms the manual action for an active, enabled account
- **THEN** exactly one request is submitted to that account's warm-up sender
- **AND** the result is persisted and returned without reporting a verified quota reset

#### Scenario: Duplicate manual click is deduplicated
- **WHEN** multiple manual requests arrive for one account within a five-minute UTC bucket
- **THEN** only one upstream request MAY be submitted
- **AND** later requests MUST return a conflict without submitting another request

#### Scenario: Disabled or unsafe account is rejected
- **WHEN** the account is not active or has warm-up disabled
- **THEN** the manual warm-up request MUST be rejected without sending upstream traffic
