# 0008 — A disappearance is recorded from the list evidence: two consecutive complete collections without the listing

Date: 2026-11-08 · Status: accepted (scraper 0.1.9). Revises [0005](0005-gone-means-sold.md) (which required a conclusive detail-page check) after [0007](0007-missing-listing-404-penalty.md). GitHub issue #2.

## Context

Until 0.1.8 an absent listing changed state only after its detail page had answered: 404 → `removed`, 200 on two checks → `delisted`. Since ~2026-11-02 one request for a missing listing (404) from a GitHub runner puts the IP in penalty for hours (decision 0007), so those checks are now limited to a sample of one per run: at that pace the 300–600 daily disappearances could never be recorded, and the time-to-sell model would have no end dates.

What the data says about the list evidence alone: on 2026-10-31 and 11-01, **3,469 of 3,469** active listings missing from a **complete** segment answered 404 — not one was still online. The false-disappearance scenario that decision 0005 guarded against (a listing pushed across page boundaries while the collection runs) is already covered by requiring the absence on **two consecutive complete collections**: a listing missed by a page shift on one day is seen again the next day, and the count resets.

## Decision

For a listing in `active` state that is absent from a segment **collected completely** today (`segment_ok`, see `disappearance-logic.md`):

- the absence is **counted** (`missing_streak + 1`; `absent_since` = the first day of the absence) whether or not a detail-page check was made;
- on the **second consecutive** counted absence the listing becomes **`delisted`** (`delisted` event, `delisted_date = absent_since`, i.e. the first day of absence). `delisted` is the disappearance for time-to-sell purposes, as before;
- a detail-page check, when made (the sample of decision 0007), can settle it at once: **404/410 → `removed`** (`removed` event; `detail_gone` if already `delisted`). A 200 adds nothing beyond the count; an error leaves the count to the list;
- an **incomplete or missing collection** of the segment changes nothing: the count is neither incremented nor reset (rule 6);
- a listing seen again in the search results goes back to `active`, the count resets (`reappeared` event if it had been `delisted`/`removed`), as before.

`list_last_seen`, `delisted_date` and `detail_gone_date` keep their meaning (decision 0005). The threshold stays `DELIST_AFTER_ABSENT_RUNS = 2`.

## Alternatives considered

- *One absence is enough*: rejected in 0005 and still rejected — page shifts during a 90-minute collection do happen.
- *Three absences*: safer by one more day, but 3,469 of 3,469 checks say two is already conservative; every extra day delays the end date of every sale by a day.
- *Keeping the 404 confirmation as the only path*: impossible at scale from GitHub (0007); a host with a different IP class remains a possible future refinement, not a prerequisite.

## Consequences

- From 0.1.9 the disappearances paused by 0.1.8 are recorded again, one day later than a same-day 404 confirmation would have (the dates are unaffected: `delisted_date` is the first day of absence).
- `removed` becomes rarer (one sampled check per run) and `delisted` becomes the usual terminal state; consumers must treat `delisted` as the sale (they already had to: `type in ('removed', 'delisted')`).
- The `delisted_recheck` tasks compete with the absence checks for the single daily sample and come after them in priority: a `delisted` listing may stay unconfirmed by a 404 for a long time. Acceptable: `removed` is a confirmation, not the signal.
