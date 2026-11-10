"""Daily run: search results → detail pages → state and events → photos → writing (spec §5, §7).

Flow and guarantees in docs/architecture.md. Key points:
- an incomplete segment produces no disappearances (quality.segment_ok + state.reconcile);
- work past the deadline is stopped, but the data collected is written anyway;
- rerunning the same day restarts from the state before that day's run for the
  segments collected, and keeps what was already written for the other segments;
  the copy of the starting state is the FIRST thing written: if it exists, the run is a rerun
  (even if the previous run stopped before the report);
- dates earlier than the last run are refused (they would roll the state back);
- an error on a single page does not lose the day.
"""

import asyncio
import faulthandler
import gzip
import json
import logging
import math
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from datetime import UTC, date, datetime

import httpx
import polars as pl

from scraper import frames
from scraper.config import City, Settings
from scraper.fingerprint import card_fingerprint, detail_hash, photo_ids_hash
from scraper.http import CircuitOpen, Fetcher, FetchResult, FetchStopped
from scraper.models import Card, CheckOutcome, Detail, Event, ListingKey, ListingState, SegmentKey
from scraper.photos import hash_image
from scraper.planner import DetailTask, plan_details, plan_photos, split_checks
from scraper.quality import active_drop_alert, segment_ok
from scraper.scope import classify
from scraper.sources.trovacasa import TROVACASA
from scraper.state import reconcile
from scraper.storage import Storage, partition_key, prune_partitions, read_parquet, scraper_version, write_parquet

log = logging.getLogger(__name__)

STATE_KEY = "state/listings.parquet"
SEGMENTS_KEY = "state/segments.parquet"
CENSOR_WINDOW_DAYS = 7  # "new" listings in a segment's first days: probably already online before
RAW_GONE_SAMPLES = 50  # 404/redirect pages kept (checks and incidental 404s) to learn how the site shows a removed listing
GONE_SAMPLES = 20  # incidental 404s (listings seen in today's search results) listed in the report, with their reason
DETAIL_SHARE = 0.75  # details stop here, leaving photos at least 15% of the runtime (they had ~5%, 2026-11-01)
PHOTO_SHARE = 0.90  # photos stop here; the rest is for writing
HEARTBEAT_S = 60.0  # heartbeat interval during the network phases
STACK_DUMP_GRACE_S = 600  # a run still alive this long after the photo deadline is stuck: dump the stacks
LIST_SHARE = 0.40  # share of the max runtime for search results: past it, unread pages count as failed
MAX_EXTRA_PAGES = 5  # pages followed through "next" links past the declared total (listings shifted during the run)
CHUNK = 500  # requests per chunk: an interruption (deadline, circuit) does not lose the chunks already done
_CHECK_REASONS = ("absence_check", "delisted_recheck")
_RAW_REASONS = ("new", "changed", "never_detailed")
_LISTING_ID_IN_URL = re.compile(r"-(\d+)/?$")
_DT = re.compile(r"/dt=(\d{4}-\d{2}-\d{2})/")


class RunRefused(Exception):
    """The run cannot start without risking corruption of the historical data (e.g. a date before the last run)."""


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
    circuit: bool = False
    skipped_cards: int = 0


# --- reading the state ----------------------------------------------------------


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
    df = df.drop("schema_version", "scraper_version", strict=False)
    return {(r["source"], r["city"], r["contract"]): r for r in df.to_dicts()}


def _history_key(run_date: date) -> str:
    return partition_key("state/history", run_date, "listings.parquet")


def _report_key(run_date: date) -> str:
    return f"runs/dt={run_date:%Y-%m-%d}/report.json"


def _latest_run_date(storage: Storage) -> date | None:
    found = [_DT.search("/" + k) for k in storage.list_keys("runs/") + storage.list_keys("state/history/")]
    return max((date.fromisoformat(m.group(1)) for m in found if m), default=None)


def _starting_state(current: dict, before_today: dict, scraped: set[SegmentKey]) -> dict[ListingKey, ListingState]:
    """Starting state of a rerun: for each listing, take the version from before today if
    today touches a segment collected in this rerun, otherwise the current one."""
    prev: dict[ListingKey, ListingState] = {}
    for key in set(current) | set(before_today):
        old, now = before_today.get(key), current.get(key)
        if old is not None:
            touched = old.segment in scraped or (now is not None and now.segment in scraped)
            prev[key] = old if touched or now is None else now
        elif now is not None and now.segment not in scraped:
            prev[key] = now  # appeared today in a segment this rerun does not touch
    return prev


