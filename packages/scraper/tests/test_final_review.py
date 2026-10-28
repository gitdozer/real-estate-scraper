"""Casi emersi dalla revisione finale dell'intero branch (fase 1)."""

import re
from pathlib import Path

import httpx
import pytest
from conftest import fx
from fakesite import card_html, list_page_html
from test_pipeline import D1, D2, events, run, site, st, storage  # noqa: F401 (fixture)
from test_http import make, sequence

from scraper.config import Settings
from scraper.pipeline import _for_each_chunk
from scraper.report import summary_markdown
from scraper.sources.trovacasa import parse_detail_page, parse_list_page
from scraper.storage import partition_key, read_parquet

REPO = Path(__file__).resolve().parents[3]


# --- C1: action GitHub fissate a un commit ------------------------------------------


def test_workflow_actions_are_pinned_to_commit_sha():
    for wf in (REPO / ".github" / "workflows").glob("*.yml"):
        for ref in re.findall(r"uses:\s*([^\s#]+)", wf.read_text(encoding="utf-8")):
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"{wf.name}: {ref}"


def test_scrape_job_timeout_is_an_input_with_daily_default():
    import yaml

    wf = yaml.safe_load((REPO / ".github" / "workflows" / "scrape.yml").read_text(encoding="utf-8"))
    triggers = wf.get("on") or wf.get(True)  # PyYAML legge la chiave "on" come True
    assert triggers["workflow_dispatch"]["inputs"]["job_timeout_minutes"]["default"] == 120
    assert "inputs.job_timeout_minutes" in str(wf["jobs"]["scrape"]["timeout-minutes"])
    assert "120" in str(wf["jobs"]["scrape"]["timeout-minutes"])  # valore per il run pianificato


def test_workflows_use_locked_dependencies():
    for wf in (REPO / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        assert all("--locked" in line for line in text.splitlines() if "uv sync" in line), wf.name
        assert "contents: read" in text, wf.name


# --- C2: memoria limitata — i blocchi si elaborano uno alla volta -------------------


class RecordingFetcher:
    def __init__(self):
        self.log = []

    async def get_many(self, urls, binary=False, deadline=None):
        self.log.append(("fetch", len(urls)))
        return [httpx.Response(200) for _ in urls]


async def test_chunks_are_handled_before_next_fetch(monkeypatch):
    import scraper.pipeline as pipeline

    monkeypatch.setattr(pipeline, "CHUNK", 2)
    f = RecordingFetcher()
    opened = await _for_each_chunk(f, list(range(5)), str, False, None, lambda item, r: f.log.append(("handle", item)))
    assert opened is False
    assert f.log == [("fetch", 2), ("handle", 0), ("handle", 1), ("fetch", 2), ("handle", 2), ("handle", 3), ("fetch", 1), ("handle", 4)]


async def test_raw_rows_are_capped_and_compressed(site, storage):
    await run(site, storage, D1, settings=Settings(max_retries=1, raw_max_per_run=5))
    raw = read_parquet(storage, partition_key("raw", D1, "raw.parquet"))
    assert len(raw) == 5 and "html_gz" in raw.columns and "html" not in raw.columns
    import gzip

    assert b"immobile__title" in gzip.decompress(raw["html_gz"][0])


# --- I1: blocco (403) frena e apre il circuito; stati HTTP nel riepilogo ------------


async def test_403_counts_as_failure_and_opens_circuit():
    f, _ = make(sequence(httpx.Response(403)), concurrency=2, error_window=5, max_retries=1)
    from scraper.http import CircuitOpen

    with pytest.raises(CircuitOpen):
        await f.get_many([f"https://www.trovacasa.it/x?n={i}" for i in range(30)])


async def test_retry_after_is_capped():
    f, sleep = make(sequence(httpx.Response(429, headers={"Retry-After": "3600"}), httpx.Response(200)))
    await f.get("https://www.trovacasa.it/x")
    assert sleep.calls and sleep.calls[0] <= 30


def test_summary_shows_status_counts():
    report = {
        "run_date": "2026-10-26", "duration_s": 60, "scraper_version": "0.1.0+x", "segments": [],
        "details": {}, "photos": {}, "events": {}, "active": {"prev": 0, "now": 0},
        "fetch": {"site": {"requests": 10, "retries": 0, "failures": 3, "by_status": {"200": 7, "403": 3}, "concurrency_now": 1}},
        "alerts": [], "exit_code": 1,
    }  # fmt: skip
    md = summary_markdown(report)
    assert "403: 3" in md


# --- I2: pagina di dettaglio non riconosciuta = errore, non dettaglio vuoto ----------


def test_unrecognized_detail_page_raises():
    with pytest.raises(ValueError):
        parse_detail_page("<html><body><h1>Verifica di sicurezza</h1></body></html>", "123")


def test_detail_page_of_another_listing_raises():
    with pytest.raises(ValueError):
        parse_detail_page(fx("detail_73623446.html"), "99999999")


async def test_many_detail_errors_raise_alert(site, storage, monkeypatch):
    from scraper.sources.trovacasa import TROVACASA

    def broken(html, listing_id):
        raise ValueError("pagina non riconosciuta")

    monkeypatch.setattr(TROVACASA, "parse_detail_page", broken)
    report = await run(site, storage, D1)
    assert "details_errors" in report["alerts"] and report["exit_code"] == 1


# --- I3: segmenti con 0 o 1 annuncio ------------------------------------------------


def test_segment_with_one_listing_has_declared_total():
    p = parse_list_page(fx("list_zerbolo_affitto_one.html"), "zerbolo", "affitto", 1)
    assert len(p.cards) == 1 and p.declared_total == 1


def test_segment_with_no_listings_has_declared_zero():
    p = parse_list_page(fx("list_morimondo_affitto_none.html"), "morimondo", "affitto", 1)
    assert p.cards == [] and p.declared_total == 0


def test_singular_count_is_parsed():
    html = list_page_html([], None).replace("<body>", "<body><h1>1 casa in vendita a Marnate</h1>")
    assert parse_list_page(html, "marnate", "vendita", 1).declared_total == 1


# --- M1: 404 in mezzo all'elenco = pagina fallita -----------------------------------


async def test_404_in_the_middle_of_the_list_is_a_failed_page(site, storage):
    site.listings[("milano", "vendita")] = [str(i) for i in range(1, 80)]  # 4 pagine
    await run(site, storage, D1)
    site.missing_pages = {("milano", "vendita", 2)}
    report = await run(site, storage, D2)
    assert report["segments"][0]["reason"] == "failed_pages"
    assert all(s.status == "active" for s in st(storage).values())


# --- M2: scheda senza link o senza ID -----------------------------------------------


def test_card_without_link_is_skipped():
    broken = card_html("5").replace('href="/annunci/mi-tc-1035-5"', "").replace('data-id="5"', "")
    p = parse_list_page(list_page_html([card_html("4"), broken], 2), "milano", "vendita", 1)
    assert [c.listing_id for c in p.cards] == ["4"] and p.skipped_cards == 1


# --- M7: credenziali R2 mancanti: messaggio chiaro ----------------------------------


def test_missing_r2_variables_are_named_in_output(tmp_path, capsys, monkeypatch):
    from scraper.cli import main

    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    code = main(["status", "--storage", "r2"])
    out = capsys.readouterr()
    assert code == 1 and "R2_ACCOUNT_ID" in out.err
