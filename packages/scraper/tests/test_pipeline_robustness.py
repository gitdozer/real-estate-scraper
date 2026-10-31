"""Robustezza della pipeline: casi emersi dalla revisione indipendente del Task 9."""

import json
from datetime import timedelta

import pytest
from test_pipeline import D1, D2, D3, MONZA, events, run, site, st, storage  # noqa: F401 (fixture)

from scraper.config import Settings
from scraper.pipeline import RunRefused
from scraper.sources.trovacasa import TROVACASA


async def test_rerun_after_crash_before_report_is_still_a_rerun(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("5")
    site.alive.add("5")
    await run(site, storage, D2)
    storage.delete(f"runs/dt={D2}/report.json")  # il run si era interrotto prima del report
    await run(site, storage, D2)
    s = st(storage)[("trovacasa", "5")]
    assert s.status == "active" and s.missing_streak == 1  # una sola assenza, non due
    assert events(storage, D2) == []


async def test_rerun_after_crash_keeps_new_events(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].append("99")
    await run(site, storage, D2)
    storage.delete(f"runs/dt={D2}/report.json")
    await run(site, storage, D2)
    assert events(storage, D2) == [("99", "new")]


async def test_refuses_past_date(site, storage):
    await run(site, storage, D1)
    await run(site, storage, D2)
    with pytest.raises(RunRefused):
        await run(site, storage, D1)
    await run(site, storage, D1, dry=True)  # in prova è consentito


async def test_detail_parse_error_does_not_lose_day(site, storage, monkeypatch):
    original = TROVACASA.parse_detail_page

    def flaky(html, listing_id):
        if listing_id == "7":
            raise ValueError("pagina strana con titolo segreto")
        return original(html, listing_id)

    monkeypatch.setattr(TROVACASA, "parse_detail_page", flaky)
    report = await run(site, storage, D1)
    assert len(st(storage)) == 30 and report["details"]["errors"] == 1
    assert st(storage)[("trovacasa", "7")].last_detail_date is None
    assert "segreto" not in json.dumps(report)


async def test_list_parse_error_counts_as_failed_page(site, storage, monkeypatch):
    await run(site, storage, D1)
    original = TROVACASA.parse_list_page

    def flaky(html, city, contract, page):
        if page == 2:
            raise ValueError("struttura inattesa")
        return original(html, city, contract, page)

    monkeypatch.setattr(TROVACASA, "parse_list_page", flaky)
    report = await run(site, storage, D2)
    assert report["segments"][0]["reason"] == "failed_pages"
    assert all(s.status == "active" for s in st(storage).values())


async def test_page1_failure_reported_as_failed_pages(site, storage):
    site.failing_pages.add(("milano", "vendita", 1))
    report = await run(site, storage, D1)
    assert report["segments"][0]["reason"] == "failed_pages" and report["exit_code"] == 1


async def test_real_drop_accepted_after_confirm_runs(site, storage):
    site.listings[("monza", "vendita")] = [str(i) for i in range(101, 111)]  # 10 annunci
    await run(site, storage, D1, cities=(MONZA,))
    for gone in ("101", "102", "103", "104"):
        site.listings[("monza", "vendita")].remove(gone)
    reasons = []
    for offset in (1, 2, 3):
        report = await run(site, storage, D1 + timedelta(days=offset), cities=(MONZA,))
        reasons.append(report["segments"][0]["reason"])
    assert reasons == ["suspicious_drop", "suspicious_drop", "drop_confirmed"]
    removed = sorted(i for i, t in events(storage, D1 + timedelta(days=3)) if t == "removed")
    assert removed == ["101", "102", "103", "104"]


async def test_drop_streak_not_inflated_by_same_day_rerun(site, storage):
    site.listings[("monza", "vendita")] = [str(i) for i in range(101, 111)]
    await run(site, storage, D1, cities=(MONZA,))
    for gone in ("101", "102", "103", "104"):
        site.listings[("monza", "vendita")].remove(gone)
    for _ in range(3):  # tre riesecuzioni dello stesso giorno contano come un solo run
        report = await run(site, storage, D2, cities=(MONZA,))
    assert report["segments"][0]["reason"] == "suspicious_drop"


async def test_changed_listing_without_detail_keeps_trigger(site, storage):
    await run(site, storage, D1)
    # un annuncio che il D3 non è nel suo giorno di rotazione: solo "changed" può fargli scaricare il dettaglio
    lid = next(str(i) for i in range(1, 31) if i % 7 != D3.toordinal() % 7)
    site.prices[lid] = "199.000 &#x20AC;"
    calls = iter([0.0])
    await run(site, storage, D2, clock=lambda: next(calls, 1e9))  # scadenza: nessun dettaglio
    site.requests.clear()
    await run(site, storage, D3)
    assert any("/annunci/" in u and u.endswith(f"-{lid}") for u in site.requests)


async def test_circuit_open_in_list_phase_no_disappearances(site, storage):
    site.listings[("milano", "vendita")] = [str(i) for i in range(1, 73)]  # 3 pages: page 3 is requested after page 2 fails
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("5")
    site.failing_pages.update(("milano", "vendita", p) for p in (2, 3))
    report = await run(site, storage, D2, settings=Settings(max_retries=1, error_window=1, list_concurrency=1, list_rate_per_s=0))
    assert report["exit_code"] == 1 and "circuit_open_lists" in report["alerts"]
    assert all(s.status == "active" for s in st(storage).values())
    # la pagina 1 era stata letta: le sue 24 osservazioni non vanno perse
    from scraper.storage import partition_key, read_parquet

    assert len(read_parquet(storage, partition_key("observations", D2))) == 24


async def test_partial_rerun_listing_moved_segment_not_lost(site, storage):
    from test_pipeline import MILANO

    await run(site, storage, D1, cities=(MILANO, MONZA))
    # oggi l'annuncio 101 compare negli elenchi di Milano invece che di Monza
    site.listings[("monza", "vendita")].remove("101")
    site.listings[("milano", "vendita")].append("101")
    await run(site, storage, D2, cities=(MILANO, MONZA))
    await run(site, storage, D2, cities=(MILANO, MONZA), only=["milano"])
    s = st(storage)[("trovacasa", "101")]
    assert s.status == "active" and s.first_seen == D1 and s.city == "milano"


async def test_circuit_open_keeps_pages_already_read_and_records_no_disappearances(site, storage):
    # Run of 2026-10-30: when the circuit opened, the pages of the segment already read
    # were thrown away and only page 1 was kept.
    site.listings[("milano", "vendita")] = [str(i) for i in range(1, 81)]  # 4 pages
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("75")  # on page 4, which will not be read
    site.failing_pages.add(("milano", "vendita", 3))
    report = await run(site, storage, D2, settings=Settings(max_retries=1, error_window=1, list_concurrency=1, list_rate_per_s=0))
    assert "circuit_open_lists" in report["alerts"]
    assert all(s.status == "active" for s in st(storage).values())
    from scraper.storage import partition_key, read_parquet

    assert len(read_parquet(storage, partition_key("observations", D2))) == 48  # pages 1 and 2


async def test_never_requests_a_page_past_the_last_one(site, storage):
    # 30 listings = 2 pages: page 3 does not exist and must never be requested (decision 0006).
    report = await run(site, storage, D1)
    assert report["exit_code"] == 0
    assert not [u for u in site.requests if "case-in-vendita/milano?page=3" in u]


async def test_follows_the_next_link_when_listings_shift(site, storage):
    # The site declares 30 listings (2 pages) but 50 are shown: page 2 links to page 3.
    site.listings[("milano", "vendita")] = [str(i) for i in range(1, 51)]
    site.declared_override[("milano", "vendita")] = 30
    await run(site, storage, D1)
    from scraper.storage import partition_key, read_parquet

    assert len(read_parquet(storage, partition_key("observations", D1))) == 50
    assert not [u for u in site.requests if "case-in-vendita/milano?page=4" in u]


async def test_list_and_detail_pages_have_separate_rates(site, storage):
    from scraper.pipeline import RunOptions, run_daily

    now = [0.0]
    starts: list[tuple[float, str]] = []

    async def sleep(seconds):
        now[0] += seconds

    def handler(request):
        starts.append((now[0], str(request.url)))
        return site.handler(request)

    import httpx

    settings = Settings(max_retries=1, list_rate_per_s=0.3, detail_rate_per_s=1.5, detail_concurrency=2)
    await run_daily(storage, [MONZA], settings, RunOptions(run_date=D1), transport=httpx.MockTransport(handler), clock=lambda: now[0], sleep=sleep)
    lists = [t for t, u in starts if "/case-in-" in u]
    details = [t for t, u in starts if "www.trovacasa.it/annunci/" in u]  # photos live on another host
    assert len(details) == 5
    assert all(b - a >= 1 / 0.3 - 1e-9 for a, b in zip(lists, lists[1:]))
    assert all(b - a >= 1 / 1.5 - 1e-9 for a, b in zip(details, details[1:]))
    assert any(b - a < 1 / 0.3 for a, b in zip(details, details[1:]))  # details are not paced like lists


async def test_failed_last_page_does_not_lead_past_the_end_nor_to_disappearances(site, storage):
    site.listings[("milano", "vendita")] = [str(i) for i in range(1, 73)]  # exactly 3 pages
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("70")
    site.failing_pages.add(("milano", "vendita", 3))
    site.requests.clear()
    report = await run(site, storage, D2)
    assert "segments_not_ok" in report["alerts"]
    assert not [u for u in site.requests if "case-in-vendita/milano?page=4" in u]
    assert all(s.status == "active" for s in st(storage).values())


async def test_failed_page_reached_through_next_link_records_no_disappearances(site, storage):
    site.listings[("milano", "vendita")] = [str(i) for i in range(1, 51)]
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("49")  # on page 3
    site.declared_override[("milano", "vendita")] = 30  # declared: 2 pages, page 3 only via "next"
    site.failing_pages.add(("milano", "vendita", 3))
    report = await run(site, storage, D2)
    assert "segments_not_ok" in report["alerts"]
    assert all(s.status == "active" for s in st(storage).values())
