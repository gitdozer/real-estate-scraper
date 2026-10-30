# How listings appear, change and disappear

Code: `packages/scraper/src/scraper/state.py` (the pure function `reconcile`). Underlying decision: [decisions/0005](decisions/0005-gone-means-sold.md) — **a listing that has gone is treated as sold**.

The project's number-one risk is **false disappearances**: a network error, a missing page or a partial collection being recorded as "listing gone". That is why a listing only changes state when there is conclusive evidence.

## States

```
            (appears)                 absent + detail page 404/410
   ┌──────► active ──────────────────────────────────────────► removed
   │          │                                                  ▲
   │          │ absent + detail page 200 on 2 checks             │ detail page 404/410
   │          ▼                                                  │ (weekly recheck)
   │       delisted ─────────────────────────────────────────────┘
   │          │
   └──────────┘  reappears in the search results (from delisted or removed) → "reappeared" event
```

- **active** — the listing appears in the search results (or has been absent for too short a time to decide).
- **delisted** — the listing is absent from the search results (in complete collections) while its detail page still returns 200 on **2 checks**, and it has not reappeared in the meantime. **It counts as gone** for time-to-sell purposes.
- **removed** — the detail page returns 404 (or 410).

## The three dates

| Field | Meaning |
|---|---|
| `list_last_seen` | last day the listing appeared in the search results. **This is the end date used for time to sell.** |
| `delisted_date` | first day of the absence **confirmed by a conclusive check result** (the start of the absence that was later confirmed) |
| `detail_gone_date` | first day the detail page returned 404/410 |

There can be more than one day between `list_last_seen` and `delisted_date` (a skipped run, an incomplete segment, a check that failed): the disappearance happened somewhere in that interval.

## Spells (continuous periods online)

A listing can disappear and reappear with the **same ID**. Each continuous period online is a *spell*, which starts on `spell_start` and ends on `list_last_seen`:

- for a new listing, `spell_start = first_seen`;
- when the listing reappears, the previous spell is closed (its dates are kept in the `reappeared` event: `spell_start`, `list_last_seen`, `delisted_date`) and a new one opens with `spell_start` = the day of the reappearance;
- the `removed` and `delisted` events carry the dates of the spell being closed.

**So the `events` table filtered on `removed`/`delisted` is directly the list of "sales"**, each with its start and end.

**Time to sell** = `list_last_seen − spell_start` of the closed spell. Listings with `first_seen_censored = true` were already online on the first collection day of their segment: their real start is earlier (the data is left-censored). Listings that are still `active` are right-censored. Survival analysis is the right tool for this.

## Rules applied in a run

For every listing **present** in today's search results:
- if it is new → `active`, `first_seen = today`, `new` event;
- if it was `delisted` or `removed` → back to `active`, `reappeared` event carrying the dates of the previous spell, and a new spell starts;
- if the price differs from the last one → `price_change` event (including changes from or to "no price");
- in every case `list_last_seen = today`, and the absence counter is reset.

For every **absent** listing:
1. If its segment (source, city, contract) **was not collected** today, or was collected **incompletely** → no change.
2. Otherwise, the result of the detail-page check decides:
   - **404/410** → `removed` (`removed` event; if the listing was `delisted` → `detail_gone` event);
   - **200** → absence count +1; on the second check returning 200 with no reappearance in between → `delisted` (`delisted` event). Days with an inconclusive result in between do not reset the count;
   - **error, timeout or check not performed** → no change.

The cards' `data-eliminato` flag is only stored: its meaning still has to be verified by comparing it with real 404s.

## Complete segment (safety lock)

Code: `quality.py`. A segment (source, city, contract) is **complete** only if:

1. page 1 shows the total declared by the site (otherwise reason `no_declared_total`);
2. no result page failed after all retries (`failed_pages`);
3. the unique listings collected are at least **97%** of the declared total; for segments with fewer than **50** declared listings, at most **2** missing listings are allowed (`incomplete`);
4. the listings collected have not dropped suspiciously compared with the segment's active listings before the run: the allowed drop is 5% (minimum 2 listings) (`suspicious_drop`). This guards against the site mistakenly declaring a wrong total (e.g. "0 case", "0 homes"): the total and the listings come from the same page, so on their own they are not enough. **If the drop repeats for 3 consecutive runs** (`drop_confirm_runs`), it is treated as real (`drop_confirmed`, with a warning) and the disappearances are recorded. Without this, a genuine drop (common in small segments, e.g. 4 rentals in Marnate) would lock the segment forever. Reruns on the same day count as a single run;
5. the run is not limited with `--max-pages` (`max_pages`).

An incomplete segment **generates no disappearances** that day and makes the run end with an error (GitHub sends an email). This is why a test run with `--max-pages` can never record disappearances.

**Drop alert:** if the number of active listings has dropped by more than **5%** compared with the previous run, the run ends with an error even if all segments are complete (a sign that the site has changed).

## To verify in the first few days

- How the site presents a listing that has **actually** been removed (404? redirect? a page with a notice?). The 404 has only been verified on made-up IDs. The HTML of the first 50 checks returning 404 in each run is saved (`raw/`).
- The meaning of `data-eliminato`.
- Listings that change segment (e.g. the same listing in the search results of two neighboring municipalities): the state remembers the last segment in which the listing was seen; if the listing then appears only in the other segment and that segment is not collected, it could end up `delisted`. Since every municipality is collected every day this case does not arise, but it should be monitored.
