"""Impronte (hash brevi) per capire se una scheda o un dettaglio sono cambiati."""

import hashlib
import json

from scraper.models import Card, Detail


def _hash16(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def card_fingerprint(card: Card) -> str:
    """Cambia solo se cambia il contenuto della scheda, non la sua posizione negli elenchi."""
    return _hash16(
        [
            card.price_eur,
            card.price_on_request,
            card.surface_m2,
            card.rooms,
            card.title,
            sorted(card.tags),
            card.photo_ids,
        ]
    )


def detail_hash(detail: Detail) -> str:
    """Cambia se cambia un qualsiasi dato della pagina di dettaglio."""
    return _hash16(detail.model_dump(exclude={"source"}))


def photo_ids_hash(ids: list[str]) -> str:
    return _hash16(list(ids))
