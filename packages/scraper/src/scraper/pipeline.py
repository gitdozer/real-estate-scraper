"""Run giornaliero: elenchi → dettagli → stato ed eventi → foto → scrittura (spec §5, §7).

Flusso e garanzie in docs/architettura.md. Punti chiave:
- un segmento incompleto non genera scomparse (quality.segment_ok + state.reconcile);
- il lavoro oltre la scadenza si interrompe ma i dati raccolti si scrivono comunque;
- rieseguire lo stesso giorno riparte dallo stato di prima del run di quel giorno
  per i segmenti raccolti, e conserva quanto già scritto per gli altri segmenti.
"""

import asyncio
import json
import logging
import math
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx
import polars as pl

from scraper import frames
from scraper.config import City, Settings
from scraper.fingerprint import card_fingerprint, detail_hash, photo_ids_hash
from scraper.http import CircuitOpen, Fetcher, FetchResult
from scraper.models import Card, CheckOutcome, Detail, ListingKey, ListingState, SegmentKey
from scraper.photos import hash_image
from scraper.planner import DetailTask, plan_details, plan_photos
from scraper.quality import active_drop_alert, segment_ok
from scraper.scope import classify
from scraper.sources.trovacasa import TROVACASA
from scraper.state import reconcile
from scraper.storage import Storage, partition_key, prune_partitions, read_parquet, scraper_version, write_parquet

log = logging.getLogger(__name__)

STATE_KEY = "state/listings.parquet"
SEGMENTS_KEY = "state/segments.parquet"
CENSOR_WINDOW_DAYS = 7  # annunci "nuovi" nei primi giorni di un segmento: probabilmente già online prima
RAW_GONE_SAMPLES = 50  # pagine di controlli 404/redirect conservate per capire come il sito mostra un annuncio rimosso
CHUNK = 500  # richieste per blocco: un'interruzione (scadenza, circuito) non fa perdere i blocchi già fatti
_CHECK_REASONS = ("absence_check", "delisted_recheck")
_RAW_REASONS = ("new", "changed", "never_detailed")


@dataclass
class RunOptions:
    run_date: date
    cities: list[str] | None = None
    dry_run: bool = False


@dataclass
class SegmentResult:
    key: SegmentKey
    cards: list[Card]
    declared: int | None
    pages: int
    failed_pages: int


# --- lettura dello stato ---------------------------------------------------------


def _read_state(storage: Storage, key: str) -> dict[ListingKey, ListingState]:
    df = read_parquet(storage, key)
    if df is None:
        return {}
    rows = df.drop("schema_version", "scraper_version", strict=False).to_dicts()
    states = (ListingState(**r) for r in rows)
    return {s.key: s for s in states}


def load_state(storage: Storage) -> dict[ListingKey, ListingState]:
    return _read_state(storage, STATE_KEY)


def load_segments(storage: Storage) -> dict[SegmentKey, dict]:
    df = read_parquet(storage, SEGMENTS_KEY)
    if df is None:
        return {}
    return {(r["source"], r["city"], r["contract"]): r for r in df.to_dicts()}


def _history_key(run_date: date) -> str:
    return partition_key("state/history", run_date, "listings.parquet")


def _report_key(run_date: date) -> str:
    return f"runs/dt={run_date:%Y-%m-%d}/report.json"


# --- fasi del run ------------------------------------------------------------------


async def _chunked(fetcher: Fetcher, urls: list[str], binary: bool, deadline: float | None) -> tuple[list[FetchResult | None], bool]:
    """Scarica a blocchi. Restituisce (risultati, circuito_aperto); i non eseguiti sono None."""
    results: list[FetchResult | None] = []
    for i in range(0, len(urls), CHUNK):
        try:
            results.extend(await fetcher.get_many(urls[i : i + CHUNK], binary=binary, deadline=deadline))
        except CircuitOpen:
            results.extend([None] * (len(urls) - len(results)))
            return results, True
    return results, False


