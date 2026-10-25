"""Record dei dati raccolti. Le colonne sono documentate in docs/dizionario-dati.md."""

from pydantic import BaseModel

# Incrementare a ogni modifica dello schema dei file Parquet e annotarla nel dizionario dati.
SCHEMA_VERSION = 1

ListingKey = tuple[str, str]  # (source, listing_id)
SegmentKey = tuple[str, str, str]  # (source, city_slug, contract)


class Card(BaseModel):
    """Scheda di un annuncio come appare nella pagina elenco."""

    source: str
    listing_id: str
    city: str
    contract: str
    url: str
    title: str
    property_type: str | None
    is_private: bool
    is_auction: bool
    neighborhood: str | None
    surface_m2: float | None
    rooms: int | None
    price_eur: int | None
    price_on_request: bool
    tags: list[str]
    photo_ids: list[str]
    advertiser_id: str | None
    eliminato: bool
    page: int
    position: int

    @property
    def key(self) -> ListingKey:
        return (self.source, self.listing_id)

    @property
    def segment(self) -> SegmentKey:
        return (self.source, self.city, self.contract)


class ListPage(BaseModel):
    cards: list[Card]
    declared_total: int | None
