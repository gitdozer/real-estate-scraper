"""Diagnosis of the site's rate limit (`python -m scraper probe`).

Requests pages at a given rate, without retries, and records for each phase how many
responses arrive and how many hang (timeouts). It shows what rate the site accepts
from a given IP (e.g. GitHub). Logs contain counts only: no URLs.

Each URL is requested at most once: a repeated page may be served by the site's cache
and not count towards its limit (the 2026-10-29 probe cycled over 798 URLs and so
overestimated the volume the site tolerates, see docs/decisions/0006-rate-limiting.md).
Cumulative counts are logged every minute, to show when the site starts hanging.

Two kinds of pages can be probed: search-result pages, and detail pages, whose URLs are
first harvested from a few search-result pages read slowly (`harvest_detail_urls`).
The old scraper read detail pages at ~2.9 req/s with 4 connections without being
stalled, while search-result pages stall above ~0.5 req/s: the limits may differ.
"""

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable

import httpx

from scraper.config import Settings
from scraper.http import BROWSER_HEADERS
from scraper.sources.trovacasa import TROVACASA

log = logging.getLogger(__name__)


async def run_probe(
    urls: list[str],
    phases: list[tuple[float, float]],
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    concurrency: int = 1,
) -> list[dict]:
    """`phases` = [(requests per second, minutes), ...]. Each URL is used once, in order;
    when they run out the probe stops and the phase is marked `exhausted`.
    `concurrency` connections share one rate: request starts are at least 1/rate s apart."""
    results = []
    i = 0
    t0 = clock()
    total: Counter[str] = Counter()
    next_log = t0 + 60
    limits = httpx.Limits(max_connections=concurrency)
    async with httpx.AsyncClient(
        headers=BROWSER_HEADERS, timeout=settings.timeout_s, follow_redirects=True, transport=transport, limits=limits
    ) as client:
        for rate, minutes in phases:
            counts: Counter[str] = Counter()
            latency = 0.0
            interval = 1.0 / rate
            end = clock() + minutes * 60
            next_start = clock()
            exhausted = False
            pace = asyncio.Lock()

            async def next_url() -> str | None:
                """Waits for this worker's turn; None when the phase is over."""
                nonlocal i, next_start, next_log, exhausted
                async with pace:
                    if clock() < next_start:
                        await sleep(next_start - clock())
                    now = clock()
                    if now >= next_log:
                        log.info(
                            "[probe] minute %.0f: requests %d, ok %d, timeouts %d",
                            (now - t0) / 60, total["requests"], total["ok"], total["timeouts"],
                        )  # fmt: skip
                        while next_log <= now:
                            next_log += 60
                    if now >= end or exhausted:
                        return None
                    if i >= len(urls):
                        exhausted = True
                        log.info("[probe] URLs exhausted after %d requests", i)
                        return None
                    url = urls[i]
                    i += 1
                    next_start = max(now, next_start) + interval
                    return url

            async def worker() -> None:
                nonlocal latency
                while (url := await next_url()) is not None:
                    started = clock()
                    outcome = "ok"
                    try:
                        resp = await client.get(url)
                        if resp.status_code != 200:
                            outcome = f"http_{resp.status_code}"
                    except httpx.TimeoutException:
                        outcome = "timeouts"
                    except httpx.HTTPError as exc:
                        outcome = type(exc).__name__
                    latency += clock() - started
                    for c in (counts, total):
                        c[outcome] += 1
                        c["requests"] += 1

            await asyncio.gather(*(worker() for _ in range(concurrency)))
            phase = {
                "rate": rate, "minutes": minutes, "concurrency": concurrency, **counts,
                "latency_avg_s": round(latency / max(1, counts["requests"]), 2), "exhausted": exhausted,
            }  # fmt: skip
            for key in ("requests", "ok", "timeouts"):
                phase.setdefault(key, 0)
            shown = {k: v for k, v in phase.items() if k not in ("rate", "minutes", "concurrency")}
            log.info("[probe] %.1f req/s, %d connection(s), %g min: %s", rate, concurrency, minutes, shown)
            results.append(phase)
            if exhausted:
                break
    return results


async def harvest_detail_urls(
    list_urls: list[str],
    city: str,
    contract: str,
    rate: float,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[list[str], dict]:
    """Reads search-result pages one at a time at `rate` req/s (below the search-results
    limit) and returns the distinct detail-page URLs found, in order, plus page counts."""
    urls: dict[str, None] = {}  # ordered set
    counts = {"pages": 0, "ok": 0, "failed": 0}
    interval = 1.0 / rate
    async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=settings.timeout_s, follow_redirects=True, transport=transport) as client:
        for n, list_url in enumerate(list_urls):
            started = clock()
            counts["pages"] += 1
            try:
                resp = await client.get(list_url)
                resp.raise_for_status()
                page = TROVACASA.parse_list_page(resp.text, city, contract, n + 1)
            except Exception:  # timeout, HTTP error or unreadable page: skip it, it is only a URL source
                counts["failed"] += 1
            else:
                counts["ok"] += 1
                for card in page.cards:
                    urls.setdefault(TROVACASA.detail_url(card.url), None)
            elapsed = clock() - started
            if elapsed < interval:
                await sleep(interval - elapsed)
    log.info("[probe] harvested %d detail URLs from %s", len(urls), counts)
    return list(urls), counts
