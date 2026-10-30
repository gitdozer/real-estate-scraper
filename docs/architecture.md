# Architecture

## The big picture

```
GitHub Actions (daily cron + manual trigger)
  └─ python -m scraper run --storage r2
       1. read the current state from R2 (state/listings.parquet)
       2. for each (source, city, contract): read ALL the result pages
       3. decide which detail pages to download (new / changed / rotation / disappearance check)
       4. download the detail pages, then the photo fingerprints
       5. compute the events (new, price change, gone, reappeared)
       6. quality checks: if a segment is incomplete, record NO disappearances
       7. write the day's Parquet partitions, then the state, then the report
Cloudflare R2 (private bucket)
  └─ Parquet partitioned by date + state + report  (see data-dictionary.md)
Local machine
  └─ DuckDB reads the Parquet files from R2 → Streamlit dashboard in Phase 3
```

The code does not depend on GitHub Actions: the same command runs on any machine that has the R2 environment variables set (plan B: a Google Cloud VM, see [decisions/0003](decisions/0003-github-actions-r2.md)).

## Modules (`packages/scraper/src/scraper/`)

| Module | Responsibility |
|---|---|
| `config.py` | loads `config/cities.yaml` and `config/settings.yaml` |
| `models.py` | data records (`Card`, `Detail`, …) and `SCHEMA_VERSION` |
| `sources/trovacasa.py` | URLs and page parsing for trovacasa.it |
| `sources/base.py` | common interface shared by all sources |
| `scope.py` | scope: what counts as "real" residential property |
| `fingerprint.py` | fingerprints used to tell whether a listing card or a detail page has changed |
| `http.py` | HTTP client with retries and adaptive backoff |
| `state.py` | state reconciliation and events (see `disappearance-logic.md`) |
| `planner.py` | which detail pages and which photos to download today |
| `quality.py` | segment completeness and the drop alert |
| `photos.py` | perceptual fingerprints of the photos |
| `frames.py` | explicit schemas of the Parquet tables |
| `pipeline.py` | the daily run (`run_daily`) |
| `report.py` | aggregated summary for GitHub |
| `cli.py` | command line (see `runbook.md`) |

## Networking

Client: `http.Fetcher` (async httpx), with real-browser headers and compression enabled.

| Parameter (`config/settings.yaml`) | Default | Effect |
|---|---|---|
| `site_concurrency` | 1 | concurrent connections to trovacasa.it. **Just one**: from GitHub, with several parallel connections the site puts our IP under a penalty (it throttles or stalls it) for hours |
| `image_concurrency` | 1 | concurrent connections to the photo server (a different host) |
| `site_rate_per_s` | 0.5 | **maximum request rate** to the site (requests/s): at least 2 s must pass between the start of two requests. From GitHub 0.5/s held for 1,303 distinct pages, while at ~2.4/s the site stalls after ~750 pages; at ~12/s it leaves requests hanging — see [decisions/0006](decisions/0006-rate-limiting.md) |
| `image_rate_per_s` | 4 | maximum request rate to the photo server |
| `max_retries` | 4 | maximum attempts per request |
| `timeout_s` | 30 | timeout for a single request |
| `error_window` | 200 | number of requests over which the error rate is measured |
| `error_threshold` | 0.2 | error rate above which concurrency is halved |

**What gets retried:** network errors and timeouts, 5xx and 429 responses, and the site's redirect to `/Error/InternalServerError` (intermittent 500 errors). The wait between attempts is whatever `Retry-After` says; otherwise 2, 4, 8… seconds (at most 30) plus a little random jitter.

**What does not get retried:** 404 and the other 4xx codes. A 404 is not an error: it carries the information "listing removed", and it does not count towards the error rate. The exceptions are **401, 403 and 451** (access denied): they are not retried, but they do count as failures, so they trigger the backoff and the circuit breaker — if the source blocks us, the run stops. `Retry-After` is honoured up to a maximum of 30 seconds.

**Adaptive backoff:** every failed **attempt** (timeout, 5xx, 429, error redirect) counts towards the error rate, even when the next attempt succeeds: when a site slows down, we should ease off straight away. Once the window of the last `error_window` requests is full and failures exceed `error_threshold`, both concurrency and request rate are halved (minimum rate 0.25 requests/s). If they are already at the minimum, the client raises `CircuitOpen`: the run stops cleanly, writes whatever it has collected, and **records no disappearances**. The results obtained before the circuit opened travel with the exception (`CircuitOpen.partial`): the search-result pages and detail pages already downloaded are kept, and a segment interrupted by the circuit always counts as incomplete.

**Deadline:** `get_many(..., deadline=…)` starts no new requests after the deadline, and **does not retry** a request whose attempt failed after it (that request counts as failed, not as skipped); the ones not executed stay queued for the next day. Before 2026-10-30 retries went on past the deadline, and the search-results phase lasted up to 188 minutes instead of 128.

