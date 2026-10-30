# 0006 — Limited request rate towards the site (~3 requests per second)

Date: 2026-10-29 · Status: accepted, under review (see the second update of 2026-10-30)

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

## Decision
- The HTTP client uses **a single connection** to the site and to the photo host (`site_concurrency = image_concurrency = 1`) and respects a **maximum request rate**: `site_rate_per_s = 3`, `image_rate_per_s = 4` (the photo limit has not been measured yet). With real latencies (0.3–0.6 s) the effective rate is ~2–3 requests/s.
- **Every failed attempt** (timeout, 5xx, 429) counts immediately towards the error rate: if it exceeds 20%, concurrency and rate are halved (down to 0.25 requests/s), and then the circuit breaker opens.
- The **search-results phase also has a deadline** (40% of the maximum run time): pages not yet read count as failed and the segment is marked incomplete (so no disappearances are recorded), but the run finishes and writes whatever it collected.
- Progress logs per phase, plus a heartbeat every minute during the search-results phase (requests, in flight, latencies, HTTP status codes).

## Alternatives considered
- **IP rotation or proxies** to get around the limit: that would be circumventing a protection put in place by the site (rule 5 in CLAUDE.md).
- **Running from the user's PC**: ruled out by the project constraints.

## Consequences
- Estimated daily run: ~1,700 result pages + ~7,000 detail pages ≈ 60 minutes, within the 100-minute budget.
- First launch: ~35,000 detail pages ≈ 4 hours. Thanks to the deadlines it completes over 1–2 runs (detail pages not yet downloaded stay in the queue); the missing photos follow on the next days.
- The rate can be raised cautiously by watching the heartbeat in the logs (timeouts = too fast).
