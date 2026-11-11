"""Async HTTP client: automatic retries, adaptive backoff, statistics (spec §6.6).

Rules:
- network errors/timeouts, 5xx and 429 responses, and the site's redirect to
  /Error/... (trovacasa's intermittent 500 errors) are retried;
- 404 and the other 4xx are final answers, not errors: a 404 carries the information
  "listing removed" and must not slow the collection down. The exceptions are 401/403/451
  (access denied: the site is blocking us), which count as failures and trigger the
  backoff and the circuit: if a source blocks us, it is dropped;
- limited request rate (`rate_per_s`): at least 1/rate seconds pass between the start of two
  requests. From GitHub, trovacasa tolerates ~3 requests/s; at ~12/s it leaves requests hanging (2026-10-29);
- every failed ATTEMPT (timeout, 5xx, 429, error redirect) counts toward the error rate,
  even if a later attempt succeeds: a site that slows down must be accommodated right away.
  If failures in the last `error_window` requests exceed `error_threshold`,
  concurrency and rate are halved; when they are already at the minimum the circuit opens
  (CircuitOpen) and the run stops cleanly;
- the deadline of `get_many` also stops retries: a request whose first attempt started
  before the deadline is not retried after it, and counts as failed.
"""

import asyncio
import random
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from scraper.config import Settings

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
}

_MAX_BACKOFF_S = 30.0
_MIN_RATE = 0.25  # requests/s: below this rate, the circuit opens instead of slowing down further
_BLOCKED = (401, 403, 451)


@dataclass
class FetchResult:
    url: str
    status: int | None
    text: str | None
    content: bytes | None
    final_url: str | None
    error: str | None
    attempts: int

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None


class CircuitOpen(Exception):
    """Too many errors even at concurrency 1: the site is struggling or blocking us.

    Raised by `get_many`, `partial` holds the results obtained before the circuit opened,
    in the order of the URLs (None = not completed), so that pages already read are kept."""

    def __init__(self, *args, partial: list["FetchResult | None"] | None = None):
        super().__init__(*args)
        self.partial = partial


class FetchStopped(CircuitOpen):
    """A response with one of the `stop_on_status` codes arrived: the following requests are
    not made. Since ~2026-11-02 one request for a missing listing (404) from a GitHub runner
    puts the IP in penalty about 10 s later, for hours (decision 0007): going on is useless."""