## Which detail pages are downloaded each day

Code: `planner.py`. Each listing gets at most one detail download, tagged with its highest-priority reason. If the run has to stop because it is running out of time, the ones at the bottom of the list are dropped first and carried over to the next day.

| Priority | Reason | When |
|---|---|---|
| 1 | `absence_check` | an active listing missing from today's search results, **only in segments that were collected and are complete** (in any other segment the result would be thrown away) |
| 2 | `new` | a listing never seen before, or one that has reappeared |
| 3 | `changed` | the listing card's fingerprint has changed (price, floor area, photos, …) |
| 4 | `never_detailed` | the detail page has never been downloaded (e.g. a previous run was interrupted) |
| 5 | `delisted_recheck` | a `delisted` listing, re-checked every 7 days until it returns 404 |
| 6 | `rotation` | periodic refresh: each listing has its own **fixed day** in the 7-day cycle (ID modulo 7), or its detail is at least 14 days old |
| 7 | `full` | only with `full_details: true` (all listings, every day) |

Out-of-scope listings (auctions, etc.) do not get a detail download, except for the absence check. Within the same reason, the oldest detail pages are downloaded first.

**Why a fixed day:** at bootstrap every detail page is downloaded on the same day. With a rule like "older than 7 days" they would all expire together on day eight. With a fixed day, roughly one seventh of them is refreshed each day.

## Which photos are downloaded

For photos we only compute the perceptual fingerprint; the images themselves are not saved. Order of work, within the `max_photos_per_run` cap (only whole listings are added, never part of one):

1. **new** listings (not censored): the first `photos_new` = 6 photos;
2. listings whose **photo list has changed**: the first 6 photos;
3. **backlog** (active listings with fewer fingerprints than they should have: never computed, or interrupted halfway), oldest first: the first `photos_backlog` = 3 photos for censored listings (already online when collection started), the first 6 for the others.

## The daily run (`pipeline.run_daily`)

1. **Starting state.** A date earlier than the last run is rejected. `state/listings.parquet` is read. If the copy `state/history/dt=<today>/` already exists (a rerun, including after an interrupted run), then for every listing that belongs to a segment collected today we restart from its version *before* today's first run.
2. **Search results.** Up to 40% of the maximum runtime (`LIST_SHARE`); pages not read by the deadline count as failed. Every minute a **heartbeat** in the log reports requests, requests in flight, latencies and HTTP status codes. All segments run in parallel: page 1 (which gives the declared total), then pages up to `ceil(total/24) + 1`. A 404 past the first page marks the end of the results; other errors after all retries, or a page the parser cannot read, count as failed pages. If the circuit breaker opens, the listing cards already read are kept. Listing cards are de-duplicated by key.
3. **Completeness** of each segment (`quality.segment_ok`, see `disappearance-logic.md`).
4. **Censoring.** Segments whose first complete collection is less than 7 days old (or that have never had one) flag their new listings as `first_seen_censored`.
5. **Detail pages** in priority order, in batches of 500, up to 85% of the maximum runtime. Each batch is processed **before** the next one is downloaded, so only one batch of pages sits in memory at any time (at bootstrap there are ~35,000 detail pages: we measured a ~145 MB peak with 6,000 simulated 170 KB pages). The HTML kept in `raw/` is compressed immediately and capped at `raw_max_per_run` pages. A detail page that does not contain the listing's `TC<id>` code (an error page, an anti-bot check, a redesigned site) counts as an error; if errors exceed 20 and 10% of the attempted detail pages, the `details_errors` warning fires. Results of the absence checks: 200 → `alive` (if the page redirects elsewhere: `alive` with no detail), 404/410 → `gone`, anything else or an unreadable page → `error`. A `changed` listing whose detail page does not arrive keeps its old fingerprint, so its detail page is requested again the next day.
6. **State and events** (`state.reconcile`).
7. **Photos** up to 90% of the maximum runtime, on a separate client (the image server is a different host), in batches: the fingerprint is computed immediately and the image is discarded.
8. **Writing** (unless `--dry-run`): copy of the starting state (this marks that a run happened today) → the day's partitions → new state → segment registry → report; then cleanup of `raw/` (90 days) and `state/history/` (30 days).
9. **Exit status:** code 1 if any segment is incomplete, active listings dropped by more than 5%, there were too many detail-page errors, or the circuit breaker opened on the site.

The GitHub summary also reports the **HTTP status codes** received from the site (counts only): this is how we notice that we are being blocked (403).

The logs contain only counts: the logs of the HTTP libraries (which would print URLs) are silenced, and an unexpected error prints only its type (the details go to `runs/crash/` in storage).
