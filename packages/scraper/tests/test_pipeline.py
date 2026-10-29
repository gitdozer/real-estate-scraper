import json
from datetime import date, timedelta

import httpx
import pytest
from fakesite import FakeSite

from scraper import __version__
from scraper.config import City, Settings
from scraper.pipeline import RunOptions, load_state, run_daily
from scraper.storage import LocalStorage, partition_key, read_parquet

D1 = date(2026, 10, 26)
D2 = D1 + timedelta(days=1)
D3 = D1 + timedelta(days=2)
MILANO = City(name="Milano", istat="015146", slugs={"trovacasa": "milano"}, contracts=["vendita"])
MONZA = City(name="Monza", istat="108033", slugs={"trovacasa": "monza"}, contracts=["vendita"])
SET = Settings(max_retries=1)


@pytest.fixture
def site():
    s = FakeSite()
    s.listings[("milano", "vendita")] = [str(i) for i in range(1, 31)]  # 2 pagine
    s.listings[("monza", "vendita")] = [str(i) for i in range(101, 106)]
    return s


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path)


async def run(site, storage, day, cities=(MILANO,), settings=SET, only=None, dry=False, clock=None):
    async def instant(_seconds):  # il ritmo limitato non deve rallentare i test
        return None

    kwargs = {"sleep": instant} if clock is None else {"clock": clock, "sleep": instant}
    return await run_daily(
        storage,
        list(cities),
        settings,
        RunOptions(run_date=day, cities=only, dry_run=dry),
        transport=httpx.MockTransport(site.handler),
        **kwargs,
    )


def events(storage, day):
    df = read_parquet(storage, partition_key("events", day))
    return [] if df is None else list(zip(df["listing_id"], df["type"]))


def st(storage):
    return load_state(storage)


async def test_pipeline_day1_bootstrap_all_new_and_censored(site, storage):
    report = await run(site, storage, D1)
    assert report["exit_code"] == 0
    state = st(storage)
    assert len(state) == 30 and all(s.status == "active" and s.first_seen_censored for s in state.values())
    assert sorted(t for _, t in events(storage, D1)) == ["new"] * 30
    assert len(read_parquet(storage, partition_key("details", D1))) == 30
    assert all(s.last_detail_date == D1 for s in state.values())
    photos = read_parquet(storage, partition_key("photos", D1))
    assert len(photos) == 60 and photos["phash"].str.len_chars().unique().to_list() == [16]
    assert all(s.photos_done == 2 for s in state.values())


