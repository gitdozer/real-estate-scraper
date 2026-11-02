"""Fingerprints (short hashes) that tell whether a listing card or a detail page has changed."""

import hashlib
import json

from scraper.models import Card, Detail


def _hash16(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def card_fingerprint(card: Card) -> str:
    """Changes only when the card's content changes, not its position in the search results."""
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
    """Changes when any piece of data on the detail page changes."""
    return _hash16(detail.model_dump(exclude={"source"}))


def photo_ids_hash(ids: list[str]) -> str:
    return _hash16(list(ids))
