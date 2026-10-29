"""Diagnosi dei blocchi: latenze delle richieste e battito periodico durante le fasi lunghe."""

import asyncio
import logging

import httpx

from scraper.config import Settings
from scraper.http import Fetcher
from scraper.pipeline import _heartbeat


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


async def test_stats_report_latency_and_in_flight():
    clock = Clock()

    def handler(request):
        clock.now += 2.0  # ogni richiesta "dura" 2 secondi
        return httpx.Response(200, text="ok")

    f = Fetcher(2, Settings(), transport=httpx.MockTransport(handler), clock=clock)
    await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(3)])
    s = f.stats
    assert s["in_flight"] == 0
    assert s["latency_avg_s"] == 2.0 and s["latency_max_s"] == 2.0


async def test_heartbeat_logs_progress_without_urls(caplog):
    caplog.set_level(logging.INFO, logger="scraper")
    f = Fetcher(2, Settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    task = asyncio.create_task(_heartbeat(f, "elenchi", lambda: 1.5, every_s=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "[elenchi] in corso" in text and "richieste" in text and "http" not in text
