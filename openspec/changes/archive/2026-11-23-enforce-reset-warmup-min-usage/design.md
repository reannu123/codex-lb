## Context

Reset detection serves both the warm-up service and blocked-account recovery. The warm-up service already resolves the effective before and after samples for each selected window.

## Goals / Non-Goals

Use the dashboard's saved minimum to qualify reset-confirmed warm-up. Keep the existing database and settings API contracts.

## Decisions

Check the effective pre-reset sample in reset-confirmed candidate selection. Keep the shared reset detector independent of the setting so a blocked account can recover even when its reset does not qualify for warm-up. A rejected reset candidate does not claim a durable attempt. Initial Free quota, paid-to-Free transitions, staggered idle warm-up, and manual probes retain their own eligibility rules.

## Risks / Trade-offs

Deploying this change activates saved values. With a minimum of 60%, an observed reset from 59.9% usage is skipped and a reset from 60% can warm if the post-reset sample qualifies.
