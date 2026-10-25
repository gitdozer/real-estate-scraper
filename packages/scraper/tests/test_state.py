from datetime import date

from builders import SEG, by_key, card, detail, state

from scraper.fingerprint import detail_hash
from scraper.state import reconcile

D1 = date(2026, 10, 26)
D2 = date(2026, 10, 27)
K = ("trovacasa", "1")


def run(prev, cards=(), details=(), checks=None, scraped=(SEG,), ok=None, bootstrap=(), day=D1):
    ok = {s: True for s in scraped} if ok is None else ok
    return reconcile(
        prev=by_key(*prev) if not isinstance(prev, dict) else prev,
        cards=by_key(*cards),
        details=by_key(*details),
        checks=checks or {},
        scraped_segments=set(scraped),
        segment_ok=ok,
        bootstrap_segments=set(bootstrap),
        run_date=day,
    )


def types(events):
    return [(e.listing_id, e.type) for e in events]


def test_reconcile_new_listing_emits_new():
    new, events = run({}, cards=[card("1")])
    s = new[K]
    assert types(events) == [("1", "new")]
    assert s.status == "active" and s.first_seen == D1 and s.list_last_seen == D1
    assert s.first_seen_censored is False and s.last_price == 250000 and s.last_fingerprint


def test_reconcile_new_in_bootstrap_segment_is_censored():
    new, _ = run({}, cards=[card("1")], bootstrap=[SEG])
    assert new[K].first_seen_censored is True


def test_reconcile_new_out_of_scope_is_tracked_and_marked():
    new, events = run({}, cards=[card("1", title="Appartamento all'asta a Milano", is_auction=True)])
    assert new[K].in_scope is False and new[K].exclusion_reason == "auction"
    assert types(events) == [("1", "new")]


def test_reconcile_present_active_updates_last_seen():
    new, events = run([state("1")], cards=[card("1")])
    assert new[K].list_last_seen == D1 and new[K].first_seen == date(2026, 10, 1)
    assert events == []


def test_reconcile_price_change_emits_event():
    new, events = run([state("1", last_price=250000)], cards=[card("1", price=240000)])
    assert types(events) == [("1", "price_change")]
    assert (events[0].old_value, events[0].new_value) == ("250000", "240000")
    assert new[K].last_price == 240000


def test_reconcile_price_to_none_is_change():
    _, events = run([state("1", last_price=250000)], cards=[card("1", price=None)])
    assert types(events) == [("1", "price_change")]
    assert (events[0].old_value, events[0].new_value) == ("250000", None)


def test_reconcile_absent_gone_is_removed_with_dates():
    new, events = run([state("1")], checks={K: "gone"})
    s = new[K]
    assert types(events) == [("1", "removed")]
    assert s.status == "removed" and s.list_last_seen == date(2026, 10, 25)
    assert s.delisted_date == D1 and s.detail_gone_date == D1 and s.absent_since == D1
    assert s.last_check_date == D1


def test_reconcile_absent_alive_once_stays_active():
    new, events = run([state("1")], checks={K: "alive"})
    s = new[K]
    assert events == [] and s.status == "active" and s.missing_streak == 1
    assert s.absent_since == D1 and s.list_last_seen == date(2026, 10, 25) and s.last_check_date == D1


def test_reconcile_absent_alive_twice_is_delisted():
    day1, _ = run([state("1")], checks={K: "alive"}, day=D1)
    day2, events = run(day1, checks={K: "alive"}, day=D2)
    s = day2[K]
    assert types(events) == [("1", "delisted")]
    assert s.status == "delisted" and s.delisted_date == D1 and s.missing_streak == 2
    assert s.list_last_seen == date(2026, 10, 25) and s.detail_gone_date is None


def test_reconcile_absent_error_changes_nothing():
    prev = state("1")
    new, events = run([prev], checks={K: "error"})
    assert events == [] and new[K] == prev


def test_reconcile_absent_unchecked_changes_nothing():
    prev = state("1")
    new, events = run([prev])
    assert events == [] and new[K] == prev


def test_reconcile_segment_not_ok_changes_nothing():
    prev = state("1")
    new, events = run([prev], checks={K: "gone"}, ok={SEG: False})
    assert events == [] and new[K] == prev


def test_reconcile_ignores_unscraped_segments():
    other = state("2", city="monza")
    new, events = run([other], checks={("trovacasa", "2"): "gone"}, scraped=[SEG])
    assert events == [] and new[("trovacasa", "2")] == other


def test_reconcile_delisted_then_gone_emits_detail_gone():
    prev = state("1", status="delisted", absent_since=D1, delisted_date=D1, missing_streak=2)
    new, events = run([prev], checks={K: "gone"}, day=date(2026, 11, 3))
    s = new[K]
    assert types(events) == [("1", "detail_gone")]
    assert s.status == "removed" and s.detail_gone_date == date(2026, 11, 3) and s.delisted_date == D1


def test_reconcile_delisted_still_alive_records_check():
    prev = state("1", status="delisted", absent_since=D1, delisted_date=D1, missing_streak=2)
    new, events = run([prev], checks={K: "alive"}, day=date(2026, 11, 3))
    assert events == [] and new[K].status == "delisted" and new[K].last_check_date == date(2026, 11, 3)


def test_reconcile_removed_reappears():
    prev = state("1", status="removed", absent_since=D1, delisted_date=D1, detail_gone_date=D1, missing_streak=0)
    new, events = run([prev], cards=[card("1")], day=D2)
    s = new[K]
    assert types(events) == [("1", "reappeared")]
    assert s.status == "active" and s.list_last_seen == D2 and s.first_seen == date(2026, 10, 1)
    assert s.delisted_date is None and s.detail_gone_date is None and s.absent_since is None


def test_reconcile_present_resets_absence():
    day1, _ = run([state("1")], checks={K: "alive"}, day=D1)
    day2, events = run(day1, cards=[card("1")], day=D2)
    assert events == [] and day2[K].missing_streak == 0 and day2[K].absent_since is None
    assert day2[K].list_last_seen == D2


def test_reconcile_detail_change_emits_event():
    old = detail("1", description="vecchia")
    prev = state("1", last_detail_hash=detail_hash(old), last_detail_date=date(2026, 10, 20))
    new, events = run([prev], cards=[card("1")], details=[detail("1", description="nuova")])
    assert types(events) == [("1", "detail_changed")]
    assert new[K].last_detail_date == D1 and new[K].last_detail_hash == detail_hash(detail("1", description="nuova"))


def test_reconcile_first_detail_is_not_a_change():
    new, events = run([state("1", last_detail_hash=None, last_detail_date=None)], cards=[card("1")], details=[detail("1")])
    assert events == [] and new[K].last_detail_date == D1


def test_reconcile_eliminato_flag_does_not_change_status():
    new, events = run([state("1")], cards=[card("1", eliminato=True)])
    assert events == [] and new[K].status == "active"


def test_reconcile_keeps_listings_not_mentioned():
    a, b = state("1"), state("2", status="removed")
    new, _ = run([a, b], cards=[card("1")])
    assert set(new) == {K, ("trovacasa", "2")} and new[("trovacasa", "2")] == b
