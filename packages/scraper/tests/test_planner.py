from collections import Counter
from datetime import date, timedelta

from builders import SEG, by_key, card, state

from scraper.config import Settings
from scraper.fingerprint import card_fingerprint, photo_ids_hash
from scraper.planner import plan_details, plan_photos

DAY = date(2026, 10, 26)
S = Settings()


def reasons(tasks):
    return {t.key[1]: t.reason for t in tasks}


def plan(prev=(), cards=(), scraped=(SEG,), settings=S, day=DAY):
    return plan_details(by_key(*prev), by_key(*cards), set(scraped), settings, day)


def fresh(listing_id, **kw):
    """Stato attivo coerente con card(listing_id): impronta uguale, dettaglio di ieri."""
    c = card(listing_id)
    base = dict(last_fingerprint=card_fingerprint(c), last_detail_date=DAY - timedelta(days=1))
    base.update(kw)
    return state(listing_id, **base)


def test_new_listing():
    assert reasons(plan(cards=[card("1")])) == {"1": "new"}


def test_reappeared_listing_counts_as_new():
    assert reasons(plan([fresh("1", status="removed")], [card("1")])) == {"1": "new"}


def test_changed_fingerprint():
    assert reasons(plan([fresh("1")], [card("1", price=1)])) == {"1": "changed"}


def test_never_detailed():
    assert reasons(plan([fresh("1", last_detail_date=None)], [card("1")])) == {"1": "never_detailed"}


def _id_not_due(day):
    return next(str(i) for i in range(1, 100) if i % S.rotation_days != day.toordinal() % S.rotation_days)


def test_unchanged_recent_listing_is_skipped():
    lid = _id_not_due(DAY)
    assert plan([fresh(lid)], [card(lid)]) == []


def test_no_rotation_when_detailed_today():
    states = [fresh(str(i), last_detail_date=DAY) for i in range(1, 15)]
    assert plan(states, [card(str(i)) for i in range(1, 15)]) == []


def test_rotation_when_too_old():
    old = fresh("1", last_detail_date=DAY - timedelta(days=2 * S.rotation_days))
    assert reasons(plan([old], [card("1")])) == {"1": "rotation"}


def test_full_details():
    s = Settings(full_details=True)
    tasks = plan([fresh(str(i)) for i in range(20)], [card(str(i)) for i in range(20)], settings=s)
    assert set(reasons(tasks).values()) <= {"full", "rotation"} and len(tasks) == 20


def test_absence_check_for_active_missing_listing():
    tasks = plan([fresh("1")], [])
    assert reasons(tasks) == {"1": "absence_check"} and tasks[0].url.endswith("-1")


def test_absence_check_also_for_out_of_scope():
    assert reasons(plan([fresh("1", in_scope=False, exclusion_reason="auction")], [])) == {"1": "absence_check"}


def test_no_absence_check_outside_scraped_segments():
    assert plan([fresh("1", city="monza")], [], scraped=[SEG]) == []


def test_removed_listing_not_checked():
    assert plan([fresh("1", status="removed")], []) == []


def test_delisted_recheck_weekly():
    recent = fresh("1", status="delisted", last_check_date=DAY - timedelta(days=3))
    due = fresh("2", status="delisted", last_check_date=DAY - timedelta(days=7))
    assert reasons(plan([recent, due], [])) == {"2": "delisted_recheck"}


def test_out_of_scope_cards_get_no_detail():
    assert plan(cards=[card("1", title="Appartamento all'asta a Milano", is_auction=True)]) == []


def test_plan_details_one_task_per_listing_highest_priority():
    s = Settings(full_details=True)
    tasks = plan([fresh("1", last_detail_date=None)], [card("1", price=1), card("2")], settings=s)
    assert reasons(tasks) == {"1": "changed", "2": "new"}
    order = ["absence_check", "new", "changed", "never_detailed", "delisted_recheck", "rotation", "full"]
    assert [t.reason for t in tasks] == sorted((t.reason for t in tasks), key=order.index)


def test_rotation_spreads_over_days():
    states = [fresh(str(i), last_detail_date=DAY) for i in range(1000)]
    cards = [card(str(i)) for i in range(1000)]
    for offset in range(1, S.rotation_days + 1):
        n = len(plan(states, cards, day=DAY + timedelta(days=offset)))
        assert 100 <= n <= 200, (offset, n)


def test_rotation_handles_non_numeric_ids():
    tasks = plan([fresh("abc", last_detail_date=DAY - timedelta(days=30))], [card("abc")])
    assert reasons(tasks) == {"abc": "rotation"}