async def _scrape_segment(fetcher: Fetcher, seg: SegmentKey, settings: Settings) -> SegmentResult:
    _, slug, contract = seg
    first = await fetcher.get(TROVACASA.list_url(slug, contract, 1))
    if not first.ok:
        return SegmentResult(seg, [], None, 1, 1)
    page1 = TROVACASA.parse_list_page(first.text, slug, contract, 1)
    declared = page1.declared_total
    n_pages = max(1, math.ceil((declared or 0) / TROVACASA.page_size))
    last = n_pages + 1  # una pagina in più: gli annunci nuovi fanno slittare gli altri durante la raccolta
    if settings.max_pages > 0:
        last = min(last, settings.max_pages)
    pages = list(range(2, last + 1))
    results = await fetcher.get_many([TROVACASA.list_url(slug, contract, p) for p in pages])
    cards, failed = list(page1.cards), 0
    for p, r in zip(pages, results):
        if r.ok:
            cards.extend(TROVACASA.parse_list_page(r.text, slug, contract, p).cards)
        elif r.status == 404 and r.error is None:
            continue  # fine dell'elenco: la completezza la giudica segment_ok
        else:
            failed += 1
    return SegmentResult(seg, cards, declared, len(pages) + 1, failed)


def _observation_rows(cards: dict[ListingKey, Card], run_date: date) -> list[dict]:
    rows = []
    for c in cards.values():
        in_scope, reason, flags = classify(c)
        rows.append(
            c.model_dump()
            | dict(in_scope=in_scope, exclusion_reason=reason, flags=flags, fingerprint=card_fingerprint(c), run_date=run_date, source_run="daily")
        )
    return rows


def _detail_row(d: Detail, city: str, contract: str, run_date: date) -> dict:
    row = d.model_dump()
    row.update(attributes=json.dumps(d.attributes, ensure_ascii=False), detail_hash=detail_hash(d), city=city, contract=contract, run_date=run_date)
    return row


def _merge(storage: Storage, key: str, df: pl.DataFrame, rerun: bool, scraped: set[SegmentKey]) -> pl.DataFrame:
    """Su un rerun conserva le righe già scritte oggi per i segmenti non raccolti in questo run."""
    if not rerun:
        return df
    old = read_parquet(storage, key)
    if old is None:
        return df
    old = old.drop("schema_version", "scraper_version", strict=False)
    seg = pl.concat_str(["source", "city", "contract"], separator="|")
    scraped_keys = ["|".join(s) for s in scraped]
    keep = old.filter(~seg.is_in(scraped_keys))
    return pl.concat([keep, df], how="vertical_relaxed") if len(keep) else df


# --- run -----------------------------------------------------------------------------


