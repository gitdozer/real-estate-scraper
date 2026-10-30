# Changelog

Changes per component. Versions follow [SemVer](https://semver.org/), with tags `<component>-vX.Y.Z`.

## scraper

### Unreleased
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
