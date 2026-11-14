"""Probe command: measures how many requests the site accepts at different rates."""

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
        phases=[(1.0, 2.0), (2.0, 1.0)],  # (requests per second, minutes)
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


def test_missing_detail_urls_keeps_the_site_and_agency_but_uses_ids_that_do_not_exist():
    # Hypothesis of 2026-11-08: the daily run's detail phase starts with absence checks
    # (listings gone from the search results, answered 404) and every failed run stalled
    # right after that burst of 404s. The probe reproduces the burst with made-up listing
    # ids: the site answers 404 for an unknown id exactly as for a removed listing.
    from scraper.probe import missing_detail_urls

    harvested = [
        "https://www.trovacasa.it/annunci/mi-tc-64698-74085984",
        "https://www.trovacasa.it/annunci/mi-tc-78833-74085991/",
        "https://www.trovacasa.it/annunci/mi-tc-1-5",
    ]
    dead = missing_detail_urls(harvested, 2)
    assert dead == [
        "https://www.trovacasa.it/annunci/mi-tc-64698-900000001",
        "https://www.trovacasa.it/annunci/mi-tc-78833-900000002",
    ]
    assert not set(dead) & set(harvested)


def test_missing_detail_urls_handles_more_requests_than_harvested_urls():
    from scraper.probe import missing_detail_urls

    dead = missing_detail_urls(["https://www.trovacasa.it/annunci/mi-tc-7-8"], 3)
    assert len(dead) == len(set(dead)) == 3
    assert all(u.startswith("https://www.trovacasa.it/annunci/mi-tc-7-9000000") for u in dead)
    assert missing_detail_urls([], 3) == []


def test_interleave_missing_detail_urls_puts_one_missing_listing_every_n_valid_pages():
    # Second step of 2026-11-08: a burst of ~10 × 404 triggers the penalty; this measures
    # the 404 density the site tolerates when the requests are spread among valid pages.
    from scraper.probe import interleave_missing_detail_urls

    valid = [f"https://www.trovacasa.it/annunci/mi-tc-1-{i}" for i in range(1, 8)]
    mixed = interleave_missing_detail_urls(valid, every=3)
    assert [u.rsplit("-", 1)[1] for u in mixed] == ["1", "2", "3", "900000001", "4", "5", "6", "900000002", "7"]
    assert interleave_missing_detail_urls(valid, every=0) == valid


def _geojson(features: list[dict]) -> str:
    import json

    return json.dumps({"type": "FeatureCollection", "features": features})


def _feature(fid: int | None, coords: list[float] | None, **props) -> dict:
    p = dict(props)
    if fid is not None:
        p["id"] = fid
    return {"type": "Feature", "geometry": None if coords is None else {"type": "Point", "coordinates": coords}, "properties": p}


async def test_probe_geojson_visits_page_1_first_then_asks_the_map_with_the_same_session(caplog):
    # 2026-11-14: the search results are blocked from GitHub's IPs; the map endpoint returns
    # the whole search in one request. The first probe (map first, no session) got 401 on
    # every segment: the site's own page calls it with jQuery after the page is loaded, so
    # the probe visits page 1 first (cookies, declared total) and asks the map with the
    # same client, the key encoded as jQuery sends it.
    from fakesite import card_html, list_page_html
    from scraper.probe import probe_geojson

    caplog.set_level(logging.INFO, logger="scraper")
    t = FakeTime()
    seen: list[tuple[float, str, dict]] = []

    def handler(request):
        seen.append((t.now, str(request.url), dict(request.headers)))
        if request.url.path == "/ricerca/geojson":
            key = request.url.params["cacheKey"]
            if key == "/case-in-affitto/milano" or "s=1" not in request.headers.get("cookie", ""):
                return httpx.Response(401, text="<html><head><title>Accesso negato</title></head><body>no</body></html>")
            features = [
                _feature(1, [9.19, 45.46], prezzodescr="100.000", tipodescr="Trilocale"),
                _feature(2, [9.20, 45.47], prezzodescr="200.000"),
                _feature(None, [9.21, 45.48], titolo="x"),
                _feature(4, None, prezzodescr="300.000"),
            ]
            return httpx.Response(200, text=_geojson(features), headers={"content-type": "application/json"})
        return httpx.Response(200, text=list_page_html([card_html("1")], declared_total=5), headers={"set-cookie": "s=1; Path=/"})

    rows = await probe_geojson(
        [("milano", "vendita"), ("milano", "affitto")], Settings(), transport=httpx.MockTransport(handler),
        interval_s=10.0, clock=t.clock, sleep=t.sleep,
    )  # fmt: skip
    assert [u.split("trovacasa.it")[1] for _, u, _ in seen] == [
        "/case-in-vendita/milano",
        "/ricerca/geojson?cacheKey=%2Fcase-in-vendita%2Fmilano",  # the key encoded as jQuery sends it
        "/case-in-affitto/milano",
        "/ricerca/geojson?cacheKey=%2Fcase-in-affitto%2Fmilano",
    ]
    assert [round(s) for s, _, _ in seen] == [0, 10, 20, 30]  # one request every interval_s
    h = [hd for _, _, hd in seen]
    assert h[0]["accept"].startswith("text/html") and h[1]["accept"].startswith("application/json")
    assert "referer" not in h[1] and "x-requested-with" not in h[1]  # the session's cookies only
    sale, rent = rows
    assert sale["outcome"] == "ok" and sale["cookies"] == 1
    assert sale["features"] == 4 and sale["with_id"] == 3 and sale["with_coordinates"] == 3
    assert sale["declared"] == 5 and sale["coverage"] == 0.6  # features with an id / declared total
    assert sale["bytes"] > 0 and sale["content_type"] == "application/json" and sale["title"] == ""
    assert sale["property_keys"] == ["id", "prezzodescr", "tipodescr", "titolo"] and sale["geometry_types"] == ["Point"]
    assert rent["outcome"] == "http_401" and rent["title"] == "Accesso negato"
    assert rent["features"] == 0 and rent["declared"] == 5 and rent["coverage"] is None
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "[probe] map milano vendita: ok" in text and "9.19" not in text and "100.000" not in text and "s=1" not in text


async def test_probe_geojson_records_timeouts_and_unreadable_bodies_without_stopping():
    from scraper.probe import probe_geojson

    t = FakeTime()

    def handler(request):
        if request.url.path == "/ricerca/geojson":
            if request.url.params["cacheKey"].endswith("/monza"):
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.Response(200, text="<html>not json</html>", headers={"content-type": "text/html"})
        raise httpx.ReadTimeout("slow", request=request)

    rows = await probe_geojson(
        [("monza", "vendita"), ("legnano", "vendita")], Settings(), transport=httpx.MockTransport(handler),
        interval_s=1.0, clock=t.clock, sleep=t.sleep,
    )  # fmt: skip
    assert [r["outcome"] for r in rows] == ["timeouts", "not_geojson"]
    assert rows[1]["content_type"] == "text/html" and rows[1]["features"] == 0 and rows[1]["title"] == ""
    assert all(r["declared"] is None and r["coverage"] is None and r["cookies"] == 0 for r in rows)