# --- run phases --------------------------------------------------------------------


async def _for_each_chunk(
    fetcher: Fetcher,
    items: list,
    url_of: Callable[[Any], str],
    binary: bool,
    deadline: float | None,
    handle: Callable[[Any, FetchResult | None], None],
    progress: Callable[[int, int], None] | None = None,
) -> str | None:
    """Download in chunks of CHUNK requests and process each chunk RIGHT AWAY, before downloading
    the next: only one chunk of pages or images is in memory at a time (at bootstrap there are
    ~35,000 detail pages: keeping them all in memory would exceed the runner's 16 GB).
    `handle(item, result)` receives None for requests not made (deadline or circuit).
    Returns "circuit" if the circuit opened, "stopped" if the fetcher stopped after a stop
    status (e.g. the first 404 of the detail phase, decision 0007), None otherwise."""
    for i in range(0, len(items), CHUNK):
        chunk = items[i : i + CHUNK]
        try:
            results = await fetcher.get_many([url_of(x) for x in chunk], binary=binary, deadline=deadline)
        except CircuitOpen as exc:
            # the requests of the chunk completed before the circuit opened are kept
            for x, r in zip(chunk, exc.partial or [None] * len(chunk)):
                handle(x, r)
            for x in items[i + CHUNK :]:
                handle(x, None)
            return "stopped" if isinstance(exc, FetchStopped) else "circuit"
        for x, r in zip(chunk, results):
            handle(x, r)
        if progress is not None:
            progress(min(i + CHUNK, len(items)), len(items))
    return None


async def _heartbeat(fetcher: Fetcher, phase: str, minutes: Callable[[], float], every_s: float | None = None) -> None:
    """Periodic heartbeat during a long phase: if the run stalls, the log says where and how.
    Counts and latencies only, no listing data."""
    while True:
        await asyncio.sleep(every_s if every_s is not None else HEARTBEAT_S)
        s = fetcher.stats
        log.info(
            "[%s] in progress: %d requests, %d in flight, mean latency %.1f s, max %.1f s, status codes %s (%.1f min)",
            phase, s["requests"], s["in_flight"], s["latency_avg_s"], s["latency_max_s"], s["by_status"], minutes(),
        )  # fmt: skip