class Fetcher:
    def __init__(
        self,
        concurrency: int,
        settings: Settings,
        rate_per_s: float = 0.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        stop_on_status: tuple[int, ...] = (),
    ):
        self._settings = settings
        self._stop_on_status = stop_on_status
        self._stopped: str | None = None  # "http_<status>" once a stop status has been received
        self._limit = max(1, concurrency)
        self._rate = rate_per_s  # 0 = no rate limit
        self._max_limit = self._limit  # the brake release never goes beyond the configured pace
        self._max_rate = rate_per_s
        self._next_start: float | None = None
        self._pace_lock = asyncio.Lock()
        self._active = 0
        self._latency_total = 0.0
        self._latency_max = 0.0
        self._latency_n = 0
        self._cond = asyncio.Condition()
        self._window: deque[bool] = deque(maxlen=settings.error_window)
        self._circuit_open = False
        self._sleep = sleep
        self._clock = clock
        self._counts: Counter[str] = Counter()
        self._by_status: Counter[str] = Counter()
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            headers=BROWSER_HEADERS,
            timeout=settings.timeout_s,
            transport=transport,
        )

    @property
    def stats(self) -> dict:
        return {
            "requests": self._counts["requests"],
            "retries": self._counts["retries"],
            "failures": self._counts["failures"],
            "by_status": dict(self._by_status),
            "concurrency_now": self._limit,
            "rate_now": self._rate,
            "in_flight": self._active,
            "latency_avg_s": round(self._latency_total / self._latency_n, 2) if self._latency_n else 0.0,
            "latency_max_s": round(self._latency_max, 2),
            "stopped": self._stopped,
        }

    def _note_latency(self, started: float) -> None:
        elapsed = self._clock() - started
        self._latency_total += elapsed
        self._latency_n += 1
        self._latency_max = max(self._latency_max, elapsed)

    async def aclose(self) -> None:
        await self._client.aclose()

    @asynccontextmanager
    async def _slot(self):
        async with self._cond:
            await self._cond.wait_for(lambda: self._active < self._limit)
            self._active += 1
        try:
            yield
        finally:
            async with self._cond:
                self._active -= 1
                self._cond.notify_all()

    async def _pace(self) -> None:
        """Wait for our turn: requests start at least 1/rate seconds apart."""
        if self._rate <= 0:
            return
        async with self._pace_lock:
            now = self._clock()
            if self._next_start is None:
                self._next_start = now
            if self._next_start > now:
                await self._sleep(self._next_start - now)
            self._next_start = max(self._clock(), self._next_start) + 1.0 / self._rate

    def _record(self, failed: bool) -> None:
        self._window.append(failed)
        if len(self._window) < self._window.maxlen:
            return
        failure_rate = sum(self._window) / len(self._window)
        if failure_rate <= self._settings.error_threshold:
            # Brake release: after a nearly clean window (at most a quarter of the threshold,
            # i.e. 5%) go back one step, never beyond the configured pace. Without it a short
            # burst of 503s halved the detail pace for the rest of the run (2026-10-31/11-01).
            slowed = self._limit < self._max_limit or self._rate < self._max_rate
            if slowed and failure_rate <= self._settings.error_threshold / 4:
                self._window.clear()
                self._limit = min(self._max_limit, self._limit * 2)
                self._rate = min(self._max_rate, self._rate * 2)
            return
        self._window.clear()
        can_slow = self._limit > 1 or (self._rate > 0 and self._rate / 2 >= _MIN_RATE)
        if not can_slow:
            self._circuit_open = True
            return
        self._limit = max(1, self._limit // 2)
        if self._rate > 0:
            self._rate = max(_MIN_RATE, self._rate / 2)

    async def get(self, url: str, binary: bool = False) -> FetchResult:
        result = await self._get(url, binary, deadline=None)
        assert result is not None
        return result

    async def _get(self, url: str, binary: bool, deadline: float | None) -> FetchResult | None:
        status: int | None = None
        final_url: str | None = None
        error: str | None = None
        attempts = 0
        for attempt in range(1, self._settings.max_retries + 1):
            if self._circuit_open:
                raise CircuitOpen(url)
            if self._stopped is not None:
                raise FetchStopped(url)
            retry_after: float | None = None
            # Past the deadline nothing waits for a slot or for the pace: on 2026-11-11 the
            # 16,000 photo requests left at the photo deadline were skipped one at a time at
            # the configured pace (0.25 s each, over an hour) and GitHub cancelled the job.
            if deadline is not None and self._clock() >= deadline:
                if attempt == 1:
                    return None
                break
            async with self._slot():
                await self._pace()
                # Checked right before EVERY attempt, after waiting for a slot and for the pace:
                # retries queued behind other requests used to start after the deadline, one 30 s
                # timeout each, and the phase never ended (2026-11-04/07).
                if deadline is not None and self._clock() >= deadline:
                    if attempt == 1:
                        return None  # never attempted: skipped, it stays in the queue for tomorrow
                    break  # already attempted: it counts as failed
                # Checked again here, for the same reason: every request of a chunk passes the
                # check at the top at once, before waiting for a slot, so a stop status seen in
                # the meantime did not stop them (run of 2026-11-10).
                if self._circuit_open:
                    raise CircuitOpen(url)
                if self._stopped is not None:
                    raise FetchStopped(url)
                attempts = attempt
                self._counts["requests"] += 1
                started = self._clock()
                try:
                    # httpx's timeout applies between bytes, not to the whole request: a response
                    # that never completes kept the details phase stuck until GitHub cancelled the
                    # job (2026-11-02/03). The total limit turns it into an ordinary failed attempt.
                    resp = await asyncio.wait_for(self._client.get(url), timeout=2 * self._settings.timeout_s)
                except httpx.HTTPError as exc:
                    self._note_latency(started)
                    status, final_url, error = None, None, type(exc).__name__
                    self._by_status[error] += 1
                except TimeoutError:
                    self._note_latency(started)
                    status, final_url, error = None, None, "total_timeout"
                    self._by_status[error] += 1
                else:
                    self._note_latency(started)
                    status, final_url = resp.status_code, str(resp.url)
                    self._by_status[str(status)] += 1
                    if resp.url.path.startswith("/Error/"):
                        error = "error_redirect"
                    elif status == 429 or status >= 500:
                        error = f"http_{status}"
                        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    else:
                        blocked = status in _BLOCKED
                        if blocked:
                            self._counts["failures"] += 1
                        if status in self._stop_on_status:
                            self._stopped = f"http_{status}"
                        self._record(failed=blocked)
                        return FetchResult(
                            url=url,
                            status=status,
                            text=None if binary else resp.text,
                            content=resp.content if binary else None,
                            final_url=final_url,
                            error=f"http_{status}" if blocked else None,
                            attempts=attempt,
                        )
            self._record(failed=True)  # every failed attempt counts, even if the next one succeeds
            if deadline is not None and self._clock() >= deadline:
                break  # past the deadline no retries: the request counts as failed (not as skipped)
            if attempt < self._settings.max_retries:
                self._counts["retries"] += 1
                wait = min(_MAX_BACKOFF_S, retry_after) if retry_after is not None else min(_MAX_BACKOFF_S, 2.0**attempt) + random.uniform(0, 1)
                await self._sleep(wait)
        self._counts["failures"] += 1
        return FetchResult(url=url, status=status, text=None, content=None, final_url=final_url, error=error, attempts=attempts)

    async def get_many(self, urls: list[str], binary: bool = False, deadline: float | None = None) -> list[FetchResult | None]:
        """Download in parallel, in the given order. None = not made because the deadline had passed."""
        tasks = [asyncio.ensure_future(self._get(u, binary, deadline)) for u in urls]
        try:
            return list(await asyncio.gather(*tasks))
        except CircuitOpen as exc:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            partial = [t.result() if t.done() and not t.cancelled() and t.exception() is None else None for t in tasks]
            raise type(exc)(*exc.args, partial=partial) from exc


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
