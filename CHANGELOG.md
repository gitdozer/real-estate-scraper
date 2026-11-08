# Changelog

Changes per component. Versions follow [SemVer](https://semver.org/), with tags `<component>-vX.Y.Z`.

## scraper

### 0.1.8 — 2026-11-08
- **Root cause of the stalled runs since 2026-11-02 found and removed** (decision 0007, issue #1): one request for a missing listing (404) from a GitHub runner puts the IP in penalty about 10 s later, for hours. The detail queue started with the absence checks, i.e. with 404s by construction.
- The checks of absent listings (`absence_check`, `delisted_recheck`) leave the detail queue: only `absence_checks_per_run` of them (new setting, default 1) are requested, after the photos, on their own client. Disappearances are limited to that sample until the list-evidence rule lands (follow-up).
- The detail phase stops at the first 404 or 410 (alert `details_stopped_404`); the rest of the queue carries over to the next day, photos and write happen normally.
- `probe --kind detail --dead-first N` and `--dead-every N` (workflow inputs `dead_first`, `dead_every`) reproduce the trigger with non-existent listing ids.

### 0.1.7 — 2026-11-07
- The phase deadline is checked right before every attempt, not only before the first one: when every detail page timed out, retries queued behind other requests kept starting after the deadline (one 30 s timeout each), the phase never ended and GitHub cancelled the job before anything was written (2026-11-04 → 11-07).

### 0.1.6 — 2026-11-04
- Every request has a total limit of 2 × `timeout_s`: a response that never completes becomes a failed attempt (`total_timeout`) instead of blocking its batch. On 2026-11-02 and 11-03 such a request kept the details phase stuck until GitHub cancelled the job, and nothing was written for those days.
- Heartbeat in the detail and photo phases too; Python stacks printed to the log if a run is still alive 10 minutes after the photo deadline.

### 0.1.5 — 2026-11-02
- Brake release: after a window of requests with at most 5% failures, concurrency and pace go back up one step, never beyond the configured values (a short burst of 503s used to halve the detail pace for the rest of the run).
- Detail pages stop at 75% of the maximum runtime instead of 85%, so photos get ~50 minutes per run instead of ~17 while there is a backlog. Search-result pages are unchanged.

### 0.1.4 — 2026-10-31
- Search-result pages at **0.3 requests/s** with one connection, like the old scraper, and **never a page past the last one**: the pager's "next" link is followed (at most 5 extra pages) for listings shifted during the collection.
- Detail pages on their own client: **2 connections at 1.5 requests/s** (measured: 3,985 pages in 45 minutes without errors).
- New settings `list_concurrency`, `list_rate_per_s`, `detail_concurrency`, `detail_rate_per_s` replace `site_concurrency` and `site_rate_per_s`; the summary shows search-result and detail requests separately.
- `probe --first-page N` (list kind) and the matching workflow input.
- `probe --kind detail`: collects distinct detail-page URLs from search-result pages read at 0.5 req/s, then probes them; `--concurrency` connections share one rate. The "Diagnosi ritmo" workflow has the matching inputs and a 75-minute limit.

### 0.1.3 — 2026-10-30
- Request rate to the site lowered to **0.5 requests/s** (measured: 1,303 distinct pages without stalling from GitHub; ~2.4/s stalls after ~750 pages). Maximum run duration 330 minutes and job limit 350 also for the nightly run.
- The deadline also stops retries: after it a failed attempt is not retried (on 2026-10-30 the search-results phase overran its deadline by an hour because of retries).
- When the circuit breaker opens, the search-result and detail pages already downloaded are kept instead of being discarded; an interrupted segment still never counts as complete.
- `probe` never repeats a URL (a repeated page may be served from the site's cache and hides the limit), stops when the URLs run out, and logs cumulative counts every minute; "Diagnosi ritmo" now defaults to 0.5 requests/s for 45 minutes. Analysis of run 41024689477 in decision 0006.

### 0.1.2 — 2026-10-30
- A single connection to the site and to the photo server: from GitHub, with several parallel connections the site puts our IP under a penalty for hours (update to decision 0006).

### 0.1.1 — 2026-10-29
- Rate-limited requests to the site (3 requests/s) and to the photo server (4/s): from GitHub the site leaves requests hanging above ~3/s (diagnosis in `docs/decisions/0006`).
- The backoff counts every failed attempt and halves the request rate too; the search-results phase now has a deadline as well.
- Per-phase progress logs, a heartbeat every minute, latencies in the statistics; configurable job time limit (default 120).
- `probe` command and the "Diagnosi ritmo" (request-rate diagnosis) workflow.

### 0.1.0 — 2026-10-25
- Daily collection from trovacasa.it: search results, detail pages, photo fingerprints, state and events, quality checks, `run`/`status`/`import-legacy` CLI; import of the Milano historical data from 2026-10-17.
- Robustness (independent review): correct reruns even after an interrupted run, past dates rejected, read errors handled page by page, a segment's drop accepted after 3 runs, unexpected errors without listing data in public logs.
- Final review: batch processing (bounded memory at bootstrap), raw HTML compressed and capped, 401/403/451 treated as a block, HTTP status codes in the summary, unrecognized detail pages counted as errors, municipalities with 0/1 listings, GitHub actions pinned to a commit and dependencies installed with `--locked`.
- GitHub Actions workflows: tests on every push, daily collection (02:17 UTC) and manual trigger.
- Monorepo structure, configuration of the municipalities (`config/cities.yaml`) and of the parameters (`config/settings.yaml`).
