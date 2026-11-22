# Spec Delta

## ADDED Requirements

### Requirement: Account summaries describe quota observations

Account summaries SHALL expose the recorded time of each normalized quota sample as an ISO 8601 timestamp, or null when absent. They SHALL flag the latest normalized primary sample when its reset is within 30 seconds of its recorded time plus its window duration, using five hours when duration is unknown.

#### Scenario: Latest sample has a sliding primary reset
- **WHEN** the latest normalized primary sample reports a reset within the inclusive sliding tolerance
- **THEN** the summary exposes the sample's recorded time and sets the primary unstarted flag

#### Scenario: Fixed reset or absent primary sample
- **WHEN** the latest normalized primary sample is missing timing data or has a reset outside the sliding tolerance, or the account has no primary window
- **THEN** the summary leaves the primary unstarted flag false

### Requirement: Account quota rows distinguish observations from live countdowns

The dashboard account card and table and the Accounts list row and usage panel SHALL show “Not started” for a flagged primary sample. For paused, reauthentication-required, and deactivated accounts, those surfaces SHALL replace reset countdowns with the corresponding sample time where available.

#### Scenario: Unstarted primary window on a sampled account
- **WHEN** a sampled account has a flagged primary sample
- **THEN** the primary row shows “Not started” without a reset countdown or reset time

#### Scenario: Frozen quota observations
- **WHEN** an account is paused, requires reauthentication, or is deactivated
- **THEN** each displayed quota row with a sample time shows its own observation time without a reset countdown
- **AND** a flagged primary row also shows “Not started”

#### Scenario: Running window on a sampled account
- **WHEN** a sampled account has a displayed primary window with a fixed reset
- **THEN** its quota row displays the existing reset countdown
