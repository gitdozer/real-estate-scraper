"""Record dei dati raccolti. Le colonne sono documentate in docs/dizionario-dati.md."""

from datetime import date
from typing import Literal

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


Status = Literal["active", "delisted", "removed"]
EventType = Literal["new", "price_change", "delisted", "removed", "detail_gone", "reappeared", "detail_changed"]
CheckOutcome = Literal["alive", "gone", "error"]


class ListingState(BaseModel):
    """Stato corrente di un annuncio (una riga di state/listings.parquet).

    Le tre date della scomparsa sono spiegate in docs/logica-scomparse.md.
    """

    source: str
    listing_id: str
    city: str
    contract: str
    url: str
    status: Status
    in_scope: bool
    exclusion_reason: str | None
    flags: list[str]
    first_seen: date
    first_seen_censored: bool
    list_last_seen: date
    absent_since: date | None
    missing_streak: int
    delisted_date: date | None
    detail_gone_date: date | None
    last_check_date: date | None
    last_fingerprint: str | None
    last_price: int | None
    last_detail_date: date | None
    last_detail_hash: str | None
    photo_ids_hash: str | None
    photos_done: int

    @property
    def key(self) -> ListingKey:
        return (self.source, self.listing_id)

    @property
    def segment(self) -> SegmentKey:
        return (self.source, self.city, self.contract)


class Event(BaseModel):
    source: str
    listing_id: str
    run_date: date
    type: EventType
    old_value: str | None = None
    new_value: str | None = None


class ListPage(BaseModel):
    cards: list[Card]
    declared_total: int | None
