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
        assert logging.getLogger(name).level >= logging.WARNING, name  # impostato esplicitamente, non ereditato


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
        raise RunRefused("data precedente all'ultimo run")

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
