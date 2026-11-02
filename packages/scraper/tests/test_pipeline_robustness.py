"""Pipeline robustness: cases found by the independent review of Task 9."""

import json
from datetime import timedelta

import pytest
from test_pipeline import D1, D2, D3, MILANO, MONZA, SET, events, run, site, st, storage  # noqa: F401 (fixture)

from scraper.config import Settings
from scraper.pipeline import RunRefused
from scraper.sources.trovacasa import TROVACASA


async def test_rerun_after_crash_before_report_is_still_a_rerun(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("5")
    site.alive.add("5")
    await run(site, storage, D2)
    storage.delete(f"runs/dt={D2}/report.json")  # the run had stopped before the report
    await run(site, storage, D2)
    s = st(storage)[("trovacasa", "5")]
    assert s.status == "active" and s.missing_streak == 1  # one absence, not two
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
    await run(site, storage, D1, dry=True)  # allowed in a dry run


async def test_detail_parse_error_does_not_lose_day(site, storage, monkeypatch):
    original = TROVACASA.parse_detail_page

    def flaky(html, listing_id):
        if listing_id == "7":
            raise ValueError("odd page with a secret title")
        return original(html, listing_id)

    monkeypatch.setattr(TROVACASA, "parse_detail_page", flaky)
    report = await run(site, storage, D1)
    assert len(st(storage)) == 30 and report["details"]["errors"] == 1
    assert st(storage)[("trovacasa", "7")].last_detail_date is None
    assert "secret" not in json.dumps(report)


async def test_list_parse_error_counts_as_failed_page(site, storage, monkeypatch):
    await run(site, storage, D1)
    original = TROVACASA.parse_list_page

    def flaky(html, city, contract, page):
        if page == 2:
            raise ValueError("unexpected structure")
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
    site.listings[("monza", "vendita")] = [str(i) for i in range(101, 111)]  # 10 listings
    await run(site, storage, D1, cities=(MONZA,))
    for gone in ("101", "102", "103", "104"):
        site.listings[("monza", "vendita")].remove(gone)
    reasons = []
    checks_all = Settings(max_retries=1, absence_checks_per_run=10)  # every absence confirmed the same day (production sample: 1)
    for offset in (1, 2, 3):
        report = await run(site, storage, D1 + timedelta(days=offset), cities=(MONZA,), settings=checks_all)
        reasons.append(report["segments"][0]["reason"])
    assert reasons == ["suspicious_drop", "suspicious_drop", "drop_confirmed"]
    removed = sorted(i for i, t in events(storage, D1 + timedelta(days=3)) if t == "removed")
    assert removed == ["101", "102", "103", "104"]


async def test_drop_streak_not_inflated_by_same_day_rerun(site, storage):
    site.listings[("monza", "vendita")] = [str(i) for i in range(101, 111)]
    await run(site, storage, D1, cities=(MONZA,))
    for gone in ("101", "102", "103", "104"):
        site.listings[("monza", "vendita")].remove(gone)
    for _ in range(3):  # three reruns on the same day count as a single run
        report = await run(site, storage, D2, cities=(MONZA,))
    assert report["segments"][0]["reason"] == "suspicious_drop"


async def test_changed_listing_without_detail_keeps_trigger(site, storage):
    await run(site, storage, D1)
    # a listing for which D3 is not its rotation day: only "changed" can get its detail page downloaded
    lid = next(str(i) for i in range(1, 31) if i % 7 != D3.toordinal() % 7)
    site.prices[lid] = "199.000 &#x20AC;"
    calls = iter([0.0])
    await run(site, storage, D2, clock=lambda: next(calls, 1e9))  # deadline: no detail pages
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
    # page 1 had been read: its 24 observations must not be lost
    from scraper.storage import partition_key, read_parquet

    assert len(read_parquet(storage, partition_key("observations", D2))) == 24


async def test_partial_rerun_listing_moved_segment_not_lost(site, storage):
    from test_pipeline import MILANO

    await run(site, storage, D1, cities=(MILANO, MONZA))
    # today listing 101 appears in the Milano search results instead of Monza's
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


def _hanging(site, hung_ids):
    """Fake-site handler whose detail pages for `hung_ids` never answer."""
    import asyncio

    async def handler(request):
        if "/annunci/" in request.url.path and request.url.path.rsplit("-", 1)[-1] in hung_ids:
            await asyncio.sleep(3600)
        return site.handler(request)

    return handler


async def test_a_hanging_detail_page_does_not_block_the_run(site, storage):
    import asyncio

    import httpx

    from scraper.pipeline import RunOptions, run_daily

    async def instant(_s):
        return None

    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("7")  # absence check on a page that never answers
    settings = Settings(max_retries=1, timeout_s=0.05)
    report = await asyncio.wait_for(
        run_daily(storage, [MILANO], settings, RunOptions(run_date=D2), transport=httpx.MockTransport(_hanging(site, {"7"})), sleep=instant),
        timeout=30,
    )
    assert report["details"]["errors"] >= 1
    assert st(storage)[("trovacasa", "7")].status == "active"  # an unanswered check is not a removal
    assert report["events"].get("removed", 0) == 0


async def test_heartbeat_runs_during_the_details_phase(site, storage, caplog, monkeypatch):
    import asyncio
    import logging

    import httpx

    import scraper.pipeline as pipeline
    from scraper.pipeline import RunOptions, run_daily

    caplog.set_level(logging.INFO, logger="scraper")
    monkeypatch.setattr(pipeline, "HEARTBEAT_S", 0.01)

    async def slow(request):
        if "/annunci/" in request.url.path:
            await asyncio.sleep(0.03)
        return site.handler(request)

    async def instant(_s):
        return None

    await run_daily(storage, [MILANO], Settings(max_retries=1), RunOptions(run_date=D1), transport=httpx.MockTransport(slow), sleep=instant)
    assert any("[details] in progress" in r.getMessage() for r in caplog.records)


async def test_stack_dump_is_armed_for_a_stuck_run_and_disarmed_at_the_end(site, storage, monkeypatch):
    import scraper.pipeline as pipeline

    calls = []
    monkeypatch.setattr(pipeline.faulthandler, "dump_traceback_later", lambda timeout, **kw: calls.append(("arm", timeout)))
    monkeypatch.setattr(pipeline.faulthandler, "cancel_dump_traceback_later", lambda: calls.append(("disarm", None)))
    await run(site, storage, D1)
    assert calls[0][0] == "arm" and calls[-1][0] == "disarm"
    # after the photo deadline (90%) but before GitHub's job limit
    assert 0.90 * SET.max_runtime_minutes * 60 < calls[0][1] < SET.max_runtime_minutes * 60 + 15 * 60


async def test_run_still_writes_when_every_detail_page_times_out(site, storage):
    # The search results are fine but every detail page hangs until the timeout: the run must
    # stop at its deadlines and write what it has, recording no disappearances.
    import httpx

    from scraper.pipeline import RunOptions, run_daily
    from scraper.storage import partition_key, read_parquet

    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("9")
    now = [0.0]

    async def sleep(s):
        import asyncio

        now[0] += s
        await asyncio.sleep(0)  # like asyncio.sleep, the backoff lets the other requests run

    def handler(request):
        if "www.trovacasa.it/annunci/" in str(request.url):
            now[0] += 30.0
            raise httpx.ReadTimeout("hang", request=request)
        return site.handler(request)

    settings = Settings(max_retries=4, max_runtime_minutes=10)
    report = await run_daily(storage, [MILANO], settings, RunOptions(run_date=D2), transport=httpx.MockTransport(handler),
                             clock=lambda: now[0], sleep=sleep)  # fmt: skip
    assert now[0] < settings.max_runtime_minutes * 60  # finished within the run's own budget
    assert read_parquet(storage, partition_key("observations", D2)) is not None  # the day was written
    assert report["events"].get("removed", 0) == 0
    assert st(storage)[("trovacasa", "9")].status == "active"


DETAIL_PREFIX = "https://www.trovacasa.it/annunci/"  # photo URLs contain "/annunci/" too, on another host


async def test_detail_404_stops_the_detail_phase_but_not_the_photos_and_removes_nothing(site, storage):
    # Decision 0007: one 404 from a GitHub runner leaves every following detail request hanging
    # for hours. The detail phase stops at the first 404, the photos (another host) and the
    # write still happen, and the listings whose detail was not read stay as they were.
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].append("31")  # new listing...
    site.dead.add("31")  # ...removed again before its detail page is requested
    site.listings[("milano", "vendita")].remove("5")  # an absent listing: its check must not run before the photos
    for i in ("1", "2"):
        site.prices[i] = "100.000 &#x20AC;"  # changed listings queued after the new one
    settings = Settings(max_retries=1, absence_checks_per_run=0)
    site.requests.clear()
    report = await run(site, storage, D2, settings=settings)
    assert "details_stopped_404" in report["alerts"] and report["exit_code"] == 0
    assert report["details"]["gone"] == 1 and report["details"]["skipped_deadline"] >= 1
    assert report["photos"]["planned"] > 0 and report["photos"]["done"] == report["photos"]["planned"]
    assert [t for _, t in events(storage, D2) if t in ("removed", "delisted")] == []
    assert st(storage)[("trovacasa", "5")].status == "active"
    assert not any(u.startswith(DETAIL_PREFIX) and u.rsplit("-", 1)[-1] == "5" for u in site.requests)


