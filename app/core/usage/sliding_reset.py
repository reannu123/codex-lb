from datetime import datetime

from app.core.utils.time import naive_utc_to_epoch

DEFAULT_ROLLING_WINDOW_SECONDS = 300 * 60
# Allow for fetch-to-write delay and upstream rounding of reset_after_seconds.
SLIDING_RESET_TOLERANCE_SECONDS = 30


def rolling_window_seconds(window_minutes: int | None) -> int:
    if window_minutes is not None and window_minutes > 0:
        return int(window_minutes) * 60
    return DEFAULT_ROLLING_WINDOW_SECONDS


def reset_slides_with_observation(
    *,
    reset_at: int | None,
    recorded_at: datetime | None,
    window_minutes: int | None,
) -> bool:
    if reset_at is None or recorded_at is None:
        return False
    observed_at = naive_utc_to_epoch(recorded_at)
    return abs(reset_at - observed_at - rolling_window_seconds(window_minutes)) <= SLIDING_RESET_TOLERANCE_SECONDS
