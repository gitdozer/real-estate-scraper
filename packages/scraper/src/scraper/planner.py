"""Pianificazione giornaliera: quali dettagli e quali foto scaricare (spec §6.2, §6.4)."""

import zlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from scraper.config import Settings
from scraper.fingerprint import card_fingerprint, photo_ids_hash
from scraper.models import Card, ListingKey, ListingState, SegmentKey
from scraper.scope import classify

DetailReason = Literal["absence_check", "new", "changed", "never_detailed", "delisted_recheck", "rotation", "full"]
# Ordine di priorità: se il run deve fermarsi per tempo, si perdono prima gli ultimi.
_PRIORITY: list[str] = ["absence_check", "new", "changed", "never_detailed", "delisted_recheck", "rotation", "full"]


@dataclass(frozen=True)
class DetailTask:
    key: ListingKey
    url: str
    reason: DetailReason


@dataclass(frozen=True)
class PhotoTask:
    key: ListingKey
    photo_id: str
    index: int


def _bucket(listing_id: str, days: int) -> int:
    n = int(listing_id) if listing_id.isascii() and listing_id.isdecimal() else zlib.crc32(listing_id.encode("utf-8"))
    return n % days


def _rotation_due(st: ListingState, run_date: date, days: int) -> bool:
    """Ogni annuncio ha un suo giorno fisso nel ciclo di `days` giorni, così i dettagli
    scaricati tutti insieme (es. al bootstrap) non scadono tutti lo stesso giorno."""
    last = st.last_detail_date
    if last is None or last >= run_date:
        return False
    if run_date - last >= timedelta(days=2 * days):
        return True
    return _bucket(st.listing_id, days) == run_date.toordinal() % days


def _card_reason(prev: ListingState | None, card: Card, settings: Settings, run_date: date) -> str | None:
    if prev is None or prev.status != "active":
        return "new"
    if prev.last_fingerprint != card_fingerprint(card):
        return "changed"
    if prev.last_detail_date is None:
        return "never_detailed"
    if _rotation_due(prev, run_date, settings.rotation_days):
        return "rotation"
    if settings.full_details:
        return "full"
    return None


def plan_details(
    prev: dict[ListingKey, ListingState],
    cards: dict[ListingKey, Card],
    check_segments: set[SegmentKey],
    settings: Settings,
    run_date: date,
) -> list[DetailTask]:
    """`check_segments`: segmenti raccolti E completi oggi. Solo lì i controlli di assenza
    servono: negli altri `reconcile` ne scarterebbe comunque l'esito."""
    tasks: list[DetailTask] = []

    for key, card in cards.items():
        if not classify(card)[0]:
            continue  # fuori perimetro: nessun dettaglio
        reason = _card_reason(prev.get(key), card, settings, run_date)
        if reason:
            tasks.append(DetailTask(key, card.url, reason))

    recheck = timedelta(days=settings.delisted_recheck_days)
    for key, st in prev.items():
        if key in cards or st.segment not in check_segments:
            continue
        if st.status == "active":
            tasks.append(DetailTask(key, st.url, "absence_check"))
        elif st.status == "delisted" and (st.last_check_date is None or run_date - st.last_check_date >= recheck):
            tasks.append(DetailTask(key, st.url, "delisted_recheck"))

    # A parità di motivo, prima i dettagli più vecchi: se la scadenza taglia la coda,
    # non sono sempre gli stessi annunci a restare indietro.
    last = {k: (s.last_detail_date or date.min) for k, s in prev.items()}
    return sorted(tasks, key=lambda t: (_PRIORITY.index(t.reason), last.get(t.key, date.min)))


def plan_photos(
    state: dict[ListingKey, ListingState],
    cards: dict[ListingKey, Card],
    new_keys: set[ListingKey],
    settings: Settings,
) -> list[PhotoTask]:
    """Prima i nuovi (K pieno), poi le liste foto cambiate (K pieno), poi l'arretrato
    dal più vecchio (K ridotto). Si aggiungono solo annunci interi entro il tetto."""
    plans: list[tuple[ListingKey, int]] = []
    planned: set[ListingKey] = set()

    def add(key: ListingKey, k: int) -> None:
        if key not in planned:
            plans.append((key, k))
            planned.add(key)

    def eligible(key: ListingKey) -> bool:
        st, card = state.get(key), cards.get(key)
        return st is not None and card is not None and st.status == "active" and st.in_scope and bool(card.photo_ids)

    def target(key: ListingKey) -> int:
        # K ridotto solo per gli annunci già online all'avvio (censurati); gli altri hanno K pieno.
        return settings.photos_backlog if state[key].first_seen_censored else settings.photos_new

    for key in sorted(new_keys):
        if eligible(key) and not state[key].first_seen_censored:
            add(key, settings.photos_new)

    for key in sorted(cards):
        st = state.get(key)
        if eligible(key) and st.photos_done > 0 and st.photo_ids_hash != photo_ids_hash(cards[key].photo_ids):
            add(key, settings.photos_new)

    # Arretrato: annunci con meno impronte del dovuto (mai fatte, o interrotte a metà).
    backlog = [k for k in cards if eligible(k) and state[k].photos_done < min(target(k), len(cards[k].photo_ids))]
    for key in sorted(backlog, key=lambda k: (state[k].first_seen, k[1])):
        add(key, target(key))

    tasks: list[PhotoTask] = []
    for key, k in plans:
        ids = cards[key].photo_ids[:k]
        if len(tasks) + len(ids) > settings.max_photos_per_run:
            break
        tasks.extend(PhotoTask(key, pid, i) for i, pid in enumerate(ids))
    return tasks
