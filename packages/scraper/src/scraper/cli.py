"""Command line: `python -m scraper run | status | import-legacy`. Guide in docs/runbook.md."""

import argparse
import asyncio
import json
import logging
import os
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scraper.config import load_cities, load_settings
from scraper.pipeline import RunOptions, RunRefused, run_daily
from scraper.report import summary_markdown
from scraper.storage import ConfigError, LocalStorage, R2Storage, Storage

ROME = ZoneInfo("Europe/Rome")


def _today() -> date:
    return datetime.now(ROME).date()


def _storage(args) -> Storage:
    return R2Storage.from_env() if args.storage == "r2" else LocalStorage(Path(args.local_root))


def _add_storage_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--storage", choices=["local", "r2"], default="local", help="where to read/write the data")
    p.add_argument("--local-root", default="data", help="data folder for --storage local")


def _cmd_run(args) -> int:
    config = Path(args.config_dir)
    cities = load_cities(config / "cities.yaml")
    settings = load_settings(
        config / "settings.yaml",
        {"full_details": args.full_details or None, "max_pages": args.max_pages, "max_runtime_minutes": args.max_runtime_minutes},
    )
    only = [c.strip() for c in args.cities.split(",") if c.strip()] if args.cities else None
    if only:
        known = {c.slugs.get("trovacasa") for c in cities}
        unknown = sorted(set(only) - known)
        if unknown:
            print(f"Unknown cities: {', '.join(unknown)}. Available: {', '.join(sorted(known))}", file=sys.stderr)
            return 2
    run_date = date.fromisoformat(args.date) if args.date else _today()
    report = asyncio.run(run_daily(_storage(args), cities, settings, RunOptions(run_date=run_date, cities=only, dry_run=args.dry_run)))
    summary = summary_markdown(report)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(summary)
    return report["exit_code"]


def _cmd_status(args) -> int:
    storage = _storage(args)
    reports = [k for k in storage.list_keys("runs/") if k.endswith("report.json")]
    if not reports:
        print("No runs found.")
        return 1
    last = json.loads(storage.read_bytes(reports[-1]))
    last_date = date.fromisoformat(last["run_date"])
    age = (_today() - last_date).days
    print(f"Last run: {last_date} ({age} days ago), outcome: {'OK' if last.get('exit_code') == 0 else 'needs checking'}")
    if age > args.max_age_days:
        print(f"WARNING: no collection for more than {args.max_age_days} days.")
        return 1
    return 0


def _cmd_import_legacy(args) -> int:
    from scraper.legacy import import_legacy

    n = import_legacy(Path(args.csv_path), _storage(args), force=args.force)
    print(f"Imported {n} listings from the historical data.")
    return 0


def _cmd_probe(args) -> int:
    from scraper.probe import harvest_detail_urls, interleave_missing_detail_urls, missing_detail_urls, probe_geojson, run_probe
    from scraper.sources.trovacasa import list_url

    settings = load_settings(Path(args.config_dir) / "settings.yaml", {})
    phases = [(float(r), float(m)) for r, m in (p.split(":") for p in args.phases.split(","))]
    if args.kind == "geojson":
        # Page 1 then the map for every configured segment; the pace is the rate of the
        # first phase (its minutes are ignored: 32 requests in all).
        cities = load_cities(Path(args.config_dir) / "cities.yaml")
        segments = [(c.slugs["trovacasa"], k) for c in cities for k in c.contracts]
        rows = asyncio.run(probe_geojson(segments, settings, interval_s=1.0 / phases[0][0]))
        return _print_summary(_geojson_summary(rows))
    if args.kind == "detail":
        # Detail URLs come from sale search-result pages read slowly (0.5 req/s, below their limit).
        pages = [list_url(args.city, "vendita", page) for page in range(1, args.harvest_pages + 1)]
        urls, _ = asyncio.run(harvest_detail_urls(pages, args.city, "vendita", rate=0.5, settings=settings))
        if args.dead_first > 0:
            # The daily run's detail phase starts with absence checks, answered 404: put the
            # same burst of requests for missing listings before the valid detail pages.
            urls = missing_detail_urls(urls, args.dead_first) + urls
        if args.dead_every > 0:
            urls = interleave_missing_detail_urls(urls, args.dead_every)
    else:
        # Distinct pages only (the probe never repeats a URL): ~2,000 pages, enough for 0.5 req/s for an hour.
        # --first-page reaches the end of the results quickly: pages past the last one answer 404.
        pages = range(args.first_page, args.first_page + 999)
        urls = [list_url(args.city, contract, page) for page in pages for contract in ("vendita", "affitto")]
    results = asyncio.run(run_probe(urls, phases, settings, concurrency=args.concurrency))
    summary = f"## Rate probe ({args.kind} pages, {args.concurrency} connection(s))\n\n"
    summary += "| req/s | minutes | requests | ok | timeouts | mean latency (s) |\n|---:|---:|---:|---:|---:|---:|\n"
    summary += "".join(
        f"| {p['rate']} | {p['minutes']:g} | {p['requests']} | {p['ok']} | {p['timeouts']} | {p['latency_avg_s']} |\n" for p in results
    )
    return _print_summary(summary)


