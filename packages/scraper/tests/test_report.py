from scraper.report import summary_markdown

REPORT = {
    "run_date": "2026-10-26",
    "duration_s": 1234.5,
    "scraper_version": "0.1.0+abc1234",
    "rerun": False,
    "dry_run": False,
    "segments": [
        {"source": "trovacasa", "city": "milano", "contract": "vendita", "declared": 17430, "unique": 17400,
         "pages": 728, "failed_pages": 0, "prev_active": 17380, "ok": True, "reason": None},
        {"source": "trovacasa", "city": "monza", "contract": "affitto", "declared": 342, "unique": 300,
         "pages": 16, "failed_pages": 1, "prev_active": 340, "ok": False, "reason": "failed_pages"},
    ],
    "details": {"planned": {"new": 120, "absence_check": 30}, "done": 140, "gone": 25, "checks": {"gone": 25, "alive": 5}},
    "photos": {"planned": 700, "done": 690, "failed": 10},
    "events": {"new": 120, "removed": 25, "price_change": 40},
    "active": {"prev": 17720, "now": 17815},
    "fetch": {"site": {"requests": 1200, "retries": 3, "failures": 1, "by_status": {"200": 1170}, "concurrency_now": 6}},
    "alerts": ["segments_not_ok"],
    "error_samples": [{"url": "https://www.trovacasa.it/annunci/mi-tc-1035-73623446", "status": 503, "error": "http_503"}],
    "exit_code": 1,
}  # fmt: skip


def test_summary_has_aggregates():
    md = summary_markdown(REPORT)
    assert "2026-10-26" in md and "17430" in md and "failed_pages" in md and "removed" in md
    assert "segments_not_ok" in md


def test_summary_contains_no_listing_data():
    md = summary_markdown(REPORT)
    assert "trovacasa.it/annunci" not in md and "73623446" not in md and "http" not in md
