"""Comando di diagnosi: misura quante richieste il sito accetta a ritmi diversi."""

import logging

import httpx

from scraper.config import Settings
from scraper.probe import run_probe


class FakeTime:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    async def sleep(self, s):
        self.now += s


async def test_probe_paces_requests_and_reports_per_minute(caplog):
    caplog.set_level(logging.INFO, logger="scraper")
    t = FakeTime()
    seen = []

    def handler(request):
        seen.append(t.now)
        return httpx.Response(200, text="ok")

    result = await run_probe(
        ["https://www.trovacasa.it/case-in-vendita/milano"],
        phases=[(1.0, 2.0), (2.0, 1.0)],  # (richieste al secondo, minuti)
        settings=Settings(),
        transport=httpx.MockTransport(handler),
        clock=t.clock,
        sleep=t.sleep,
    )
    assert [p["requests"] for p in result] == [120, 120]
    assert all(p["ok"] == p["requests"] for p in result)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "[probe] 1.0 req/s" in text and "http" not in text


async def test_probe_counts_timeouts():
    t = FakeTime()

    def handler(request):
        raise httpx.ReadTimeout("lento", request=request)

    result = await run_probe(
        ["https://www.trovacasa.it/x"], phases=[(1.0, 1.0)], settings=Settings(),
        transport=httpx.MockTransport(handler), clock=t.clock, sleep=t.sleep,
    )  # fmt: skip
    assert result[0]["timeouts"] == result[0]["requests"] > 0