async def test_listing_absent_from_two_complete_collections_is_delisted_without_a_detail_check(site, storage):
    # Decision 0008: since the 404 check can no longer be made at scale (decision 0007), the
    # absence from two consecutive complete collections records the disappearance.
    site.listings[("milano", "vendita")] = [str(i) for i in range(1, 101)]
    no_checks = Settings(max_retries=1, absence_checks_per_run=0)
    await run(site, storage, D1, settings=no_checks)
    site.listings[("milano", "vendita")].remove("5")
    await run(site, storage, D2, settings=no_checks)
    s = st(storage)[("trovacasa", "5")]
    assert s.status == "active" and s.missing_streak == 1 and s.absent_since == D2
    assert [t for _, t in events(storage, D2) if t in ("removed", "delisted")] == []
    site.failing_pages.add(("milano", "vendita", 2))  # an incomplete collection in between changes nothing
    report = await run(site, storage, D3, settings=no_checks)
    assert report["segments"][0]["reason"] == "failed_pages"
    assert st(storage)[("trovacasa", "5")].missing_streak == 1 and events(storage, D3) == []
    site.failing_pages.clear()
    d4 = D3 + timedelta(days=1)
    await run(site, storage, d4, settings=no_checks)
    s = st(storage)[("trovacasa", "5")]
    assert [t for i, t in events(storage, d4) if i == "5"] == ["delisted"]
    assert s.status == "delisted" and s.delisted_date == D2 and s.list_last_seen == D1 and s.detail_gone_date is None


