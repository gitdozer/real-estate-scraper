from scraper.config import Settings
from scraper.quality import active_drop_alert, segment_ok

S = Settings()


def test_segment_complete_enough():
    assert segment_ok(17430, 17000, 0, S) == (True, None)


def test_segment_incomplete():
    assert segment_ok(17430, 16800, 0, S) == (False, "incomplete")


def test_small_segment_absolute_threshold():
    assert segment_ok(4, 2, 0, S) == (True, None)
    assert segment_ok(4, 1, 0, S) == (False, "incomplete")


def test_more_cards_than_declared_is_ok():
    assert segment_ok(100, 103, 0, S) == (True, None)


def test_no_declared_total():
    assert segment_ok(None, 10, 0, S) == (False, "no_declared_total")


def test_failed_pages_block():
    assert segment_ok(100, 100, 1, S) == (False, "failed_pages")


def test_empty_segment_declared_zero_is_ok():
    assert segment_ok(0, 0, 0, S) == (True, None)


def test_active_drop_alert():
    assert active_drop_alert(1000, 940, S) is True
    assert active_drop_alert(1000, 960, S) is False
    assert active_drop_alert(0, 10, S) is False


def test_boundaries():
    assert segment_ok(49, 47, 0, S) == (True, None)
    assert segment_ok(50, 48, 0, S) == (False, "incomplete")
    assert segment_ok(100, 97, 0, S) == (True, None)
    assert active_drop_alert(1000, 950, S) is False


def test_suspicious_drop_vs_previous_active():
    # Il sito dichiara "0 case" (o un totale sballato) ma ieri c'erano 17.000 annunci attivi.
    assert segment_ok(0, 0, 0, S, prev_active=17000) == (False, "suspicious_drop")
    assert segment_ok(9000, 9000, 0, S, prev_active=17000) == (False, "suspicious_drop")


def test_normal_churn_is_not_suspicious():
    assert segment_ok(16900, 16800, 0, S, prev_active=17000) == (True, None)
    assert segment_ok(3, 3, 0, S, prev_active=4) == (True, None)
    assert segment_ok(0, 0, 0, S, prev_active=2) == (True, None)


def test_failed_page_one_is_failed_pages_not_parser_problem():
    assert segment_ok(None, 0, 1, S) == (False, "failed_pages")


def test_drop_confirmed_after_consecutive_runs():
    s = Settings(drop_confirm_runs=3)
    assert segment_ok(6, 6, 0, s, prev_active=10, drop_runs=0) == (False, "suspicious_drop")
    assert segment_ok(6, 6, 0, s, prev_active=10, drop_runs=1) == (False, "suspicious_drop")
    assert segment_ok(6, 6, 0, s, prev_active=10, drop_runs=2) == (True, "drop_confirmed")
    assert segment_ok(6, 5, 0, s, prev_active=10, drop_runs=2) == (True, "drop_confirmed")
    assert segment_ok(60, 40, 0, s, prev_active=100, drop_runs=2) == (False, "incomplete")
