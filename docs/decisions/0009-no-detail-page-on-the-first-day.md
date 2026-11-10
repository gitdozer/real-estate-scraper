# 0009 — No detail page on the day a listing first appears in the search results

Date: 2026-11-10 · Status: accepted (scraper 0.2.2). Follows [0007](0007-missing-listing-404-penalty.md).

## Context

Since 0.1.8 the detail phase stops at the first 404, because one request for a missing listing puts the runner IP in penalty for hours (decision 0007). On 2026-11-10 the phase stopped after 44 pages: 3 × 404 among the first new listings of the day, then the penalty (2 timeouts). The day before, 4,602 detail pages of new listings had gone through without a single 404.

What the data says (observations and state of 11-10, report of the run):

- the detail queue follows the order of the cards in the search results; the three pages without a result were the 41st–43rd new listings in that order: three **listings by private sellers on page 696 of 739** of Milano sale, with the three highest listing ids of the segment;
- **all 24 cards with the highest ids of the day were by private sellers, on the last pages of their segment**, seen for the first time that day: the site lists freshly inserted private listings at the end of the results;
- the 44 pages that answered 200 had ids inserted the evening before (just above the highest id of the previous run); the five private listings among them were fine. The 4,602 pages of 11-09 were listings at least a day old (the backlog of the 11-02…11-08 failures): **the trigger is not "private" but "inserted a few hours earlier"**;
- the photos of the three listings had been downloaded (6 fingerprints each): the image host serves them before the page exists;
- ten hours later the owner opened one of the three in a browser: the listing was online. The page is published with a delay after the card appears in the search results.

## Decision

The detail page of a listing is **not requested on the day it first appears** in the search results; it is requested from the next day, if the listing is still listed (`plan_details` skips cards without a previous state). Photos are still taken on the first day. The card itself (price, surface, rooms, photo ids, flags) is in the day's observations as before, and the `new` event is recorded on the first day.

**Bootstrap** (a segment with no listing in the state yet) is exempt: every listing is new there, almost all of them online for a long time, and deferring the whole collection by a day would cost more than the one 404 that may stop the phase near the end of the queue.

Detail reasons after the change: `new` = first detail page of a listing seen on a previous day and not marked `first_seen_censored` (even if its card changed in the meantime); `never_detailed` = the same for listings marked `first_seen_censored` (online at bootstrap or seen in the segment's first 7 days). The first live run after the legacy import also applies the rule: the imported listings have pages, the new ones wait a day.

## Alternatives considered

- *Only private listings wait a day*: smaller loss (agency listings the same day), but no evidence that agency feeds publish the page before the card; one 404 is enough to lose the day's detail phase.
- *Newest ids last in the queue*: the 404 would come at the end instead of the start, but it would still come, and the penalty would still hit the sampled absence check after the photos.
- *Keep requesting and detect the penalty*: the first 404 is enough (decision 0007); detection comes too late.

## Consequences

- Detail attributes of new listings arrive one day later than before. Nothing else in the data changes: no schema change, same events, same dates.
- The `gone_samples` of the report (0.2.1) keep telling which listings answer 404; if they stop being first-day private listings, this decision is to be revisited.
