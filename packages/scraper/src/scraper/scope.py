"""Perimetro della raccolta: quali annunci sono residenziali "veri" (spec §6.1).

Gli annunci fuori perimetro si salvano comunque nelle osservazioni, marcati,
ma non ricevono il dettaglio. I casi dubbi restano dentro e vengono marcati:
escludere per errore è irreversibile, filtrare dopo no.
"""

from scraper.models import Card

_WHOLE_BUILDING = {"intero stabile", "palazzo"}
_ROOM_PREFIXES = ("stanza", "posto letto")
_FLAG_TAGS = {
    "Nuova Costruzione": "new_build",
    "Affitto con riscatto": "rent_to_buy",
    "A Reddito": "investment",
}


def classify(card: Card) -> tuple[bool, str | None, list[str]]:
    """Restituisce (in_scope, exclusion_reason, flags)."""
    title = card.title.lower()
    ptype = (card.property_type or "").lower()
    flags = [flag for tag, flag in _FLAG_TAGS.items() if tag in card.tags]

    if card.is_auction or any("asta giudiziaria" in t.lower() for t in card.tags):
        return False, "auction", flags
    if ptype in _WHOLE_BUILDING:
        return False, "whole_building", flags
    if title.startswith(_ROOM_PREFIXES):
        return False, "room", flags
    return True, None, flags
