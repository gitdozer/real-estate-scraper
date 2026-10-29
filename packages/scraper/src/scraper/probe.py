"""Diagnosi del limite di frequenza del sito (`python -m scraper probe`).

Fa richieste alle pagine elenco a ritmi crescenti, una alla volta e senza tentativi,
e registra per ogni fase quante risposte arrivano e quante restano appese (timeout).
Serve a scoprire a che ritmo il sito accetta le richieste da un certo IP (es. GitHub).
Nei log solo conteggi: nessun URL.
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
    """`phases` = [(richieste al secondo, minuti), ...]. Le richieste girano sugli URL dati."""
    results = []
    i = 0
    async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=settings.timeout_s, follow_redirects=True, transport=transport) as client:
        for rate, minutes in phases:
            counts: Counter[str] = Counter()
            latency = 0.0
            interval = 1.0 / rate
            end = clock() + minutes * 60
            while clock() < end:
                started = clock()
                try:
                    resp = await client.get(urls[i % len(urls)])
                    counts["ok" if resp.status_code == 200 else f"http_{resp.status_code}"] += 1
                except httpx.TimeoutException:
                    counts["timeouts"] += 1
                except httpx.HTTPError as exc:
                    counts[type(exc).__name__] += 1
                i += 1
                counts["requests"] += 1
                elapsed = clock() - started
                latency += elapsed
                if elapsed < interval:
                    await sleep(interval - elapsed)
            phase = {"rate": rate, "minutes": minutes, **counts, "latency_avg_s": round(latency / max(1, counts["requests"]), 2)}
            phase.setdefault("ok", 0)
            phase.setdefault("timeouts", 0)
            log.info("[probe] %.1f req/s per %.0f min: %s", rate, minutes, {k: v for k, v in phase.items() if k not in ("rate", "minutes")})
            results.append(phase)
    return results
