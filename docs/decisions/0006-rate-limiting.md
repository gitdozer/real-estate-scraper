# 0006 — Limited request rate towards the site (~3 requests per second)

Date: 2026-10-29 · Status: accepted, revised on 2026-10-31 (scraper 0.1.4: separate paces for search results and detail pages, no page past the last one). The sections below keep the history of the diagnosis, including the hypotheses that turned out wrong.

## Context
The first launch on GitHub Actions (27 October) and the runs on the following days were all cancelled by the job time limit (350 minutes, then 120) without writing anything. The progress logs showed that the run was stuck in the **search-results phase**:

- in the first minute, ~750 successful requests (≈12 per second, 6 in parallel);
- then, for the rest of the run, **12 timeouts per minute** (all 6 connections hanging for 30 s each) and only 8–20 responses per minute.

The site does not answer with 403 or 429. Towards datacenter IPs, when the request rate is too high, it **leaves requests hanging**. From the user's home IP the same rate works fine (1,528 pages in 1.1 minutes). The old scraper, which was slower (result pages one at a time with a 2.5 s pause), never ran into the problem.

Diagnosis from GitHub using the `probe` command (workflow "Diagnosi ritmo", i.e. "request-rate diagnosis"), sending requests one at a time:

| Rate | Requests | Succeeded | Timeouts | Mean latency |
|---|---|---|---|---|
| 1/s for 10 min | 592 | 592 | 0 | 0.50 s |
| 2/s for 5 min | 577 | 577 | 0 | 0.41 s |
| ~3/s for 5 min | 924 | 924 | 0 | 0.31 s |

This is a **rate limit**, not a cap on the total number of requests.

## Update 2026-10-30: the number of parallel connections matters

The first launch at 3 requests/s **but with 6 parallel connections** stalled again after ~710 requests (minute 4). From then on the site answered 3–4 requests per minute for more than 2 hours, **even after the backoff had dropped to a single connection**: the IP stays "penalized". The `probe` diagnosis, using **a single connection**, had made 2,093 requests at up to ~3/s without a single timeout. Conclusion: the site tolerates ~3 requests/s **sent sequentially**; several simultaneous connections from the same IP trigger an IP penalty that lasts for hours. Hence `site_concurrency = 1` (and, to be safe, `image_concurrency = 1`).

## Second update 2026-10-30: it looks like a volume limit, not a rate limit

The first full run with a single connection at ~3 requests/s (run 41024689477, 320-minute budget) stalled again: 760 requests in 6 minutes without errors (all of Milano sale, 729 pages), then 1–4 responses per minute until the circuit breaker opened at minute 187. All the protections worked: every segment was marked incomplete, no disappearances were recorded, and the run wrote what it had collected.

The three stalled runs have one thing in common, the number of requests, not the rate:

| Run | Connections | Rate | Requests before stalling | Minutes |
|---|---|---|---|---|
| 27 Oct | 6 | ~12/s | ~750 | 1 |
| 29 Oct | 6 | 3/s | ~710 | 4 |
| 30 Oct | 1 | ~2.4/s | ~760 | 6 |

The `probe` diagnosis that suggested "~3/s is fine" was flawed: it cycled over **798 URLs** (pages 1–399 of sale and rent) and then requested them again. In its first 13.5 minutes it made only ~800 requests to distinct pages, at 1–2/s; after that it was re-reading pages the site's CDN probably had in cache, which do not weigh on the limit.

**Working hypothesis:** the site tolerates ~700–800 requests to distinct pages from one datacenter IP within a short window, and then penalises the IP for hours. It is not yet known whether a slow enough sustained rate (e.g. 0.5/s) stays under the limit. The `probe` command now never repeats a URL and logs cumulative counts every minute; the next diagnosis runs at 0.5 requests/s for 45 minutes (~1,350 distinct pages, well beyond the ~760 threshold).

### Result of the corrected diagnosis (run 41058341202)

At **0.5 requests/s, one connection, never repeating a URL**: 1,303 distinct pages in 45 minutes, 1,297 answered, 3 isolated timeouts, 3 404s past the end of the list. The rate stayed at 30 requests per minute throughout, well beyond the ~750 pages where the faster runs stalled. So the limit does depend on the rate, but it is far lower than we thought: the site seems to allow a burst of ~700–750 requests and then a sustained rate somewhere between 0.5/s (holds) and ~2.4/s (stalls).

**Revised decision:** `site_rate_per_s = 0.5`; `max_runtime_minutes = 330` and a 350-minute job limit for the nightly run too (the repository is public: Actions minutes are free). A faster rate (e.g. 1/s) can be measured later with the same probe; the rate goes up only after a probe holds for at least 45 minutes.

### Old-scraper log: detail pages tolerate a much higher rate (2026-10-30)

