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
        [f"https://www.trovacasa.it/case-in-vendita/milano?page={i}" for i in range(2, 400)],
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
        [f"https://www.trovacasa.it/x?page={i}" for i in range(2, 100)], phases=[(1.0, 1.0)], settings=Settings(),
        transport=httpx.MockTransport(handler), clock=t.clock, sleep=t.sleep,
    )  # fmt: skip
    assert result[0]["timeouts"] == result[0]["requests"] > 0


async def test_probe_never_repeats_a_url_and_stops_when_they_run_out(caplog):
    # A repeated URL may be served by the site's cache and not count towards its limit:
    # the 2026-10-29 probe cycled over 798 URLs and overestimated the tolerated volume.
    caplog.set_level(logging.INFO, logger="scraper")
    t = FakeTime()
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, text="ok")

    urls = [f"https://www.trovacasa.it/x?page={i}" for i in range(2, 52)]
    result = await run_probe(
        urls, phases=[(1.0, 1.0), (1.0, 1.0)], settings=Settings(),
        transport=httpx.MockTransport(handler), clock=t.clock, sleep=t.sleep,
    )  # fmt: skip
    assert len(seen) == len(set(seen)) == 50
    assert [p["requests"] for p in result] == [50]  # the second phase never starts
    assert result[0]["exhausted"] is True
    assert "URLs exhausted" in "\n".join(r.getMessage() for r in caplog.records)


async def test_probe_logs_cumulative_counts_every_minute(caplog):
    # A 40-minute phase must show WHEN the site starts hanging, not just the final totals.
    caplog.set_level(logging.INFO, logger="scraper")
    t = FakeTime()
    n = 0

    def handler(request):
        nonlocal n
        n += 1
        if n > 90:
            t.now += 30  # the site starts hanging after 90 requests
            raise httpx.ReadTimeout("hang", request=request)
        return httpx.Response(200, text="ok")

    await run_probe(
        [f"https://www.trovacasa.it/x?page={i}" for i in range(2, 1000)], phases=[(1.0, 3.0)], settings=Settings(),
        transport=httpx.MockTransport(handler), clock=t.clock, sleep=t.sleep,
    )  # fmt: skip
    minute_lines = [r.getMessage() for r in caplog.records if "[probe] minute" in r.getMessage()]
    assert len(minute_lines) >= 2
    assert "requests 60" in minute_lines[0] and "timeouts 0" in minute_lines[0]
    assert "http" not in "\n".join(minute_lines)
