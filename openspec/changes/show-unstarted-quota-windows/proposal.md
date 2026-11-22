# Proposal

## Why

A paused account can display a ticking 5h countdown derived from a sample that described an unstarted window. The countdown suggests traffic started a window at the time of the last poll.

## What Changes

- Expose the latest normalized primary sample's sliding-reset classification and each normalized window's observation time on account summaries.
- Show “Not started” for sliding primary samples and the observation time for quota rows whose accounts are excluded from sampling.

## Capabilities

### Modified Capabilities

- `account-quota-presentation` covers unstarted primary windows and frozen quota snapshots.

## Impact

The account summary API, dashboard cards and table, and Accounts list and usage panel consume display metadata. The classification shares the existing timing rule with limit warm-up.