async def _scrape_segment(fetcher: Fetcher, seg: SegmentKey, settings: Settings, deadline: float | None = None) -> SegmentResult:
    _, slug, contract = seg
    try:
        first = await fetcher.get(TROVACASA.list_url(slug, contract, 1))
    except CircuitOpen:
        return SegmentResult(seg, [], None, 1, 1, circuit=True)
    if not first.ok:
        return SegmentResult(seg, [], None, 1, 1)
    try:
        page1 = TROVACASA.parse_list_page(first.text, slug, contract, 1)
    except Exception:
        log.warning("unreadable search-result page (%s/%s, page 1)", slug, contract)
        return SegmentResult(seg, [], None, 1, 1)
    declared = page1.declared_total
    skipped = page1.skipped_cards
    n_pages = max(1, math.ceil((declared or 0) / TROVACASA.page_size))
    # Never request a page past the last one: the old scraper followed the pager and never did,
    # and every stall of ours came right after such a request (decision 0006). Listings shifted
    # during the collection are reached through the last page's "next" link instead.
    last = n_pages if settings.max_pages <= 0 else min(n_pages, settings.max_pages)
    pages = list(range(2, last + 1))
    cards, failed = list(page1.cards), 0
    circuit = False
    has_next = page1.has_next  # "next" link of the last page read so far

    async def fetch(batch: list[int]) -> list:
        nonlocal circuit
        try:
            return await fetcher.get_many([TROVACASA.list_url(slug, contract, p) for p in batch], deadline=deadline)
        except CircuitOpen as exc:
            # the pages read before the circuit opened are kept; the segment stays incomplete
            circuit = True
            return exc.partial or [None] * len(batch)

    def handle(p: int, r) -> None:
        nonlocal failed, skipped, has_next
        has_next = False  # only a page actually read can lead further (never guess past the end)
        if r is None:
            failed += 1  # not read: search-result time ran out or the circuit opened
            return
        if r.ok:
            try:
                page = TROVACASA.parse_list_page(r.text, slug, contract, p)
            except Exception:
                log.warning("unreadable search-result page (%s/%s, page %s)", slug, contract, p)
                failed += 1
                return
            cards.extend(page.cards)
            skipped += page.skipped_cards
            has_next = page.has_next
        elif r.status == 404 and r.error is None and p >= n_pages:
            has_next = False  # end of the results (the last page can vanish if listings drop meanwhile)
        else:
            failed += 1  # a 404 mid-results too: 24 listings would be missing

    for p, r in zip(pages, await fetch(pages)):
        handle(p, r)
    requested = len(pages) + 1
    extra = 0
    while has_next and not circuit and settings.max_pages <= 0 and extra < MAX_EXTRA_PAGES:
        nxt = last + extra + 1
        has_next = False
        handle(nxt, (await fetch([nxt]))[0])
        extra += 1
        requested += 1
    if circuit:
        failed = max(failed, 1)  # a segment interrupted by the circuit is never complete (no disappearances)
    return SegmentResult(seg, cards, declared, requested, failed, circuit=circuit, skipped_cards=skipped)


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
    """On a rerun, keep the rows already written today for the segments not collected in this run."""
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
    sleep=asyncio.sleep,
) -> dict:
    """Runs the daily collection. If the process is still alive well after the photo deadline it
    is stuck somewhere: Python then prints every stack to the log (code locations only, no
    listing data), so the next diagnosis does not start blind (2026-11-02/03)."""
    faulthandler.dump_traceback_later(PHOTO_SHARE * settings.max_runtime_minutes * 60 + STACK_DUMP_GRACE_S, exit=False)
    try:
        return await _run_daily(storage, cities, settings, options, transport=transport, clock=clock, sleep=sleep)
    finally:
        faulthandler.cancel_dump_traceback_later()


