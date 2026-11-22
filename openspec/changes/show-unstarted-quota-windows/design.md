# Design

## Context

The account mapper already chooses which usage history row represents each window. The warm-up stagger compares the recorded time and reset time, then corroborates that timing with an earlier sample before sending traffic.

## Goals

- Pair each quota timing label with the observation used for that row.
- Reuse the stagger's sliding-reset calculation while preserving its eligibility and corroboration rules.

## Decisions

- Take the display classification from one normalized primary sample with zero usage. A completed or skipped sampling run supplies no additional evidence about when a window began.
- Keep the existing expiry and percentage calculations. The UI can still identify an expired sliding sample as “Not started” with an unknown percentage when the mapper has cleared its quota values.
- Format observation times using the dashboard date preference. For example, a paused account last sampled at 20:18 shows “Not started” and “As of” 20:18 instead of a reset countdown.

## Risks / Trade-offs

A window that began moments before a sample can match the tolerance. Positive recorded usage rules out an unstarted window. This classification describes the latest sample and is used only for display. Weekly and monthly rows report their individual sample times because their samples can differ.
