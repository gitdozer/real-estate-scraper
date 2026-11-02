"""Collection scope: which listings are "real" residential property (spec §6.1).

Out-of-scope listings are still saved in the observations, flagged, but they get
no detail download. Doubtful cases stay in scope and are flagged: excluding by
mistake cannot be undone, filtering later can.
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
    """Returns (in_scope, exclusion_reason, flags)."""
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
