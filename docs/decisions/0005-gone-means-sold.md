# 0005 — Gone means sold, with separate dates

Date: 2026-10-25 · Status: accepted

## Context
There is no public data on actual property sales. The user's direct experience (they are house-hunting) is that the time a listing stays online is a good approximation of the time to sell. The "venduto" (sold) / "in trattativa" (under negotiation) labels that agencies sometimes add are too rare to be useful. The common case we must handle is **re-listing**: a listing is taken down and published again under a new ID so that it looks new.

## Decision
- A listing is considered **sold when it disappears** from the site.
- We record **three separate dates**, because "gone from the search results" and "page removed" do not necessarily happen on the same day:
  - `list_last_seen` — the last day the listing appeared in the search results: **this is the end date used for the time to sell**;
  - `delisted_date` — the first day of confirmed absence;
  - `detail_gone_date` — the first day the detail page returns 404.
- An absence is confirmed only if the collection for that segment was complete; a network error never decides anything.
- From day one we collect the signals needed to recognize re-listings after the fact (Phase 2): the agency's internal reference, coordinates, fingerprints of several photos, and the description.
- Target of the price model: the asking price shown in the listing (the last one before the disappearance).

## Alternatives considered
- **Using the "venduto"/"in trattativa" labels**: too rare.
- **Treating a listing as gone the first time it is missing**: pagination shifts while the collection is running (new listings push the others across pages), so this would produce false disappearances.

## Consequences
- Time to sell must be treated as a survival analysis problem with censored data (listings still online; listings already online on the first day of collection, flagged with `first_seen_censored`).
- Details of the logic: [disappearance-logic.md](../disappearance-logic.md).
