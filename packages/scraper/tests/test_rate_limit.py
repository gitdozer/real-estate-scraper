"""Ritmo limitato e freno sensibile ai rallentamenti (diagnosi del 2026-10-29: da GitHub
il sito tollera ~3 richieste al secondo; a ~12 al secondo lascia appese le richieste)."""

import httpx

from scraper.config import Settings
from scraper.http import Fetcher


class Time:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    async def sleep(self, s):
        self.now += s


async def test_rate_limit_spaces_request_starts():
    t = Time()
    starts = []

    def handler(request):
        starts.append(t.now)
        return httpx.Response(200)

    f = Fetcher(6, Settings(), rate_per_s=2.0, transport=httpx.MockTransport(handler), sleep=t.sleep, clock=t.clock)
    await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(5)])
    assert starts == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert f.stats["rate_now"] == 2.0


async def test_no_rate_limit_by_default():
    t = Time()
    f = Fetcher(6, Settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200)), sleep=t.sleep, clock=t.clock)
    await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(5)])
    assert t.now == 0.0


async def test_timeouts_that_later_succeed_still_engage_the_brake():
    t = Time()
    attempts: dict[str, int] = {}

    def handler(request):
        n = attempts.get(str(request.url), 0)
        attempts[str(request.url)] = n + 1
        if n == 0:  # il primo tentativo resta appeso, il secondo riesce: come su GitHub
            raise httpx.ReadTimeout("appesa", request=request)
        return httpx.Response(200)

    f = Fetcher(6, Settings(error_window=10, max_retries=2), rate_per_s=4.0,
                transport=httpx.MockTransport(handler), sleep=t.sleep, clock=t.clock)  # fmt: skip
    results = await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(20)])
    assert all(r.ok for r in results)
    assert f.stats["concurrency_now"] < 6 and f.stats["rate_now"] < 4.0