async def run_daily(
    storage: Storage,
    cities: list[City],
    settings: Settings,
    options: RunOptions,
    transport: httpx.AsyncBaseTransport | None = None,
    clock=time.monotonic,
) -> dict:
    run_date = options.run_date
    t0 = clock()
    started = datetime.now(UTC)
    version = scraper_version()
    alerts: list[str] = []
    src = TROVACASA.name

    selected = [c for c in cities if options.cities is None or c.slugs.get(src) in options.cities]
    segments: list[SegmentKey] = [(src, c.slugs[src], contract) for c in selected if src in c.slugs for contract in c.contracts]
    scraped = set(segments)

    current = load_state(storage)
    rerun = storage.read_bytes(_report_key(run_date)) is not None
    if rerun:
        before_today = _read_state(storage, _history_key(run_date))
        prev = {k: v for k, v in current.items() if v.segment not in scraped}
        prev.update({k: v for k, v in before_today.items() if v.segment in scraped})
    else:
        prev = current
    seg_registry = load_segments(storage)

    site = Fetcher(settings.site_concurrency, settings, transport=transport, clock=clock)
    images = Fetcher(settings.image_concurrency, settings, transport=transport, clock=clock)
    circuit = False
    try:
        # 1. elenchi
        try:
            seg_results = await asyncio.gather(*(_scrape_segment(site, s, settings) for s in segments))
        except CircuitOpen:
            circuit, seg_results = True, []
            alerts.append("circuit_open_lists")

        cards: dict[ListingKey, Card] = {}
        for res in seg_results:
            for c in res.cards:
                cards.setdefault(c.key, c)  # stesso annuncio visto due volte: vale la prima

        # 2. completezza dei segmenti
        prev_active = Counter(s.segment for s in prev.values() if s.status == "active")
        seg_report, ok = [], {}
        by_seg = Counter(c.segment for c in cards.values())
        for res in seg_results:
            good, reason = segment_ok(res.declared, by_seg[res.key], res.failed_pages, settings, prev_active[res.key])
            if settings.max_pages > 0:
                good, reason = False, "max_pages"
            ok[res.key] = good
            seg_report.append(
                dict(source=res.key[0], city=res.key[1], contract=res.key[2], declared=res.declared, unique=by_seg[res.key],
                     pages=res.pages, failed_pages=res.failed_pages, prev_active=prev_active[res.key], ok=good, reason=reason)
            )  # fmt: skip
        for s in segments:
            ok.setdefault(s, False)
        check_segments = {s for s in segments if ok[s]}
        censor = set()
        for s in segments:
            first = (seg_registry.get(s) or {}).get("first_complete_run")
            if first is None or (run_date - first).days < CENSOR_WINDOW_DAYS:
                censor.add(s)

        # 3. dettagli
        tasks: list[DetailTask] = [] if circuit else plan_details(prev, cards, check_segments, settings, run_date)
        detail_deadline = t0 + 0.85 * settings.max_runtime_minutes * 60
        results, opened = await _chunked(site, [t.url for t in tasks], False, detail_deadline)
        if opened:
            circuit = True
            alerts.append("circuit_open_details")
        details: dict[ListingKey, Detail] = {}
        checks: dict[ListingKey, CheckOutcome] = {}
        raw_rows: list[dict] = []
        dstats: Counter[str] = Counter()
        error_samples: list[dict] = []
        gone_samples = 0
        for t, r in zip(tasks, results):
            is_check = t.reason in _CHECK_REASONS
            seg_of = cards[t.key].segment if t.key in cards else prev[t.key].segment
            raw = dict(source=t.key[0], listing_id=t.key[1], city=seg_of[1], contract=seg_of[2], reason=t.reason, url=t.url, run_date=run_date)
            if r is None:
                dstats["skipped_deadline"] += 1
                continue
            if r.ok:
                redirected = t.key[1] not in (r.final_url or "")
                if not redirected:
                    details[t.key] = TROVACASA.parse_detail_page(r.text, t.key[1])
                    dstats["done"] += 1
                else:
                    dstats["redirected"] += 1
                if is_check:
                    checks[t.key] = "alive"
                if (t.reason in _RAW_REASONS and not redirected) or (is_check and redirected and gone_samples < RAW_GONE_SAMPLES):
                    gone_samples += is_check
                    raw_rows.append(raw | dict(final_url=r.final_url, status=r.status, html=r.text))
            elif r.status in (404, 410) and r.error is None:
                dstats["gone"] += 1
                if is_check:
                    checks[t.key] = "gone"
                    if gone_samples < RAW_GONE_SAMPLES:
                        gone_samples += 1
                        raw_rows.append(raw | dict(final_url=r.final_url, status=r.status, html=r.text))
            else:
                dstats["errors"] += 1
                if is_check:
                    checks[t.key] = "error"
                if len(error_samples) < 20:
                    error_samples.append(dict(url=t.url, status=r.status, error=r.error))

        # 4. stato ed eventi
        new_state, events = reconcile(prev, cards, details, checks, scraped, ok, censor, run_date)

        # 5. foto
        new_keys = {(e.source, e.listing_id) for e in events if e.type == "new"}
        ptasks = [] if circuit else plan_photos(new_state, cards, new_keys, settings)
        photo_deadline = t0 + 0.90 * settings.max_runtime_minutes * 60
        presults, popened = await _chunked(images, [TROVACASA.photo_url(p.photo_id) for p in ptasks], True, photo_deadline)
        if popened:
            alerts.append("circuit_open_photos")
        photo_rows: list[dict] = []
        pstats: Counter[str] = Counter()
        hashed: Counter[ListingKey] = Counter()
        for p, r in zip(ptasks, presults):
            if r is None:
                pstats["skipped_deadline"] += 1
                continue
            hashes = hash_image(r.content) if r.ok and r.content else None
            if hashes is None:
                pstats["failed"] += 1
                continue
            pstats["done"] += 1
            hashed[p.key] += 1
            c = cards[p.key]
            photo_rows.append(dict(source=p.key[0], listing_id=p.key[1], city=c.city, contract=c.contract, photo_index=p.index,
                                   photo_id=p.photo_id, phash=hashes[0], dhash=hashes[1], run_date=run_date))  # fmt: skip
        for key, n in hashed.items():
            new_state[key] = new_state[key].model_copy(update=dict(photos_done=n, photo_ids_hash=photo_ids_hash(cards[key].photo_ids)))
    finally:
        await site.aclose()
        await images.aclose()

    # 6. registro dei segmenti, allarmi
    for s in segments:
        if ok[s]:
            entry = dict(seg_registry.get(s) or dict(source=s[0], city=s[1], contract=s[2], first_complete_run=None))
            entry["first_complete_run"] = entry["first_complete_run"] or run_date
            entry["last_complete_run"] = run_date
            seg_registry[s] = entry
    prev_n = sum(1 for s in prev.values() if s.status == "active" and s.segment in scraped)
    now_n = sum(1 for s in new_state.values() if s.status == "active" and s.segment in scraped)
    if active_drop_alert(prev_n, now_n, settings):
        alerts.append("active_drop")
    if not all(ok[s] for s in segments):
        alerts.append("segments_not_ok")
    if circuit:
        alerts.append("circuit_open")
    exit_code = 1 if ("active_drop" in alerts or "segments_not_ok" in alerts or circuit) else 0

    report = dict(
        run_date=str(run_date),
        started_at=started.isoformat(timespec="seconds"),
        duration_s=round(clock() - t0, 1),
        scraper_version=version,
        rerun=rerun,
        dry_run=options.dry_run,
        segments=seg_report,
        details=dict(planned=dict(Counter(t.reason for t in tasks)), **dstats, checks=dict(Counter(checks.values()))),
        photos=dict(planned=len(ptasks), **pstats),
        events=dict(Counter(e.type for e in events)),
        active=dict(prev=prev_n, now=now_n),
        fetch=dict(site=site.stats, images=images.stats),
        alerts=alerts,
        error_samples=error_samples,
        exit_code=exit_code,
    )
    log.info("run %s: %s annunci, eventi %s, avvisi %s", run_date, len(cards), report["events"], alerts)

    if options.dry_run:
        return report

    # 7. scrittura: partizioni del giorno → copia dello stato precedente → nuovo stato → report
    datasets = {
        "observations": frames.frame(_observation_rows(cards, run_date), frames.OBSERVATIONS),
        "details": frames.frame(
            [_detail_row(d, *(cards[k].segment[1:] if k in cards else new_state[k].segment[1:]), run_date) for k, d in details.items()],
            frames.DETAILS,
        ),
        "photos": frames.frame(photo_rows, frames.PHOTOS),
        "events": frames.frame([e.model_dump() for e in events], frames.EVENTS),
    }
    for name, df in datasets.items():
        key = partition_key(name, run_date)
        write_parquet(storage, key, _merge(storage, key, df, rerun, scraped), version)
    raw_key = partition_key("raw", run_date, "raw.parquet")
    write_parquet(storage, raw_key, _merge(storage, raw_key, frames.frame(raw_rows, frames.RAW), rerun, scraped), version)
    if not rerun and current:
        write_parquet(storage, _history_key(run_date), frames.frame([s.model_dump() for s in current.values()], frames.STATE), version)
    write_parquet(storage, STATE_KEY, frames.frame([s.model_dump() for s in new_state.values()], frames.STATE), version)
    write_parquet(storage, SEGMENTS_KEY, frames.frame(list(seg_registry.values()), frames.SEGMENTS), version)
    storage.write_bytes(_report_key(run_date), json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8"))
    prune_partitions(storage, "raw", settings.raw_retention_days, run_date)
    prune_partitions(storage, "state/history", settings.state_history_days, run_date)
    return report
