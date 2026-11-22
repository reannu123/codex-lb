## Why

The dashboard promises that “Min usage %” controls reset-confirmed warm-up, but the scheduler can send a probe after a reset at any pre-reset usage.

## What Changes

- Require the selected window's pre-reset usage to meet or exceed the saved minimum before a reset-confirmed warm-up is eligible.
- Preserve reset detection, rate-limit recovery, post-reset availability, and the existing warm-up policies for other triggers.

## Capabilities

### Modified Capabilities

- `usage-refresh-policy` enforces the saved minimum for reset-confirmed warm-up.

## Impact

The saved dashboard setting takes effect on the next warm-up evaluation. Its default remains 99%. Existing settings rows already store this value.
