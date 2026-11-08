# 0007 — One request for a missing listing (404) puts the runner IP in penalty: checks of absent listings leave the detail queue

Date: 2026-11-08 · Status: accepted (scraper 0.1.8). Follow-up pending: disappearances from list evidence (two consecutive complete collections) instead of the detail page's 404. Tracked in GitHub issue #1.

## Context

From 2026-11-02 every nightly run was cancelled by GitHub at 350 minutes without writing anything (six days of data lost). The heartbeat added in 0.1.6 showed the same sequence every time: the search-result phase ended healthy (1,565–1,588 requests, all 200, 0.6 s average), then **in the first minute of the detail phase the site answered 5–13 fast 404s and left every following request hanging** (`ReadTimeout` after 30 s, about 2 responses per minute, for the rest of the run). The site never answers 403 or 429.

Four hypotheses had already turned out wrong (request rate, parallel connections, a page past the last one, a never-ending response — decision 0006). A systematic comparison with the user's old scraper, which kept working at night from GitHub with unchanged code (736 search-result pages + 17,639 detail pages on 2026-11-07), left one difference in the detail phase: the old scraper only requests links found in the day's search results and **never gets a 404**; ours starts the detail queue with the `absence_check` tasks (listings gone from the search results), whose pages answer 404 by construction.

## Evidence (probes from a fresh GitHub runner, `probe --kind detail`, 300 search-result pages at 0.5 req/s, then detail pages at 1.5 req/s with 2 connections)

| Run | Variable | Result |
|---|---|---|
| 42399690479 (11-07) | none | **2,017 / 2,017 OK**, 0 timeouts |
| 42473045029 (11-08) | 15 requests for non-existent listing ids first (`--dead-first 15`) | 10 × 404 answered, then **80 timeouts, 0 OK** in 20 minutes |
| 42475525510 (11-08) | one non-existent id after every 20 valid pages (`--dead-every 20`) | 20 OK, the first 404, ~16 more OK (≈ 11 s), then **78 timeouts, 0 OK** |

Reading: **a single request for a missing listing puts the IP in penalty about 7–11 seconds later, for hours**. In penalty the site keeps answering 404s instantly and hangs only the valid pages — exactly the pattern of the failed runs (11-07: 5 × 404, 0 × 200). The rule is new: on 2026-10-31 and 11-01 the runs got 105 and 3,451 × 404 through at 1.5 req/s. Time of day, header set, HTTP library, search-result volume and detail pace were all ruled out (same runner, same pace, same 300-page history in the three probes).

Our own data also says that the list evidence is reliable on its own: in those two runs **3,469 of 3,469** absence checks (active listing missing from a complete segment) answered 404; none was alive.

## Decision

1. **The checks of absent listings (`absence_check`, `delisted_recheck`) leave the detail queue.** Only a sample of `absence_checks_per_run` (default **1**) is requested, **after the photos**, on a client of its own, so that the penalty it triggers cannot hurt the day's work. The sample tells us when the site relaxes the rule.
2. **The detail phase stops at the first 404** (`Fetcher(stop_on_status=(404, 410))`): a listing removed between the search results and its detail page is rare (0 in 9,734 detail pages on 11-01, 0 in 4,034 in the probes), but one is enough to leave every following request hanging until the phase deadline. The remaining tasks are not attempted and carry over to the next day (`skipped_deadline` in the report, alert `details_stopped_404`); photos and the write happen normally; the exit status is unaffected.
3. **Disappearances are paused until the follow-up**: an absent listing whose check was not made stays `active` with its counters untouched (rule 6: no network error, missing page or partial run produces `removed`/`delisted`). The follow-up records a disappearance from the list evidence (absent from a complete segment on two consecutive complete collections → `delisted`, `delisted_date` = first day of absence), with its own tests and decision record.

## Alternatives considered

- *Spreading the 404s among valid pages*: measured, does not help (one 404 is enough).
- *Running the checks first, at a very low rate*: the first 404 kills the rest of the run.
- *Making the checks from another IP class* (home device, cloud VM): a home device is excluded by the owner; a VM with one stable IP remains an option under rule 5 (one identifiable client, no rotation) if the list-evidence rule proves insufficient.
- *Imitating a browser more closely* (full Chrome header set, TLS fingerprint): not the trigger here, and a spoofed identity is out of scope under rule 5.

## Consequences

- The daily run writes search results **and** detail pages again from the first 0.1.8 run (to be verified on 2026-11-09).
- `removed` events are limited to one per run until the follow-up lands; the backlog of absent listings is not lost (they stay `active` and are re-planned every day).
- The probe gained `--dead-first` and `--dead-every` to reproduce the trigger; never run them against the production runner's day (a penalised IP stays penalised for hours).