def _print_summary(summary: str) -> int:
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(summary)
    return 0


def _geojson_summary(rows: list[dict]) -> str:
    """Counts per segment only (the repository is public): no ids, prices or coordinates."""
    summary = "## Map (GeoJSON) probe\n\n"
    summary += "| city | contract | outcome | status | cookies | KB | features | with id | with coordinates | declared | coverage | latency (s) | title |\n"
    summary += "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|\n"
    for r in rows:
        cov = "" if r["coverage"] is None else f"{r['coverage']:.1%}"
        declared = "" if r["declared"] is None else r["declared"]
        summary += (
            f"| {r['city']} | {r['contract']} | {r['outcome']} | {r['status'] or ''} | {r['cookies']} | {r['bytes'] // 1024} "
            f"| {r['features']} | {r['with_id']} | {r['with_coordinates']} | {declared} | {cov} | {r['latency_s']} | {r['title']} |\n"
        )
    keys = sorted({k for r in rows for k in r["property_keys"]})
    geometry = sorted({g for r in rows for g in r["geometry_types"]})
    summary += f"\nProperty keys: {', '.join(keys) or '-'}. Geometry types: {', '.join(geometry) or '-'}.\n"
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scraper", description="Daily collection of real-estate listings")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the day's collection")
    _add_storage_args(run)
    run.add_argument("--date", help="run date (YYYY-MM-DD), default today (Europe/Rome)")
    run.add_argument("--cities", help="comma-separated city slugs, default all")
    run.add_argument("--full-details", action="store_true", help="download the detail page of every listing")
    run.add_argument("--max-pages", type=int, help="limit the pages per segment (testing; blocks disappearances)")
    run.add_argument("--max-runtime-minutes", type=int, help="maximum run duration")
    run.add_argument("--dry-run", action="store_true", help="write nothing")
    run.add_argument("--config-dir", default="config", help="folder containing cities.yaml and settings.yaml")
    run.set_defaults(func=_cmd_run)

    status = sub.add_parser("status", help="check that the collection is up to date")
    _add_storage_args(status)
    status.add_argument("--max-age-days", type=int, default=2)
    status.set_defaults(func=_cmd_status)

    probe = sub.add_parser("probe", help="probe: how many requests the site accepts at different rates")
    probe.add_argument("--city", default="milano", help="slug of the city whose search-result pages to use")
    probe.add_argument("--phases", default="0.5:45", help="comma-separated 'requests_per_second:minutes' phases")
    probe.add_argument("--kind", choices=("list", "detail", "geojson"), default="list", help="pages to probe: search results, detail pages or the map (GeoJSON) of every segment")
    probe.add_argument("--concurrency", type=int, default=1, help="connections sharing the rate")
    probe.add_argument("--first-page", type=int, default=1, help="list kind: first search-result page to request")
    probe.add_argument("--harvest-pages", type=int, default=300, help="detail kind: search-result pages read to collect URLs (24 each)")
    probe.add_argument("--dead-first", type=int, default=0, help="detail kind: requests for non-existent listings (404) made before the valid detail pages")
    probe.add_argument("--dead-every", type=int, default=0, help="detail kind: one request for a non-existent listing (404) after every N valid detail pages")
    probe.add_argument("--config-dir", default="config")
    probe.set_defaults(func=_cmd_probe)

    legacy = sub.add_parser("import-legacy", help="import the old scraper's historical CSV (one-off)")
    _add_storage_args(legacy)
    legacy.add_argument("csv_path")
    legacy.add_argument("--force", action="store_true", help="import even if the state already exists")
    legacy.set_defaults(func=_cmd_import_legacy)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # The HTTP libraries log every URL (= listing data): GitHub logs are public.
    for name in ("httpx", "httpcore", "botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # Windows console (cp1252): avoids errors on the summary's non-ASCII characters.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RunRefused as exc:
        print(f"Run refused: {exc}", file=sys.stderr)  # the message contains only dates
        return 2
    except ConfigError as exc:
        print(f"Configuration: {exc}", file=sys.stderr)  # variable names only, no data
        return 1
    except Exception as exc:
        # The error text may contain listing data (URLs, titles): only its type goes to the
        # public log; the full details are saved to storage, which is private.
        saved = _save_crash(args, traceback.format_exc())
        print(f"Unexpected error: {type(exc).__name__}. Details: {saved or 'not saved'}", file=sys.stderr)
        return 1


def _save_crash(args, text: str) -> str | None:
    try:
        key = f"runs/crash/{datetime.now(ROME):%Y-%m-%dT%H%M%S}.txt"
        _storage(args).write_bytes(key, text.encode("utf-8"))
        return key
    except Exception:
        return None