async def _run_daily(
    storage: Storage,
    cities: list[City],
    settings: Settings,
    options: RunOptions,
    transport: httpx.AsyncBaseTransport | None = None,
    clock=time.monotonic,
    sleep=asyncio.sleep,
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

    latest = _latest_run_date(storage)
    if latest is not None and run_date < latest and not options.dry_run:
        raise RunRefused(f"the date {run_date} is before the last run ({latest}): only the last day can be rerun")

    current = load_state(storage)
    # The copy of the starting state is written first: if it exists, there has already been a run today.
    rerun = storage.read_bytes(_history_key(run_date)) is not None
    prev = _starting_state(current, _read_state(storage, _history_key(run_date)), scraped) if rerun else current
    seg_registry = load_segments(storage)

    def minutes() -> float:
        return (clock() - t0) / 60

    def progress_of(phase: str) -> Callable[[int, int], None]:
        return lambda done, total: log.info("[%s] %d/%d (%.1f min)", phase, done, total, minutes())

    log.info("[start] %d segments, %d listings in the state, rerun=%s", len(segments), len(current), rerun)

    # Search-result and detail pages get separate clients and paces: the site limits search
    # results far more than detail pages (decision 0006).
    site = Fetcher(settings.list_concurrency, settings, rate_per_s=settings.list_rate_per_s, transport=transport, clock=clock, sleep=sleep)
    # One 404 (a listing removed between the search results and its detail page) puts the runner
    # IP in penalty for hours: the detail phase stops there (decision 0007).
    detail_site = Fetcher(
        settings.detail_concurrency, settings, rate_per_s=settings.detail_rate_per_s, transport=transport, clock=clock, sleep=sleep,
        stop_on_status=(404, 410),
    )  # fmt: skip
    images = Fetcher(settings.image_concurrency, settings, rate_per_s=settings.image_rate_per_s, transport=transport, clock=clock, sleep=sleep)
    # The checks of absent listings run last, on their own client without the stop: a 404 is the
    # expected answer there, and the site keeps answering 404s instantly even once in penalty.
    check_site = Fetcher(settings.detail_concurrency, settings, rate_per_s=settings.detail_rate_per_s, transport=transport, clock=clock, sleep=sleep)
    circuit = False
    try:
        # 1. search results
        beat = asyncio.create_task(_heartbeat(site, "lists", minutes))
        try:
            list_deadline = t0 + LIST_SHARE * settings.max_runtime_minutes * 60
            seg_results = list(await asyncio.gather(*(_scrape_segment(site, s, settings, list_deadline) for s in segments)))
        finally:
            beat.cancel()
        if any(r.circuit for r in seg_results):
            circuit = True
            alerts.append("circuit_open_lists")

        cards: dict[ListingKey, Card] = {}
        for res in seg_results:
            for c in res.cards:
                cards.setdefault(c.key, c)  # same listing seen twice: the first one wins

        log.info("[lists] %d unique cards from %d segments (%.1f min)", len(cards), len(seg_results), minutes())

        # 2. segment completeness
        prev_active = Counter(s.segment for s in prev.values() if s.status == "active")
        seg_report, ok = [], {}
        by_seg = Counter(c.segment for c in cards.values())
        drop_runs: dict[SegmentKey, int] = {}
        for res in seg_results:
            entry = seg_registry.get(res.key) or {}
            # suspicious drops in previous runs (a rerun on the same day does not count twice)
            drop_runs[res.key] = (entry.get("drop_runs") or 0) - (1 if entry.get("drop_runs_date") == run_date else 0)
            good, reason = segment_ok(
                res.declared, by_seg[res.key], res.failed_pages, settings, prev_active[res.key], drop_runs[res.key]
            )
            if settings.max_pages > 0:
                good, reason = False, "max_pages"
            ok[res.key] = good
            seg_report.append(
                dict(source=res.key[0], city=res.key[1], contract=res.key[2], declared=res.declared, unique=by_seg[res.key],
                     pages=res.pages, failed_pages=res.failed_pages, skipped_cards=res.skipped_cards,
                     prev_active=prev_active[res.key], ok=good, reason=reason)
            )  # fmt: skip
        for s in segments:
            ok.setdefault(s, False)
        check_segments = {s for s in segments if ok[s]}
        censor = set()
        for s in segments:
            first = (seg_registry.get(s) or {}).get("first_complete_run")
            if first is None or (run_date - first).days < CENSOR_WINDOW_DAYS:
                censor.add(s)

        # 3. detail pages
        planned: list[DetailTask] = [] if circuit else plan_details(prev, cards, check_segments, settings, run_date)
        # The checks of absent listings answer 404: only a sample, after the photos (decision 0007).
        tasks, check_tasks = split_checks(planned, settings.absence_checks_per_run)
        detail_deadline = t0 + DETAIL_SHARE * settings.max_runtime_minutes * 60
        details: dict[ListingKey, Detail] = {}
        checks: dict[ListingKey, CheckOutcome] = {}
        raw_rows: list[dict] = []
        dstats: Counter[str] = Counter()
        error_samples: list[dict] = []
        gone_samples = 0
        # Which listings seen in today's search results answered 404, and why they were requested:
        # one such 404 stops the detail phase (decision 0007), so the report on R2 keeps the evidence.
        incidental_gone: list[dict] = []

        def keep_raw(raw: dict, r: FetchResult) -> None:
            # HTML compressed right away: ~15 KB per page in memory instead of ~170 KB
            html_gz = gzip.compress((r.text or "").encode("utf-8"))
            raw_rows.append(raw | dict(final_url=r.final_url, status=r.status, html_gz=html_gz))

        def handle_detail(t: DetailTask, r: FetchResult | None) -> None:
            nonlocal gone_samples
            is_check = t.reason in _CHECK_REASONS
            seg_of = cards[t.key].segment if t.key in cards else prev[t.key].segment
            raw = dict(source=t.key[0], listing_id=t.key[1], city=seg_of[1], contract=seg_of[2], reason=t.reason, url=t.url, run_date=run_date)
            if r is None:
                dstats["skipped_deadline"] += 1
                return
            if r.ok:
                m = _LISTING_ID_IN_URL.search(httpx.URL(r.final_url or t.url).path)
                redirected = m is None or m.group(1) != t.key[1]
                if not redirected:
                    try:
                        details[t.key] = TROVACASA.parse_detail_page(r.text, t.key[1])
                    except Exception as exc:
                        dstats["errors"] += 1
                        if is_check:
                            checks[t.key] = "error"
                        if len(error_samples) < 20:
                            error_samples.append(dict(url=t.url, status=r.status, error=f"parse:{type(exc).__name__}"))
                        return
                    dstats["done"] += 1
                else:
                    dstats["redirected"] += 1
                if is_check:
                    checks[t.key] = "alive"
                if t.reason in _RAW_REASONS and not redirected and dstats["raw_kept"] < settings.raw_max_per_run:
                    dstats["raw_kept"] += 1
                    keep_raw(raw, r)
                elif is_check and redirected and gone_samples < RAW_GONE_SAMPLES:
                    gone_samples += 1
                    keep_raw(raw, r)
            elif r.status in (404, 410) and r.error is None:
                dstats["gone"] += 1
                if is_check:
                    checks[t.key] = "gone"
                elif len(incidental_gone) < GONE_SAMPLES:
                    incidental_gone.append(dict(url=t.url, reason=t.reason, status=r.status))
                if gone_samples < RAW_GONE_SAMPLES:
                    gone_samples += 1
                    keep_raw(raw, r)
            else:
                dstats["errors"] += 1
                if is_check:
                    checks[t.key] = "error"
                if len(error_samples) < 20:
                    error_samples.append(dict(url=t.url, status=r.status, error=r.error))

        log.info("[details] planned %d (%.1f min)", len(tasks), minutes())
        beat = asyncio.create_task(_heartbeat(detail_site, "details", minutes))
        try:
            details_outcome = await _for_each_chunk(
                detail_site, tasks, lambda t: t.url, False, detail_deadline, handle_detail, progress_of("details")
            )
        finally:
            beat.cancel()
        if details_outcome == "circuit":
            circuit = True
            alerts.append("circuit_open_details")
        elif details_outcome == "stopped":
            alerts.append("details_stopped_404")  # the rest of the queue carries over to the next day
        attempted = len(tasks) - dstats["skipped_deadline"]
        if dstats["errors"] > max(20, 0.1 * attempted):
            alerts.append("details_errors")  # many pages not downloaded or not recognized: site changed or blocking us

        # 4. state and events
        def settle() -> tuple[dict[ListingKey, ListingState], list[Event]]:
            new_state, events = reconcile(prev, cards, details, checks, scraped, ok, censor, run_date)
            # A "changed" listing whose detail page did not arrive keeps its old fingerprint,
            # so tomorrow it still shows as changed and the detail page is requested again.
            for t in tasks:
                if t.reason == "changed" and t.key not in details and t.key in new_state:
                    new_state[t.key] = new_state[t.key].model_copy(update=dict(last_fingerprint=prev[t.key].last_fingerprint))
            return new_state, events

        new_state, events = settle()

        # 5. photos
        new_keys = {(e.source, e.listing_id) for e in events if e.type == "new"}
        ptasks = [] if circuit else plan_photos(new_state, cards, new_keys, settings)
        photo_deadline = t0 + PHOTO_SHARE * settings.max_runtime_minutes * 60
        photo_rows: list[dict] = []
        pstats: Counter[str] = Counter()
        hashed: Counter[ListingKey] = Counter()

        def handle_photo(p, r: FetchResult | None) -> None:
            if r is None:
                pstats["skipped_deadline"] += 1
                return
            hashes = hash_image(r.content) if r.ok and r.content else None
            if hashes is None:
                pstats["failed"] += 1
                return
            pstats["done"] += 1
            hashed[p.key] += 1
            c = cards[p.key]
            photo_rows.append(dict(source=p.key[0], listing_id=p.key[1], city=c.city, contract=c.contract, photo_index=p.index,
                                   photo_id=p.photo_id, phash=hashes[0], dhash=hashes[1], run_date=run_date))  # fmt: skip

        log.info("[photos] planned %d (%.1f min)", len(ptasks), minutes())
        beat = asyncio.create_task(_heartbeat(images, "photos", minutes))
        try:
            photos_circuit = await _for_each_chunk(
                images, ptasks, lambda p: TROVACASA.photo_url(p.photo_id), True, photo_deadline, handle_photo, progress_of("photos")
            )
        finally:
            beat.cancel()
        if photos_circuit == "circuit":
            alerts.append("circuit_open_photos")

        # 5b. checks of absent listings, after everything else: a missing listing answers 404 and
        # one 404 puts the runner IP in penalty for hours (decision 0007). Their outcome can only
        # add removals, so the state is settled again.
        if check_tasks:
            log.info("[checks] planned %d (%.1f min)", len(check_tasks), minutes())
            await _for_each_chunk(check_site, check_tasks, lambda t: t.url, False, photo_deadline, handle_detail)
            if checks:
                new_state, events = settle()
        for key, n in hashed.items():
            new_state[key] = new_state[key].model_copy(update=dict(photos_done=n, photo_ids_hash=photo_ids_hash(cards[key].photo_ids)))
    finally:
        await site.aclose()
        await detail_site.aclose()
        await check_site.aclose()
        await images.aclose()

    # 6. segment registry, alerts
    reasons = {(r["source"], r["city"], r["contract"]): r["reason"] for r in seg_report}
    for s in segments:
        blank = dict(source=s[0], city=s[1], contract=s[2], first_complete_run=None, last_complete_run=None)
        entry = blank | dict(seg_registry.get(s) or {})
        if ok[s]:
            entry["first_complete_run"] = entry["first_complete_run"] or run_date
            entry["last_complete_run"] = run_date
        if reasons.get(s) == "suspicious_drop":
            entry["drop_runs"], entry["drop_runs_date"] = drop_runs.get(s, 0) + 1, run_date
        else:
            entry["drop_runs"], entry["drop_runs_date"] = 0, None
        seg_registry[s] = entry
    if "drop_confirmed" in reasons.values():
        alerts.append("drop_confirmed")
    prev_n = sum(1 for s in prev.values() if s.status == "active" and s.segment in scraped)
    now_n = sum(1 for s in new_state.values() if s.status == "active" and s.segment in scraped)
    if active_drop_alert(prev_n, now_n, settings):
        alerts.append("active_drop")
    if not all(ok[s] for s in segments):
        alerts.append("segments_not_ok")
    if circuit:
        alerts.append("circuit_open")
    exit_code = 1 if ({"active_drop", "segments_not_ok", "details_errors"} & set(alerts) or circuit) else 0

    report = dict(
        run_date=str(run_date),
        started_at=started.isoformat(timespec="seconds"),
        duration_s=round(clock() - t0, 1),
        scraper_version=version,
        rerun=rerun,
        dry_run=options.dry_run,
        segments=seg_report,
        details=dict(planned=dict(Counter(t.reason for t in planned)), **dstats, checks=dict(Counter(checks.values()))),
        photos=dict(planned=len(ptasks), **pstats),
        events=dict(Counter(e.type for e in events)),
        active=dict(prev=prev_n, now=now_n),
        fetch=dict(lists=site.stats, details=detail_site.stats, images=images.stats),
        alerts=alerts,
        error_samples=error_samples,
        gone_samples=incidental_gone,
        exit_code=exit_code,
    )
    log.info("run %s: %s listings, events %s, warnings %s", run_date, len(cards), report["events"], alerts)

    if options.dry_run:
        return report

    log.info("[write] started (%.1f min)", minutes())
    # 7. writing: copy of the starting state (marks that a run happened today) → the day's
    #    partitions → new state → segment registry → report
    if not rerun:
        write_parquet(storage, _history_key(run_date), frames.frame([s.model_dump() for s in current.values()], frames.STATE), version)
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
    write_parquet(storage, STATE_KEY, frames.frame([s.model_dump() for s in new_state.values()], frames.STATE), version)
    write_parquet(storage, SEGMENTS_KEY, frames.frame(list(seg_registry.values()), frames.SEGMENTS), version)
    storage.write_bytes(_report_key(run_date), json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8"))
    prune_partitions(storage, "raw", settings.raw_retention_days, run_date)
    prune_partitions(storage, "state/history", settings.state_history_days, run_date)
    log.info("[write] done (%.1f min)", minutes())
    return report