A log of the old scraper (GitHub Actions, Azure westus, 2026-10-06) shows: 714 search-result pages one at a time with a 2.5 s pause (**0.30 req/s**, 39.5 minutes, 0 errors), then **17,132 detail pages with 4 connections at ~2.9 req/s for 99 minutes**, with 2 "Server disconnected" errors and 3 listings missing. All our stalls happened on search-result pages, and so did the probes. Working hypothesis: the site limits mainly **search-result pages** (~0.5 req/s sustainable), much less detail pages; the "parallel connections" conclusion of the first update came from search-result pages too. Alternatively the site may have tightened its limits after 2026-10-06 (possibly after our first launch at ~12 req/s on 2026-10-27). The `probe` command can now probe detail pages (`--kind detail`, `--concurrency`); next measurement: detail pages at 2.5 req/s with 2 connections for 45 minutes.

### Detail pages hold; every stall follows a 404 (2026-10-31)

- **Detail-page probe** (run 41094245148): after 300 search-result pages at 0.5 req/s, **3,985 detail pages in 45 minutes with 2 connections** (rate cap 2.5/s, ~1.5/s reached because of the 1.34 s latency): **0 timeouts, 0 errors**.
- **The collection at 0.5 req/s stalled too** (run 41076923737): ~750 requests in 25 minutes, then timeouts, exactly as at 12, 3 and 2.4 req/s. So the rate was not the cause.
- In **all four** runs with heartbeats, the first timeouts come **right after the only 404**: the extra page requested after the last page of Milano sale (`n_pages + 1`, to catch listings shifted during the collection). The search-results probe at 0.5 req/s met its first 404s at minute 44 of 45 and saw nothing after them. The old scraper followed the pager's "next" link and never requested a page past the end.

**New hypothesis:** requesting a search-result page that does not exist (404) makes the site penalise the IP (about half of the following requests hang for hours). Test: `probe --kind list --first-page 600`, which reaches the 404 pages of Milano rent (past page ~646) while the Milano sale pages are still valid (up to ~728); if those valid pages start timing out right after the first 404s, the hypothesis is confirmed.

### Result of the 404 test (run 41191253281, 2026-10-31)

At 0.5 req/s from search-result page 600: from minute 3 to 9 the valid Milano sale pages kept answering **while** 404s on Milano rent were interleaved; from minute 9 to 15, 285 pages past the end answered 404 promptly; the stall came only at minute ~15, after ~450 requests, almost all on deep or non-existent pages. So a single 404 does not trigger the penalty. The picture that fits **all** the data: the site weighs search-result pages by their cost for the server (deep pages and pages past the end are expensive, detail pages cheap) and penalises the IP when the cost accumulated over time crosses a threshold. The old scraper stayed below it by reading search results at 0.30 req/s and never requesting a page past the end. After four hypotheses (rate, parallel connections, 404, cost), we stop guessing and copy the behaviour that has been **shown to work**.

## Decision (scraper 0.1.4, 2026-10-31)
- **Search-result pages** like the old scraper: **one connection at 0.3 requests/s** (`list_concurrency = 1`, `list_rate_per_s = 0.3`), and **never a page past the last one**: pages 2…`ceil(declared/24)`, then the pager's "next" link is followed (at most 5 extra pages) to reach listings shifted during the collection. A page that was not read never leads further.
- **Detail pages** with their own client: **2 connections at 1.5 requests/s** (`detail_concurrency = 2`, `detail_rate_per_s = 1.5`), the pace measured on 2026-10-30 (3,985 pages, 0 errors); the old scraper went faster (~2.9/s with 4 connections).
- Photos: one connection at 4 requests/s (separate host, limit not measured yet).
- **Every failed attempt** (timeout, 5xx, 429) counts towards the error rate: above 20%, concurrency and rate are halved (down to 0.25 requests/s), then the circuit breaker opens; pages already read are kept, and an interrupted segment never records disappearances.
- The **search-results phase has a deadline** (40% of the maximum run time), which also stops retries.
- Progress logs per phase, a heartbeat every minute during the search-results phase, and separate request statistics for search results and detail pages in the summary.

*Earlier decisions, superseded:* 3 req/s with 6 connections (2026-10-29); one connection at 3 req/s (2026-10-30, "parallel connections" hypothesis); 0.5 req/s for every page (2026-10-30, "volume per IP" hypothesis).

## Alternatives considered
- **IP rotation or proxies** to get around the limit: that would be circumventing a protection put in place by the site (rule 5 in CLAUDE.md).
- **Running from the user's PC**: ruled out by the project constraints.

## Consequences
- Daily run (estimate): ~1,700 search-result pages at 0.3/s ≈ 95 minutes, then ~5,400 detail pages at 1.5/s ≈ 60 minutes, then photos: **~2.5–3 hours**, within the 330-minute budget.
- Bootstrap: ~35,000 detail pages ≈ 6.5 hours, i.e. **~2 nights** (the queue carries over).
- Not yet proven: ~1,700 search-result pages at 0.3/s in one run (the old scraper read 714). The other municipalities have few, shallow pages. The nightly run is the test; the heartbeat shows it if the site starts hanging.
- Raising the paces later: only one at a time, after a 45-minute probe that holds.
