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
