# Changelog

Changes per component. Versions follow [SemVer](https://semver.org/), with tags `<component>-vX.Y.Z`.

## scraper

### 0.2.5 — 2026-11-14
- **Map probe, second design.** The first run (43621007332, 17:25 UTC) asked the map first, without a session: one 503, then 401 with a 13 KB HTML page on the other 15 segments, while page 1 of every segment answered 200. The site's own page asks the map with jQuery after the page is loaded, so the probe now visits page 1 first (declared total, cookies) and asks the map with the same client, with the key encoded as jQuery sends it. The summary gains the number of cookies set by the site and the title of a non-JSON answer.

### 0.2.4 — 2026-11-14
- **Map (GeoJSON) probe**: `probe --kind geojson` asks the map endpoint of the search results (`/ricerca/geojson?cacheKey=/case-in-<contract>/<city>`, the whole search in one request) for every configured segment, then page 1 of each segment for the declared total, and reports counts only: outcome, size, features, features with an id and with coordinates, property keys, coverage. First test from GitHub's IPs on the night of 2026-11-14 (temporary schedule of the `Rate probe` workflow at 23:30 UTC); if the map answers where the search-result pages are blocked, it is the candidate source of the daily lists (decision to follow).

### Schedule suspended — 2026-11-14
- The nightly `Daily collection` is suspended (the `schedule` trigger of `scrape.yml` is commented out; manual runs stay possible): since 2026-11-12 the site blocks the search results from GitHub's IPs after ~100–200 pages, or with a 403 from the first request (`docs/sources/trovacasa.md`). No code change.

### 0.2.3 — 2026-11-11
- **Requests past a phase deadline are skipped at once.** They used to wait for a connection slot and for their turn in the pace before noticing the deadline: on 2026-11-11 the 16,000 photo requests left at the photo deadline were skipped at 4 per second (over an hour), GitHub cancelled the job at 350 minutes and nothing was written — after 1,731 search-result pages, ~9,930 detail pages (the most in one run so far) and 13,635 photos. The deadline is now checked before waiting as well.

### 0.2.2 — 2026-11-10
- **No detail page on the day a listing first appears in the search results** (decision 0009). The three 404s that stopped the detail phase on 2026-11-10 were private listings inserted a few hours earlier: already listed (at the end of the results), their page not published yet (online by the evening). The page is requested from the next day, if the listing is still listed; photos are still taken on the first day. At bootstrap (a segment with no listing in the state yet) every listing is new and its page is requested the same day, as before.
- Detail priorities: `new` is now the first detail page of a listing that appeared after its segment's censor window (even if its card changed in the meantime); `never_detailed` stays for the listings marked `first_seen_censored`.

### 0.2.1 — 2026-11-10
- **The stop at the first 404 now stops the requests already waiting their turn.** Every request of a 500-page chunk passed the "stopped?" check at once, before waiting for a connection and for the pace, so after the first 404 the following requests still went out; the phase of 2026-11-10 ended only because a timed-out request re-entered the loop. The check is repeated right before the request is sent.
- The report on R2 lists the listings seen in today's search results whose detail page answered 404 (`gone_samples`: URL, reason, status, up to 20) and their 404 pages are kept with the raw pages: that 404 is what stops the detail phase, and nothing else said which listings cause it.
- First two runs with the 0.1.8/0.1.9 rules (11-09, 11-10): search results complete on both days and written; details 4,602 then a burst of 503s opened the circuit (11-09); details stopped at a 404 after 44 pages, photos all done, 3,566 `delisted` recorded (11-10). Notes in `docs/sources/trovacasa.md` and `docs/runbook.md`.

### 0.2.0 — 2026-11-08
- **The project is now entirely in English**: code comments, docstrings, log messages, CLI help, the GitHub job summary, workflow names, configuration comments and documentation (the docs were translated earlier, in commit 895035a). Italian remains only where it is data or text read from the site (`vendita`, `affitto`, detail-page labels, quoted page text).
- Log phase tags are now `[start]`, `[lists]`, `[details]`, `[photos]`, `[checks]`, `[write]`; the heartbeat reads "in progress".
- Workflows renamed: "Raccolta giornaliera" → **Daily collection**; "Diagnosi ritmo" → **Rate probe**, with its file renamed from `diagnostica.yml` to `probe.yml` (past runs stay listed under the old name in the Actions tab).
- Rebased on 0.1.9 (same day): includes decisions 0007 and 0008.
- No change in behavior, data or schema: same columns, same values, same `SCHEMA_VERSION`; data from 0.1.x and 0.2.0 can be used together.

### 0.1.9 — 2026-11-08
- **Disappearances from the list evidence** (decision 0008, issue #2): an active listing absent from a segment collected completely has its absence counted even without a detail-page check; on the second consecutive counted absence it becomes `delisted` (`delisted_date` = first day of absence). A sampled check answering 404 still makes it `removed` at once; an error or no check leaves the count to the list. Incomplete or missing collections change nothing, as before.
- Revises decision 0005, which required a conclusive detail-page check: since decision 0007 that check can be made for one listing per run only.

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
