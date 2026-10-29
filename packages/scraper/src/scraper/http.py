"""Client HTTP asincrono: tentativi automatici, freno adattivo, statistiche (spec §6.6).

Regole:
- si ritentano errori di rete/timeout, risposte 5xx e 429, e il redirect del sito
  verso /Error/... (errori 500 intermittenti di trovacasa);
- 404 e gli altri 4xx sono risposte definitive, non errori: un 404 è l'informazione
  "annuncio rimosso" e non deve frenare la raccolta. Fanno eccezione 401/403/451
  (accesso negato: il sito ci sta bloccando), che contano come fallimenti e azionano
  il freno e il circuito: se una fonte blocca, la si abbandona;
- ritmo limitato (`rate_per_s`): tra l'inizio di due richieste passa almeno 1/rate secondi.
  Da GitHub trovacasa tollera ~3 richieste/s; a ~12/s lascia appese le richieste (2026-10-29);
- ogni TENTATIVO fallito (timeout, 5xx, 429, redirect di errore) conta nel tasso di errori,
  anche se un tentativo successivo riesce: un sito che rallenta va assecondato subito.
  Se nelle ultime `error_window` richieste i fallimenti superano `error_threshold`,
  concorrenza e ritmo si dimezzano; quando sono già al minimo si apre il circuito
  (CircuitOpen) e il run si ferma in modo pulito.
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
_MIN_RATE = 0.25  # richieste/s: sotto questo ritmo, invece di rallentare ancora, si apre il circuito
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
    """Troppi errori anche a concorrenza 1: il sito è in difficoltà o ci sta bloccando."""


class Fetcher:
    def __init__(
        self,
        concurrency: int,
        settings: Settings,
        rate_per_s: float = 0.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._settings = settings
        self._limit = max(1, concurrency)
        self._rate = rate_per_s  # 0 = nessun limite di ritmo
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
        """Attende il proprio turno: le richieste partono distanziate di almeno 1/rate secondi."""
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
        if sum(self._window) / len(self._window) <= self._settings.error_threshold:
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
            retry_after: float | None = None
            async with self._slot():
                if attempt == 1 and deadline is not None and self._clock() >= deadline:
                    return None
                attempts = attempt
                await self._pace()
                self._counts["requests"] += 1
                started = self._clock()
                try:
                    resp = await self._client.get(url)
                except httpx.HTTPError as exc:
                    self._note_latency(started)
                    status, final_url, error = None, None, type(exc).__name__
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
            self._record(failed=True)  # ogni tentativo fallito conta, anche se il prossimo riesce
            if attempt < self._settings.max_retries:
                self._counts["retries"] += 1
                wait = min(_MAX_BACKOFF_S, retry_after) if retry_after is not None else min(_MAX_BACKOFF_S, 2.0**attempt) + random.uniform(0, 1)
                await self._sleep(wait)
        self._counts["failures"] += 1
        return FetchResult(url=url, status=status, text=None, content=None, final_url=final_url, error=error, attempts=attempts)

    async def get_many(self, urls: list[str], binary: bool = False, deadline: float | None = None) -> list[FetchResult | None]:
        """Scarica in parallelo, nell'ordine dato. None = non eseguita perché la scadenza era passata."""
        tasks = [asyncio.ensure_future(self._get(u, binary, deadline)) for u in urls]
        try:
            return list(await asyncio.gather(*tasks))
        except CircuitOpen:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