# --- foto ---------------------------------------------------------------------

PH = Settings(photos_new=6, photos_backlog=3, max_photos_per_run=30000)


def photos(listing_id, n):
    return [f"A_1_{listing_id}_{i}" for i in range(n)]


def test_plan_photos_new_full_k():
    st = by_key(state("1", first_seen=DAY))
    tasks = plan_photos(st, by_key(card("1", photo_ids=photos("1", 10))), {("trovacasa", "1")}, PH)
    assert [t.index for t in tasks] == list(range(6)) and tasks[0].photo_id == "A_1_1_0"


def test_plan_photos_censored_new_goes_to_backlog_k3():
    st = by_key(state("1", first_seen=DAY, first_seen_censored=True))
    tasks = plan_photos(st, by_key(card("1", photo_ids=photos("1", 10))), {("trovacasa", "1")}, PH)
    assert len(tasks) == 3


def test_plan_photos_backlog_oldest_first_and_cap():
    st = by_key(
        state("1", first_seen=date(2026, 10, 20), first_seen_censored=True),
        state("2", first_seen=date(2026, 10, 10), first_seen_censored=True),
        state("3", first_seen=date(2026, 10, 15), photos_done=3, photo_ids_hash=photo_ids_hash(photos("3", 5))),
    )
    cards = by_key(*(card(i, photo_ids=photos(i, 5)) for i in ("1", "2", "3")))
    tasks = plan_photos(st, cards, set(), Settings(photos_backlog=3, max_photos_per_run=4))
    assert [t.key[1] for t in tasks] == ["2", "2", "2"]  # solo annunci interi entro il tetto


def test_plan_photos_redone_when_photo_list_changes():
    st = by_key(state("1", photos_done=3, photo_ids_hash=photo_ids_hash(["vecchia"])))
    tasks = plan_photos(st, by_key(card("1", photo_ids=photos("1", 8))), set(), PH)
    assert len(tasks) == 6


def test_plan_photos_skips_out_of_scope_and_no_photos():
    st = by_key(state("1", in_scope=False), state("2"))
    cards = by_key(card("1", photo_ids=photos("1", 5)), card("2", photo_ids=[]))
    assert plan_photos(st, cards, set(), PH) == []


def test_delisted_recheck_when_never_checked():
    assert reasons(plan([fresh("1", status="delisted", last_check_date=None)], [])) == {"1": "delisted_recheck"}


def test_rotation_oldest_first_within_reason():
    lid_a, lid_b = "1", "2"
    a = fresh(lid_a, last_detail_date=DAY - timedelta(days=15))
    b = fresh(lid_b, last_detail_date=DAY - timedelta(days=30))
    assert [t.key[1] for t in plan([a, b], [card(lid_a), card(lid_b)])] == ["2", "1"]


def test_plan_photos_uncensored_backlog_gets_full_k():
    st = by_key(state("1", first_seen=DAY - timedelta(days=3), first_seen_censored=False))
    assert len(plan_photos(st, by_key(card("1", photo_ids=photos("1", 10))), set(), PH)) == 6


def test_plan_photos_partial_listing_is_redone():
    st = by_key(state("1", first_seen_censored=False, photos_done=2, photo_ids_hash=photo_ids_hash(photos("1", 10))))
    assert len(plan_photos(st, by_key(card("1", photo_ids=photos("1", 10))), set(), PH)) == 6


def test_plan_photos_listing_with_few_photos_is_complete():
    st = by_key(state("1", first_seen_censored=False, photos_done=2, photo_ids_hash=photo_ids_hash(photos("1", 2))))
    assert plan_photos(st, by_key(card("1", photo_ids=photos("1", 2))), set(), PH) == []


def test_plan_photos_priority_new_then_changed_then_backlog_under_cap():
    st = by_key(
        state("1", first_seen=DAY),
        state("2", photos_done=6, photo_ids_hash=photo_ids_hash(["vecchia"])),
        state("3", first_seen=date(2026, 1, 1), first_seen_censored=True),
    )
    cards = by_key(*(card(i, photo_ids=photos(i, 6)) for i in ("1", "2", "3")))
    tasks = plan_photos(st, cards, {("trovacasa", "1")}, Settings(photos_new=6, photos_backlog=3, max_photos_per_run=12))
    assert [t.key[1] for t in tasks] == ["1"] * 6 + ["2"] * 6


def test_bucket_with_unicode_digits_does_not_crash():
    tasks = plan([fresh("²", last_detail_date=DAY - timedelta(days=1))], [card("²")])
    assert set(reasons(tasks).values()) <= {"rotation"}
