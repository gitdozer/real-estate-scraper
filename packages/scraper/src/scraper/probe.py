"""Diagnosi del limite di frequenza del sito (`python -m scraper probe`).

Fa richieste alle pagine elenco a ritmi crescenti, una alla volta e senza tentativi,
e registra per ogni fase quante risposte arrivano e quante restano appese (timeout).
Serve a scoprire a che ritmo il sito accetta le richieste da un certo IP (es. GitHub).
Nei log solo conteggi: nessun URL.

Each URL is requested at most once: a repeated page may be served by the site's cache
and not count towards its limit (the 2026-10-29 probe cycled over 798 URLs and so
overestimated the volume the site tolerates, see docs/decisions/0006-rate-limiting.md).
Cumulative counts are logged every minute, to show when the site starts hanging.
"""

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable

import httpx

from scraper.config import Settings
from scraper.http import BROWSER_HEADERS

log = logging.getLogger(__name__)


async def run_probe(
    urls: list[str],
    phases: list[tuple[float, float]],
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[dict]:
    """`phases` = [(richieste al secondo, minuti), ...]. Each URL is used once, in order;
    when they run out the probe stops and the phase is marked `exhausted`."""
    results = []
    i = 0
    t0 = clock()
    total: Counter[str] = Counter()
    next_log = t0 + 60
    async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=settings.timeout_s, follow_redirects=True, transport=transport) as client:
        for rate, minutes in phases:
            counts: Counter[str] = Counter()
            latency = 0.0
            interval = 1.0 / rate
            end = clock() + minutes * 60
            exhausted = False
            while clock() < end:
                if clock() >= next_log:
                    log.info(
                        "[probe] minute %.0f: requests %d, ok %d, timeouts %d",
                        (clock() - t0) / 60, total["requests"], total["ok"], total["timeouts"],
                    )  # fmt: skip
                    while next_log <= clock():
                        next_log += 60
                if i >= len(urls):
                    exhausted = True
                    log.info("[probe] URLs exhausted after %d requests", i)
                    break
                started = clock()
                outcome = "ok"
                try:
                    resp = await client.get(urls[i])
                    if resp.status_code != 200:
                        outcome = f"http_{resp.status_code}"
                except httpx.TimeoutException:
                    outcome = "timeouts"
                except httpx.HTTPError as exc:
                    outcome = type(exc).__name__
                i += 1
                for c in (counts, total):
                    c[outcome] += 1
                    c["requests"] += 1
                elapsed = clock() - started
                latency += elapsed
                if elapsed < interval:
                    await sleep(interval - elapsed)
            phase = {"rate": rate, "minutes": minutes, **counts, "latency_avg_s": round(latency / max(1, counts["requests"]), 2), "exhausted": exhausted}
            phase.setdefault("requests", 0)
            phase.setdefault("ok", 0)
            phase.setdefault("timeouts", 0)
            log.info("[probe] %.1f req/s per %.0f min: %s", rate, minutes, {k: v for k, v in phase.items() if k not in ("rate", "minutes")})
            results.append(phase)
            if exhausted:
                break
    return results
