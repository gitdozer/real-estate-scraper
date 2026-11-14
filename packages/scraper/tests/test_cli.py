import json
from datetime import date, timedelta

from scraper.cli import main
from scraper.storage import LocalStorage


def write_report(root, day):
    LocalStorage(root).write_bytes(f"runs/dt={day}/report.json", json.dumps({"run_date": str(day), "exit_code": 0}).encode())


def test_status_fresh(tmp_path, capsys):
    write_report(tmp_path, date.today())
    assert main(["status", "--storage", "local", "--local-root", str(tmp_path)]) == 0
    assert str(date.today()) in capsys.readouterr().out


def test_status_stale(tmp_path):
    write_report(tmp_path, date.today() - timedelta(days=3))
    assert main(["status", "--storage", "local", "--local-root", str(tmp_path), "--max-age-days", "2"]) == 1


def test_status_no_runs(tmp_path):
    assert main(["status", "--storage", "local", "--local-root", str(tmp_path)]) == 1


def test_run_dry_run_with_unknown_city_fails(tmp_path):
    assert main(["run", "--storage", "local", "--local-root", str(tmp_path), "--cities", "atlantide", "--dry-run"]) == 2


def test_http_libraries_do_not_log_urls(tmp_path):
    import logging

    write_report(tmp_path, date.today())
    main(["status", "--storage", "local", "--local-root", str(tmp_path)])
    for name in ("httpx", "httpcore", "botocore", "urllib3"):
        assert logging.getLogger(name).level >= logging.WARNING, name  # set explicitly, not inherited


def test_crash_prints_only_error_type(tmp_path, capsys, monkeypatch):
    import scraper.cli as cli

    async def boom(*a, **k):
        raise ValueError("titolo segreto https://www.trovacasa.it/annunci/mi-tc-1-123")

    monkeypatch.setattr(cli, "run_daily", boom)
    code = main(["run", "--storage", "local", "--local-root", str(tmp_path), "--cities", "marnate"])
    out = capsys.readouterr()
    assert code == 1 and "ValueError" in out.out + out.err
    assert "segreto" not in out.out + out.err and "trovacasa.it" not in out.out + out.err
    crash = [k for k in LocalStorage(tmp_path).list_keys("runs/") if "crash" in k]
    assert crash and b"segreto" in LocalStorage(tmp_path).read_bytes(crash[0])


def test_refused_run_exits_2(tmp_path, monkeypatch):
    import scraper.cli as cli
    from scraper.pipeline import RunRefused

    async def refuse(*a, **k):
        raise RunRefused("date before the last run")

    monkeypatch.setattr(cli, "run_daily", refuse)
    assert main(["run", "--storage", "local", "--local-root", str(tmp_path), "--cities", "marnate"]) == 2


def test_probe_detail_kind_harvests_urls_then_probes_them(monkeypatch, capsys):
    import scraper.probe as probe

    seen = {}

    async def fake_harvest(list_urls, city, contract, rate, settings, **kw):
        seen["harvest"] = (len(list_urls), city, contract, rate)
        return ["https://www.trovacasa.it/annunci/a", "https://www.trovacasa.it/annunci/b"], {}

    async def fake_probe(urls, phases, settings, concurrency=1, **kw):
        seen["probe"] = (urls, phases, concurrency)
        return [{"rate": 2.5, "minutes": 45, "requests": 2, "ok": 2, "timeouts": 0, "latency_avg_s": 0.5}]

    monkeypatch.setattr(probe, "harvest_detail_urls", fake_harvest)
    monkeypatch.setattr(probe, "run_probe", fake_probe)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = ["probe", "--kind", "detail", "--concurrency", "2", "--phases", "2.5:45", "--harvest-pages", "10"]
    assert main(args) == 0
    assert seen["harvest"] == (10, "milano", "vendita", 0.5)  # search-result pages read below their limit
    assert seen["probe"][1:] == ([(2.5, 45.0)], 2)
    assert "detail pages, 2 connection(s)" in capsys.readouterr().out


