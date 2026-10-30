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


async def test_probe_with_two_connections_keeps_two_requests_in_flight():
    # Detail pages are probed like the old scraper fetched them: several connections, one shared rate.
    # Real time, kept short: each response takes 0.1 s, rate cap 20 req/s, 1.5 s per run.
    import asyncio

    async def run(concurrency):
        in_flight = peak = 0

        async def handler(request):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.1)
            in_flight -= 1
            return httpx.Response(200, text="ok")

        result = await run_probe(
            [f"https://www.trovacasa.it/annunci/x-{i}" for i in range(1000)], phases=[(20.0, 0.025)],
            settings=Settings(), transport=httpx.MockTransport(handler), concurrency=concurrency,
        )  # fmt: skip
        return result[0]["requests"], peak

    one, peak_one = await run(1)
    two, peak_two = await run(2)
    assert peak_one == 1 and peak_two == 2
    assert two > 1.5 * one  # with 0.1 s latency one connection cannot reach the rate cap, two can


async def test_harvest_detail_urls_from_list_pages():
    from fakesite import card_html, list_page_html

    from scraper.probe import harvest_detail_urls

    t = FakeTime()
    starts = []

    def handler(request):
        starts.append(t.now)
        page = int(request.url.params.get("page", "1"))
        if page == 3:
            raise httpx.ReadTimeout("hang", request=request)
        ids = [str(page * 100 + k) for k in range(24)] + ["1"]  # "1" repeats across pages
        return httpx.Response(200, text=list_page_html([card_html(i) for i in ids], declared_total=100))

    list_urls = [f"https://www.trovacasa.it/case-in-vendita/milano?page={p}" for p in range(2, 6)]
    urls, counts = await harvest_detail_urls(
        list_urls, "milano", "vendita", rate=0.5, settings=Settings(),
        transport=httpx.MockTransport(handler), clock=t.clock, sleep=t.sleep,
    )  # fmt: skip
    assert len(urls) == len(set(urls)) == 3 * 24 + 1  # pages 2, 4, 5 + the shared listing once
    assert all(u.startswith("https://www.trovacasa.it/annunci/") for u in urls)
    assert counts == {"pages": 4, "ok": 3, "failed": 1}
    assert all(b - a >= 2.0 for a, b in zip(starts, starts[1:]))  # one list page every 2 s at most
