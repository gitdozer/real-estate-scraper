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


class Detail(BaseModel):
    """Dati della pagina di dettaglio di un annuncio."""

    source: str
    listing_id: str
    title: str | None
    price_eur: int | None
    price_on_request: bool
    address: str | None
    property_type: str | None
    contract: str | None
    municipality: str | None
    listing_code: str | None
    agency_reference: str | None
    surface_m2: float | None
    rooms: int | None
    bathrooms: int | None
    floor: str | None
    energy_class: str | None
    energy_kwh_m2_year: float | None
    features: list[str]
    attributes: dict[str, str]
    description: str | None
    agency_name: str | None
    agency_id: str | None
    agency_address: str | None
    latitude: float | None
    longitude: float | None


class ListPage(BaseModel):
    cards: list[Card]
    declared_total: int | None
