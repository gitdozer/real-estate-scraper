import httpx
import pytest

from scraper.config import Settings
from scraper.http import CircuitOpen, Fetcher


class FakeSleep:
    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make(handler, concurrency=6, **settings) -> tuple[Fetcher, FakeSleep]:
    sleep = FakeSleep()
    fetcher = Fetcher(concurrency, Settings(**settings), transport=httpx.MockTransport(handler), sleep=sleep)
    return fetcher, sleep


def sequence(*responses):
    """Handler che restituisce le risposte in ordine (l'ultima si ripete)."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        r = responses[min(len(calls) - 1, len(responses) - 1)]
        return r(request) if callable(r) else r

    handler.calls = calls
    return handler


async def test_retries_500_then_succeeds():
    f, sleep = make(sequence(httpx.Response(500), httpx.Response(500), httpx.Response(200, text="ok")))
    r = await f.get("https://www.trovacasa.it/x")
    assert r.ok and r.text == "ok" and r.attempts == 3 and len(sleep.calls) == 2
    assert f.stats["retries"] == 2 and f.stats["failures"] == 0


async def test_error_redirect_is_retried():
    def first(request):
        return httpx.Response(302, headers={"Location": "/Error/InternalServerError?path=x"})

    def error_page(request):
        return httpx.Response(200, text="errore")

    handler = sequence(first, error_page, httpx.Response(200, text="pagina"))
    f, _ = make(handler)
    r = await f.get("https://www.trovacasa.it/case-in-affitto/milano?page=50")
    assert r.ok and r.text == "pagina" and r.attempts == 2


async def test_404_not_retried():
    f, sleep = make(sequence(httpx.Response(404)))
    r = await f.get("https://www.trovacasa.it/annunci/x-1")
    assert r.status == 404 and r.attempts == 1 and r.error is None and not r.ok and sleep.calls == []


async def test_429_honours_retry_after():
    f, sleep = make(sequence(httpx.Response(429, headers={"Retry-After": "5"}), httpx.Response(200)))
    r = await f.get("https://www.trovacasa.it/x")
    assert r.ok and sleep.calls == [5.0]


async def test_network_error_is_retried():
    def boom(request):
        raise httpx.ConnectError("connessione rifiutata", request=request)

    f, _ = make(sequence(boom, httpx.Response(200)))
    r = await f.get("https://www.trovacasa.it/x")
    assert r.ok and r.attempts == 2


async def test_gives_up_after_max_retries():
    f, sleep = make(sequence(httpx.Response(503)))
    r = await f.get("https://www.trovacasa.it/x")
    assert r.status == 503 and r.attempts == 4 and r.error and len(sleep.calls) == 3
    assert f.stats["failures"] == 1


async def test_binary_content():
    f, _ = make(sequence(httpx.Response(200, content=b"\x89PNG")))
    r = await f.get("https://img.trovacasa.it/a.jpg", binary=True)
    assert r.content == b"\x89PNG"


async def test_concurrency_halves_on_error_rate():
    def handler(request):
        n = int(request.url.params["n"])
        return httpx.Response(503 if n < 3 else 200)

    f, _ = make(handler, concurrency=6, error_window=10, max_retries=1)
    await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(10)])
    assert f.stats["concurrency_now"] == 3


async def test_circuit_opens_at_concurrency_one():
    f, _ = make(sequence(httpx.Response(503)), concurrency=2, error_window=5, max_retries=1)
    with pytest.raises(CircuitOpen):
        await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(30)])


async def test_404_does_not_count_as_error():
    f, _ = make(sequence(httpx.Response(404)), concurrency=6, error_window=5, max_retries=1)
    await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(20)])
    assert f.stats["concurrency_now"] == 6


async def test_get_many_stops_at_deadline():
    sleep = FakeSleep()
    f = Fetcher(6, Settings(), transport=httpx.MockTransport(sequence(httpx.Response(200))), sleep=sleep, clock=lambda: 100.0)
    results = await f.get_many(["https://www.trovacasa.it/a", "https://www.trovacasa.it/b"], deadline=50.0)
    assert results == [None, None]


async def test_get_many_preserves_order():
    def handler(request):
        return httpx.Response(200, text=request.url.params["n"])

    f, _ = make(handler)
    results = await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(15)])
    assert [r.text for r in results] == [str(i) for i in range(15)]