async def test_pipeline_day2_removed_listing_404_becomes_removed(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("5")
    report = await run(site, storage, D2)
    assert report["exit_code"] == 0
    assert events(storage, D2) == [("5", "removed")]
    s = st(storage)[("trovacasa", "5")]
    assert s.status == "removed" and s.list_last_seen == D1 and s.detail_gone_date == D2


async def test_pipeline_listing_missing_from_list_but_alive_needs_two_days(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("5")
    site.alive.add("5")
    await run(site, storage, D2)
    assert events(storage, D2) == [] and st(storage)[("trovacasa", "5")].status == "active"
    await run(site, storage, D3)
    assert events(storage, D3) == [("5", "delisted")]
    assert st(storage)[("trovacasa", "5")].delisted_date == D2


async def test_pipeline_failed_page_blocks_disappearances(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("5")
    site.failing_pages.add(("milano", "vendita", 2))
    report = await run(site, storage, D2)
    assert report["exit_code"] == 1
    assert not any(t in ("removed", "delisted") for _, t in events(storage, D2))
    assert all(s.status == "active" for s in st(storage).values())
    seg = report["segments"][0]
    assert seg["ok"] is False and seg["reason"] == "failed_pages"


async def test_max_pages_marks_segment_incomplete(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("5")
    report = await run(site, storage, D2, settings=Settings(max_retries=1, max_pages=1))
    assert report["segments"][0]["reason"] == "max_pages" and report["exit_code"] == 1
    assert st(storage)[("trovacasa", "5")].status == "active"


async def test_collect_cards_dedupes_by_key(site, storage):
    site.extra_on_page[("milano", "vendita", 2)] = ["1"]  # lo stesso annuncio su due pagine
    await run(site, storage, D1)
    obs = read_parquet(storage, partition_key("observations", D1))
    assert len(obs) == 30 and obs["listing_id"].n_unique() == 30


async def test_pipeline_respects_deadline(site, storage):
    calls = iter([0.0])

    def clock():
        return next(calls, 1e9)  # dopo l'avvio il tempo è già scaduto

    report = await run(site, storage, D1, clock=clock)
    state = st(storage)
    # Tempo già scaduto: si legge solo la pagina 1 di ogni segmento (24 annunci), nessun dettaglio,
    # ma il run si chiude e scrive quanto raccolto; il segmento risulta incompleto.
    assert len(state) == 24 and all(s.last_detail_date is None for s in state.values())
    assert len(read_parquet(storage, partition_key("observations", D1))) == 24
    assert report["details"]["skipped_deadline"] == 24
    assert report["segments"][0]["reason"] == "failed_pages"


async def test_pipeline_rerun_same_day_is_idempotent(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("5")
    await run(site, storage, D2)
    first = sorted(events(storage, D2))
    await run(site, storage, D2)
    assert sorted(events(storage, D2)) == first == [("5", "removed")]
    assert st(storage)[("trovacasa", "1")].first_seen == D1


async def test_partial_rerun_keeps_other_segments(site, storage):
    await run(site, storage, D1, cities=(MILANO, MONZA))
    await run(site, storage, D1, cities=(MILANO, MONZA), only=["monza"])
    ev = events(storage, D1)
    assert len([1 for i, t in ev if t == "new"]) == 35
    assert st(storage)[("trovacasa", "1")].list_last_seen == D1
    assert len(read_parquet(storage, partition_key("observations", D1))) == 35


async def test_pipeline_dry_run_writes_nothing(site, storage):
    report = await run(site, storage, D1, dry=True)
    assert report["exit_code"] == 0 and storage.list_keys("") == []


async def test_pipeline_writes_versioned_partitions_and_report(site, storage):
    await run(site, storage, D1)
    for ds in ("observations", "details", "photos", "events"):
        df = read_parquet(storage, partition_key(ds, D1))
        assert df["schema_version"].unique().to_list() == [1], ds
        assert df["scraper_version"].str.starts_with(f"{__version__}+").all(), ds
    report = json.loads(storage.read_bytes(f"runs/dt={D1}/report.json"))
    assert report["run_date"] == str(D1) and report["segments"][0]["declared"] == 30
    assert storage.read_bytes("state/listings.parquet") and storage.read_bytes("state/segments.parquet")


async def test_new_listings_censored_only_in_first_week(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].append("99")
    await run(site, storage, D2)
    assert st(storage)[("trovacasa", "99")].first_seen_censored is True
    late = D1 + timedelta(days=8)
    site.listings[("milano", "vendita")].append("100")
    await run(site, storage, late)
    assert st(storage)[("trovacasa", "100")].first_seen_censored is False


async def test_new_listing_after_bootstrap_window_gets_full_photos(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].append("100")
    late = D1 + timedelta(days=8)
    await run(site, storage, late)
    photos = read_parquet(storage, partition_key("photos", late))
    assert sorted(photos.filter(photos["listing_id"] == "100")["photo_index"].to_list()) == [0, 1]


async def test_incomplete_segment_gets_no_absence_checks(site, storage):
    await run(site, storage, D1)
    site.listings[("milano", "vendita")].remove("5")
    site.failing_pages.add(("milano", "vendita", 2))
    site.requests.clear()
    await run(site, storage, D2)
    assert not any("/annunci/" in u and u.endswith("-5") for u in site.requests)
    assert not any("/annunci/" in u and u.endswith("-30") for u in site.requests)  # sulla pagina fallita


async def test_rerun_without_history_on_first_day_starts_from_empty(site, storage):
    await run(site, storage, D1)
    await run(site, storage, D1)
    assert sorted(t for _, t in events(storage, D1)) == ["new"] * 30
