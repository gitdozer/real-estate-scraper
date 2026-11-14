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

A third kind asks the map endpoint of the search results (`probe_geojson`): since
2026-11-12 the search-result pages are blocked from GitHub's IPs after ~100-200 pages,
and the map returns the whole search in one request per segment.
"""

import asyncio
import json
import logging
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable

import httpx

from scraper.config import Settings
from scraper.http import BROWSER_HEADERS
from scraper.sources.trovacasa import TROVACASA, geojson_url, list_url

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


_JSON_HEADERS = {**BROWSER_HEADERS, "Accept": "application/json, text/plain, */*"}


async def probe_geojson(
    segments: list[tuple[str, str]],
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    interval_s: float = 10.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[dict]:
    """Asks the map endpoint for every segment (city slug, contract), one request every
    `interval_s` seconds, then page 1 of each segment's search results for the declared
    total. Returns one row of counts per segment (no listing data): outcome, size, number
    of features, how many carry an `id` and coordinates, the property keys, and the
    coverage = features with an id / declared total."""
    rows = [
        dict(
            city=city, contract=contract, outcome="", status=None, bytes=0, content_type="", latency_s=0.0,
            features=0, with_id=0, with_coordinates=0, declared=None, coverage=None, property_keys=[], geometry_types=[],
        )
        for city, contract in segments
    ]  # fmt: skip
    next_start = clock()

    async def paced_get(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> tuple[httpx.Response | None, str, float]:
        """One request at the pace; returns (response or None, outcome, latency)."""
        nonlocal next_start
        if clock() < next_start:
            await sleep(next_start - clock())
        next_start = clock() + interval_s
        started = clock()
        try:
            resp = await client.get(url, headers=headers)
        except httpx.TimeoutException:
            return None, "timeouts", clock() - started
        except httpx.HTTPError as exc:
            return None, type(exc).__name__, clock() - started
        return resp, "ok" if resp.status_code == 200 else f"http_{resp.status_code}", clock() - started

    async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=settings.timeout_s, follow_redirects=True, transport=transport) as client:
        for row in rows:
            resp, outcome, latency = await paced_get(client, geojson_url(row["city"], row["contract"]), _JSON_HEADERS)
            row.update(outcome=outcome, latency_s=round(latency, 2))
            if resp is not None:
                row.update(status=resp.status_code, bytes=len(resp.content), content_type=resp.headers.get("content-type", "").split(";")[0])
            if outcome == "ok":
                row.update(_describe_geojson(resp.content))
            log.info(
                "[probe] map %s %s: %s, %d bytes, %d features (%d with id, %d with coordinates) in %.1f s",
                row["city"], row["contract"], row["outcome"], row["bytes"], row["features"], row["with_id"],
                row["with_coordinates"], row["latency_s"],
            )  # fmt: skip
        for row in rows:
            # The declared total of the segment, from page 1 of its search results (a page the
            # site still serves: the block of 2026-11-12 starts after ~100 pages).
            resp, outcome, _ = await paced_get(client, list_url(row["city"], row["contract"], 1), BROWSER_HEADERS)
            if resp is not None and outcome == "ok":
                try:
                    row["declared"] = TROVACASA.parse_list_page(resp.text, row["city"], row["contract"], 1).declared_total
                except Exception:  # unreadable page: the coverage stays unknown
                    row["declared"] = None
            if row["declared"] and row["outcome"] == "ok":
                row["coverage"] = round(row["with_id"] / row["declared"], 3)
            log.info("[probe] page 1 %s %s: %s, declared %s", row["city"], row["contract"], outcome, row["declared"])
    return rows


def _describe_geojson(body: bytes) -> dict:
    """Counts over a GeoJSON body: no listing data leaves this function."""
    try:
        data = json.loads(body)
        features = data["features"]
        assert isinstance(features, list)
    except Exception:
        return dict(outcome="not_geojson")
    keys: set[str] = set()
    geometry: set[str] = set()
    with_id = with_coords = 0
    for f in features:
        props = f.get("properties") or {}
        keys.update(props)
        if props.get("id") not in (None, ""):
            with_id += 1
        geom = f.get("geometry") or {}
        if geom.get("coordinates"):
            with_coords += 1
            geometry.add(str(geom.get("type")))
    return dict(
        features=len(features), with_id=with_id, with_coordinates=with_coords,
        property_keys=sorted(keys), geometry_types=sorted(geometry),
    )  # fmt: skip


_LISTING_ID = re.compile(r"^(.*-)(\d+)/?$")
_MISSING_ID_BASE = 900_000_000  # far above any listing id seen so far (~74 million in 2026-11)


def missing_detail_urls(harvested: list[str], n: int) -> list[str]:
    """`n` detail URLs for listings that do not exist (the site answers 404, like for a
    removed listing). Built from harvested URLs by replacing the listing id, so that the
    host, path and agency part are real. The daily run's detail phase starts with absence
    checks, i.e. such 404s; this reproduces that burst in the probe (2026-11-08)."""
    if not harvested:
        return []
    urls = []
    for k in range(n):
        m = _LISTING_ID.match(harvested[k % len(harvested)])
        if m is None:
            continue
        urls.append(f"{m.group(1)}{_MISSING_ID_BASE + k + 1}")
    return urls


def interleave_missing_detail_urls(valid: list[str], every: int) -> list[str]:
    """One request for a missing listing after every `every` valid detail pages (0 = none):
    measures the 404 density the site tolerates, once a burst of ~10 proved to trigger the
    penalty (probe of 2026-11-08). The missing ids are distinct across the whole list."""
    if every <= 0 or not valid:
        return list(valid)
    missing = missing_detail_urls(valid, len(valid) // every)
    out: list[str] = []
    for k, url in enumerate(valid, start=1):
        out.append(url)
        if k % every == 0 and missing:
            out.append(missing.pop(0))
    return out


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
