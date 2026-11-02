"""Quality checks: when a collection is complete enough to record disappearances."""

from scraper.config import Settings


def segment_ok(
    declared_total: int | None,
    unique_cards: int,
    failed_pages: int,
    settings: Settings,
    prev_active: int = 0,
    drop_runs: int = 0,
) -> tuple[bool, str | None]:
    """A segment is complete if no page failed and the listings collected cover the declared total.

    `prev_active` = the segment's active listings before the run. If today we see far fewer,
    the total declared by the site could be wrong (same page, same fault):
    the segment is not reliable (`suspicious_drop`). If, however, the drop repeats for
    `drop_confirm_runs` consecutive runs (`drop_runs` = previous runs already in a drop), it is
    treated as real (`drop_confirmed`) and the disappearances are recorded.
    Returns (ok, reason). Only ok segments can produce disappearances.
    """
    if failed_pages > 0:
        return False, "failed_pages"
    if declared_total is None:
        return False, "no_declared_total"
    reason = None
    allowed_drop = max(settings.small_segment_max_missing, settings.active_drop_alert * prev_active)
    if prev_active - unique_cards > allowed_drop:
        if drop_runs + 1 < settings.drop_confirm_runs:
            return False, "suspicious_drop"
        reason = "drop_confirmed"
    if declared_total < settings.small_segment_threshold:
        ok = declared_total - unique_cards <= settings.small_segment_max_missing
    else:
        ok = unique_cards / declared_total >= settings.completeness_min
    return (True, reason) if ok else (False, "incomplete")


def active_drop_alert(prev_active: int, now_active: int, settings: Settings) -> bool:
    """True if active listings dropped by more than the threshold compared with the previous run."""
    return prev_active > 0 and (prev_active - now_active) / prev_active > settings.active_drop_alert
