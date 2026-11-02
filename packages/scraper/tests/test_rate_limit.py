"""Limited request rate and a backoff that reacts to slowdowns (probe of 2026-10-29: from GitHub
the site tolerates ~3 requests per second; at ~12 per second it leaves requests hanging)."""

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
    import asyncio

    class YieldingTime(Time):
        async def sleep(self, s):  # like asyncio.sleep, the backoff lets the other requests run
            self.now += s
            await asyncio.sleep(0)

    t = YieldingTime()
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
        if n == 0:  # the first attempt hangs, the second succeeds: as on GitHub
            raise httpx.ReadTimeout("hung", request=request)
        return httpx.Response(200)

    f = Fetcher(6, Settings(error_window=10, max_retries=2), rate_per_s=4.0,
                transport=httpx.MockTransport(handler), sleep=t.sleep, clock=t.clock)  # fmt: skip
    results = await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(20)])
    assert all(r.ok for r in results)
    assert f.stats["concurrency_now"] < 6 and f.stats["rate_now"] < 4.0


async def _drive(fetcher, outcomes):
    """Sends one request per outcome, in order: True = the site fails it (503), False = 200."""
    for failed in outcomes:
        await fetcher.get(f"https://www.trovacasa.it/annunci/x-{'f' if failed else 'ok'}-{id(object())}")


def _fetcher(concurrency=2, rate=1.5, window=5):
    t = Time()

    def handler(request):
        return httpx.Response(503 if "-f-" in str(request.url) else 200)

    f = Fetcher(concurrency, Settings(error_window=window, max_retries=1), rate_per_s=rate,
                transport=httpx.MockTransport(handler), sleep=t.sleep, clock=t.clock)  # fmt: skip
    return f


async def test_brake_is_released_after_a_clean_window():
    # 2026-10-31/11-01: a short burst of 503s halved the detail pace for the rest of the run.
    f = _fetcher()
    await _drive(f, [True] * 5)  # failure window -> halved
    assert (f.stats["concurrency_now"], f.stats["rate_now"]) == (1, 0.75)
    await _drive(f, [False] * 5)  # a clean window -> back one step
    assert (f.stats["concurrency_now"], f.stats["rate_now"]) == (2, 1.5)


async def test_brake_release_never_exceeds_the_configured_pace():
    f = _fetcher()
    await _drive(f, [False] * 50)
    assert (f.stats["concurrency_now"], f.stats["rate_now"]) == (2, 1.5)


async def test_brake_is_released_one_step_at_a_time():
    f = _fetcher(concurrency=1, rate=1.5)
    await _drive(f, [True] * 10)  # two failure windows: 1.5 -> 0.75 -> 0.375
    assert f.stats["rate_now"] == 0.375
    await _drive(f, [False] * 5)
    assert f.stats["rate_now"] == 0.75
    await _drive(f, [False] * 5)
    assert f.stats["rate_now"] == 1.5


async def test_brake_is_not_released_while_errors_go_on():
    # 1 failure in 5 (20%): not enough to brake further, too many to speed up again.
    f = _fetcher()
    await _drive(f, [True] * 5)
    await _drive(f, [False, False, True, False, False] * 4)
    assert (f.stats["concurrency_now"], f.stats["rate_now"]) == (1, 0.75)


async def test_no_request_starts_after_the_deadline_even_for_queued_retries():
    # 2026-11-04/07: detail pages all timed out; after the deadline every request queued for
    # its 2nd-4th attempt still made one more 30 s attempt, so the phase never ended and GitHub
    # cancelled the job before anything was written.
    import asyncio

    class YieldingTime(Time):
        async def sleep(self, s):  # like asyncio.sleep, the backoff lets the other requests run
            self.now += s
            await asyncio.sleep(0)

    t = YieldingTime()
    starts = []

    def handler(request):
        starts.append(t.now)
        t.now += 30.0  # each attempt hangs until the timeout
        raise httpx.ReadTimeout("hang", request=request)

    f = Fetcher(1, Settings(max_retries=4, error_window=10_000), rate_per_s=0,
                transport=httpx.MockTransport(handler), sleep=t.sleep, clock=t.clock)  # fmt: skip
    results = await f.get_many([f"https://www.trovacasa.it/annunci/x-{i}" for i in range(50)], deadline=300.0)
    assert starts and max(starts) < 300.0  # nothing starts at or after the deadline
    assert all(r is None or not r.ok for r in results)
