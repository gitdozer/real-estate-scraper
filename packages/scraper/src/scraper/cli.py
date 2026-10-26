"""Riga di comando: `python -m scraper run | status | import-legacy`. Guida in docs/runbook.md."""

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
from scraper.storage import LocalStorage, R2Storage, Storage

ROME = ZoneInfo("Europe/Rome")


def _today() -> date:
    return datetime.now(ROME).date()


def _storage(args) -> Storage:
    return R2Storage.from_env() if args.storage == "r2" else LocalStorage(Path(args.local_root))


def _add_storage_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--storage", choices=["local", "r2"], default="local", help="dove leggere/scrivere i dati")
    p.add_argument("--local-root", default="data", help="cartella dati per --storage local")


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
            print(f"Comuni sconosciuti: {', '.join(unknown)}. Disponibili: {', '.join(sorted(known))}", file=sys.stderr)
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
        print("Nessun run trovato.")
        return 1
    last = json.loads(storage.read_bytes(reports[-1]))
    last_date = date.fromisoformat(last["run_date"])
    age = (_today() - last_date).days
    print(f"Ultimo run: {last_date} ({age} giorni fa), esito: {'OK' if last.get('exit_code') == 0 else 'da controllare'}")
    if age > args.max_age_days:
        print(f"ATTENZIONE: nessuna raccolta da più di {args.max_age_days} giorni.")
        return 1
    return 0


def _cmd_import_legacy(args) -> int:
    from scraper.legacy import import_legacy

    n = import_legacy(Path(args.csv_path), _storage(args), force=args.force)
    print(f"Importati {n} annunci dallo storico.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scraper", description="Raccolta giornaliera degli annunci immobiliari")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="esegue la raccolta del giorno")
    _add_storage_args(run)
    run.add_argument("--date", help="data del run (YYYY-MM-DD), default oggi (Europe/Rome)")
    run.add_argument("--cities", help="slug dei comuni separati da virgola, default tutti")
    run.add_argument("--full-details", action="store_true", help="scarica il dettaglio di tutti gli annunci")
    run.add_argument("--max-pages", type=int, help="limita le pagine per segmento (test; blocca le scomparse)")
    run.add_argument("--max-runtime-minutes", type=int, help="durata massima del run")
    run.add_argument("--dry-run", action="store_true", help="non scrive nulla")
    run.add_argument("--config-dir", default="config", help="cartella con cities.yaml e settings.yaml")
    run.set_defaults(func=_cmd_run)

    status = sub.add_parser("status", help="controlla che la raccolta sia aggiornata")
    _add_storage_args(status)
    status.add_argument("--max-age-days", type=int, default=2)
    status.set_defaults(func=_cmd_status)

    legacy = sub.add_parser("import-legacy", help="importa lo storico CSV del vecchio scraper (una tantum)")
    _add_storage_args(legacy)
    legacy.add_argument("csv_path")
    legacy.add_argument("--force", action="store_true", help="importa anche se lo stato esiste già")
    legacy.set_defaults(func=_cmd_import_legacy)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Le librerie HTTP loggano ogni URL (= dati degli annunci): i log di GitHub sono pubblici.
    for name in ("httpx", "httpcore", "botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # Console Windows (cp1252): evita errori sui caratteri non ASCII del riepilogo.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RunRefused as exc:
        print(f"Run rifiutato: {exc}", file=sys.stderr)  # il messaggio contiene solo date
        return 2
    except Exception as exc:
        # Il testo dell'errore può contenere dati degli annunci (URL, titoli): nel log pubblico
        # va solo il tipo; il dettaglio completo si salva nello storage, che è privato.
        saved = _save_crash(args, traceback.format_exc())
        print(f"Errore imprevisto: {type(exc).__name__}. Dettagli: {saved or 'non salvati'}", file=sys.stderr)
        return 1


def _save_crash(args, text: str) -> str | None:
    try:
        key = f"runs/crash/{datetime.now(ROME):%Y-%m-%dT%H%M%S}.txt"
        _storage(args).write_bytes(key, text.encode("utf-8"))
        return key
    except Exception:
        return None