def test_probe_geojson_kind_probes_every_configured_segment_and_prints_counts_only(monkeypatch, capsys):
    import scraper.probe as probe

    seen = {}

    async def fake_geojson(segments, settings, interval_s=10.0, **kw):
        seen["segments"] = segments
        seen["interval_s"] = interval_s
        return [
            dict(city=c, contract=k, outcome="ok", status=200, bytes=12_000_000, content_type="application/json", latency_s=3.2,
                 features=16129, with_id=16129, with_coordinates=16129, declared=17470, coverage=0.923,
                 property_keys=["id", "prezzodescr"], geometry_types=["Point"], cookies=2, title="")
            for c, k in segments
        ]

    monkeypatch.setattr(probe, "probe_geojson", fake_geojson)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert main(["probe", "--kind", "geojson", "--phases", "0.1:5"]) == 0
    assert len(seen["segments"]) == 16 and ("milano", "vendita") in seen["segments"] and ("castellanza", "affitto") in seen["segments"]
    assert seen["interval_s"] == 10.0  # one request every 1/rate seconds of the first phase
    out = capsys.readouterr().out
    assert "## Map (GeoJSON) probe" in out and "| milano | vendita | ok | 200 | 2 |" in out and "92.3%" in out
    assert "id, prezzodescr" in out and "Point" in out


def test_probe_detail_kind_can_start_with_requests_for_missing_listings(monkeypatch):
    # Reproduces the daily run's detail phase, which starts with absence checks (404s):
    # `--dead-first N` puts N detail URLs with non-existent ids before the harvested ones.
    import scraper.probe as probe

    seen = {}

    async def fake_harvest(list_urls, city, contract, rate, settings, **kw):
        return ["https://www.trovacasa.it/annunci/mi-tc-1-10", "https://www.trovacasa.it/annunci/mi-tc-2-20"], {}

    async def fake_probe(urls, phases, settings, concurrency=1, **kw):
        seen["urls"] = urls
        return [{"rate": 1.5, "minutes": 1, "requests": 0, "ok": 0, "timeouts": 0, "latency_avg_s": 0}]

    monkeypatch.setattr(probe, "harvest_detail_urls", fake_harvest)
    monkeypatch.setattr(probe, "run_probe", fake_probe)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert main(["probe", "--kind", "detail", "--harvest-pages", "1", "--dead-first", "3", "--phases", "1.5:1"]) == 0
    assert seen["urls"][3:] == ["https://www.trovacasa.it/annunci/mi-tc-1-10", "https://www.trovacasa.it/annunci/mi-tc-2-20"]
    assert seen["urls"][:3] == probe.missing_detail_urls(seen["urls"][3:], 3)


def test_probe_detail_kind_can_spread_requests_for_missing_listings(monkeypatch):
    import scraper.probe as probe

    seen = {}
    valid = [f"https://www.trovacasa.it/annunci/mi-tc-1-{i}" for i in range(1, 5)]

    async def fake_harvest(list_urls, city, contract, rate, settings, **kw):
        return list(valid), {}

    async def fake_probe(urls, phases, settings, concurrency=1, **kw):
        seen["urls"] = urls
        return [{"rate": 1.5, "minutes": 1, "requests": 0, "ok": 0, "timeouts": 0, "latency_avg_s": 0}]

    monkeypatch.setattr(probe, "harvest_detail_urls", fake_harvest)
    monkeypatch.setattr(probe, "run_probe", fake_probe)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert main(["probe", "--kind", "detail", "--harvest-pages", "1", "--dead-every", "2", "--phases", "1.5:1"]) == 0
    assert seen["urls"] == probe.interleave_missing_detail_urls(valid, every=2)
    assert len(seen["urls"]) == 6


def test_probe_list_kind_can_start_from_a_given_page(monkeypatch):
    # Used to reach the end of the search results quickly (hypothesis: a request beyond the
    # last page, answered with 404, makes the site penalise the IP).
    import scraper.probe as probe

    seen = {}

    async def fake_probe(urls, phases, settings, concurrency=1, **kw):
        seen["urls"] = urls
        return [{"rate": 0.5, "minutes": 1, "requests": 0, "ok": 0, "timeouts": 0, "latency_avg_s": 0}]

    monkeypatch.setattr(probe, "run_probe", fake_probe)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert main(["probe", "--kind", "list", "--first-page", "600", "--phases", "0.5:1"]) == 0
    assert seen["urls"][:2] == [
        "https://www.trovacasa.it/case-in-vendita/milano?page=600",
        "https://www.trovacasa.it/case-in-affitto/milano?page=600",
    ]
