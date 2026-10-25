"""Riconciliazione dello stato degli annunci: il cuore della regola "sparito = venduto".

Funzione pura (nessun I/O). Regole in docs/logica-scomparse.md; in sintesi:
- un annuncio presente negli elenchi è attivo (nuovo, invariato, ribassato o ricomparso);
- un annuncio assente cambia stato SOLO se il suo segmento è stato raccolto per
  intero oggi E il controllo della sua pagina di dettaglio ha dato un esito certo:
  404 → removed; 200 per due run completi consecutivi → delisted;
- errori, controlli non eseguiti o segmenti incompleti non cambiano nulla.
"""

from datetime import date

from scraper.fingerprint import card_fingerprint, detail_hash
from scraper.models import Card, CheckOutcome, Detail, Event, ListingKey, ListingState, SegmentKey
from scraper.scope import classify

DELIST_AFTER_ABSENT_RUNS = 2


def _str(value: int | None) -> str | None:
    return None if value is None else str(value)


def _present(prev: ListingState | None, card: Card, bootstrap: bool, run_date: date, events: list[Event]) -> ListingState:
    in_scope, reason, flags = classify(card)
    common = dict(
        url=card.url,
        city=card.city,
        contract=card.contract,
        in_scope=in_scope,
        exclusion_reason=reason,
        flags=flags,
        list_last_seen=run_date,
        absent_since=None,
        missing_streak=0,
        last_fingerprint=card_fingerprint(card),
        last_price=card.price_eur,
    )
    ev = dict(source=card.source, listing_id=card.listing_id, city=card.city, contract=card.contract, run_date=run_date)

    if prev is None:
        events.append(Event(**ev, type="new", new_value=_str(card.price_eur)))
        return ListingState(
            source=card.source,
            listing_id=card.listing_id,
            status="active",
            first_seen=run_date,
            spell_start=run_date,
            first_seen_censored=bootstrap,
            delisted_date=None,
            detail_gone_date=None,
            last_check_date=None,
            last_detail_date=None,
            last_detail_hash=None,
            photo_ids_hash=None,
            photos_done=0,
            **common,
        )

    spell_start = prev.spell_start
    if prev.status != "active":
        # Ricompare con lo stesso ID: si chiude il periodo precedente (date nell'evento) e se ne apre uno nuovo.
        events.append(
            Event(
                **ev,
                type="reappeared",
                old_value=prev.status,
                new_value="active",
                spell_start=prev.spell_start,
                list_last_seen=prev.list_last_seen,
                delisted_date=prev.delisted_date,
            )
        )
        spell_start = run_date
    if card.price_eur != prev.last_price:
        events.append(Event(**ev, type="price_change", old_value=_str(prev.last_price), new_value=_str(card.price_eur)))
    return prev.model_copy(update=dict(status="active", spell_start=spell_start, delisted_date=None, detail_gone_date=None, **common))


def _absent(prev: ListingState, check: CheckOutcome | None, run_date: date, events: list[Event]) -> ListingState:
    if check not in ("alive", "gone"):
        return prev  # nessun esito certo: non si decide nulla
    ev = dict(source=prev.source, listing_id=prev.listing_id, city=prev.city, contract=prev.contract, run_date=run_date)

    if prev.status == "active":
        absent_since = prev.absent_since or run_date
        base = dict(absent_since=absent_since, last_check_date=run_date)
        spell = dict(spell_start=prev.spell_start, list_last_seen=prev.list_last_seen, delisted_date=absent_since)
        if check == "gone":
            events.append(Event(**ev, type="removed", **spell))
            return prev.model_copy(update=dict(status="removed", delisted_date=absent_since, detail_gone_date=run_date, **base))
        streak = prev.missing_streak + 1
        if streak >= DELIST_AFTER_ABSENT_RUNS:
            events.append(Event(**ev, type="delisted", **spell))
            return prev.model_copy(update=dict(status="delisted", delisted_date=absent_since, missing_streak=streak, **base))
        return prev.model_copy(update=dict(missing_streak=streak, **base))

    if prev.status == "delisted":
        if check == "gone":
            events.append(
                Event(**ev, type="detail_gone", spell_start=prev.spell_start, list_last_seen=prev.list_last_seen, delisted_date=prev.delisted_date)
            )
            return prev.model_copy(update=dict(status="removed", detail_gone_date=run_date, last_check_date=run_date))
        return prev.model_copy(update=dict(last_check_date=run_date))

    return prev  # removed: resta tale finché non ricompare negli elenchi


def _apply_detail(state: ListingState, detail: Detail, run_date: date, events: list[Event]) -> ListingState:
    h = detail_hash(detail)
    if state.last_detail_hash is not None and state.last_detail_hash != h:
        events.append(
            Event(source=state.source, listing_id=state.listing_id, city=state.city, contract=state.contract, run_date=run_date, type="detail_changed")
        )
    return state.model_copy(update=dict(last_detail_date=run_date, last_detail_hash=h))


def reconcile(
    prev: dict[ListingKey, ListingState],
    cards: dict[ListingKey, Card],
    details: dict[ListingKey, Detail],
    checks: dict[ListingKey, CheckOutcome],
    scraped_segments: set[SegmentKey],
    segment_ok: dict[SegmentKey, bool],
    bootstrap_segments: set[SegmentKey],
    run_date: date,
) -> tuple[dict[ListingKey, ListingState], list[Event]]:
    """Calcola il nuovo stato e gli eventi del giorno.

    `cards` contiene le schede viste oggi (già deduplicate) dei soli segmenti raccolti.
    `checks` contiene l'esito dei controlli di dettaglio degli annunci assenti.
    """
    new: dict[ListingKey, ListingState] = dict(prev)
    events: list[Event] = []

    for key, card in cards.items():
        new[key] = _present(prev.get(key), card, card.segment in bootstrap_segments, run_date, events)

    for key, old in prev.items():
        if key in cards:
            continue
        if old.segment not in scraped_segments or not segment_ok.get(old.segment, False):
            continue  # segmento non raccolto o incompleto: nessuna scomparsa
        new[key] = _absent(old, checks.get(key), run_date, events)

    for key, detail in details.items():
        if key in new:
            new[key] = _apply_detail(new[key], detail, run_date, events)

    return new, events
