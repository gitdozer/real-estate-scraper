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
