## Why

Operators currently move between Dashboard, Settings, and account and key management surfaces to check quota resets, warm up accounts, and change key routing. Simple Dashboard puts these actions alongside live request activity and gives operators a reversible way to stop new traffic for a key by clearing its eligible accounts.

## What Changes

- Add a separate Simple Dashboard destination under Advanced. Keep the current landing page and existing routes.
- Show account status and quota first, with a countdown and exact browser-local reset date and time for each reported window. Reuse the confirmed manual warmup action from Phase 1.
- Show API-key cards next. Allow independent account toggles and open the native API-key editor from each card.
- Add explicit all-accounts and selected-accounts modes. Saving an empty selection stops new proxy work for that key and allows reopening it by selecting an account again.
- Provide a quick control for the existing global routing strategy and reuse the current Request Logs.

## Capabilities

### New Capabilities

- `simple-dashboard` provides the permission-aware operator view and its controls.

### Modified Capabilities

- `api-keys` gains explicit, conditional scope updates and enforcement for empty scope at request admission.
- `query-caching` requires a committed account-scope read on cached key admissions.

## Impact

- Dashboard navigation, account cards, API-key controls, routing settings, and Request Logs reuse existing surfaces and permission checks.
- The API-key PATCH contract gains an optional scope update object and reuses the persisted scope flag and assignments. Current payloads and data retain their meaning.
- Proxy admission must observe committed scope on new work across replicas and reused transports. Phase 1 must land before implementation adopts the manual warmup contract.