async def test_absence_checks_run_after_the_photos_and_only_a_sample(site, storage):
    site.listings[("milano", "vendita")] = [str(i) for i in range(1, 101)]  # 3 of 100 absent is not a suspicious drop
    await run(site, storage, D1)
    for gone in ("5", "6", "7"):
        site.listings[("milano", "vendita")].remove(gone)
    site.listings[("milano", "vendita")].append("101")  # a new listing, so that photos are requested today
    site.requests.clear()
    report = await run(site, storage, D2, settings=Settings(max_retries=1, absence_checks_per_run=1))
    check_requests = [u for u in site.requests if u.startswith(DETAIL_PREFIX) and u.rsplit("-", 1)[-1] in ("5", "6", "7")]
    assert len(check_requests) == 1
    last_photo = max(i for i, u in enumerate(site.requests) if "img.trovacasa.it" in u or "pic.trovacasa.it" in u)
    assert site.requests.index(check_requests[0]) > last_photo
    removed = [i for i, t in events(storage, D2) if t == "removed"]
    assert len(removed) == 1 and report["details"]["planned"]["absence_check"] == 3
    others = [st(storage)[("trovacasa", i)] for i in ("5", "6", "7") if i not in removed]
    assert all(s.status == "active" and s.missing_streak == 1 for s in others)  # counted, not decided (decision 0008)
