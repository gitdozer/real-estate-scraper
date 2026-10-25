"""Costruttori di record per i test della logica (stato, pianificazione)."""

from datetime import date

from scraper.models import Card, Detail, ListingState

SEG = ("trovacasa", "milano", "vendita")


def card(listing_id: str, price: int | None = 250000, city: str = "milano", contract: str = "vendita", **kw) -> Card:
    data = dict(
        source="trovacasa",
        listing_id=listing_id,
        city=city,
        contract=contract,
        url=f"https://www.trovacasa.it/annunci/mi-tc-1-{listing_id}",
        title="Appartamento a Milano via Roma, 1",
        property_type="Appartamento",
        is_private=False,
        is_auction=False,
        neighborhood=None,
        surface_m2=80.0,
        rooms=3,
        price_eur=price,
        price_on_request=price is None,
        tags=[],
        photo_ids=[f"A_1_{listing_id}_1", f"A_1_{listing_id}_2"],
        advertiser_id="1",
        eliminato=False,
        page=1,
        position=0,
    )
    data.update(kw)
    return Card(**data)


def detail(listing_id: str, description: str = "Bel trilocale", **kw) -> Detail:
    data = dict(
        source="trovacasa",
        listing_id=listing_id,
        title="Appartamento in vendita a Milano via Roma, 1",
        price_eur=250000,
        price_on_request=False,
        address="Via Roma, 1",
        property_type="Appartamento",
        contract="Vendita",
        municipality="Milano",
        listing_code=f"TC{listing_id}",
        agency_reference="REF-1",
        surface_m2=80.0,
        rooms=3,
        bathrooms=1,
        floor=None,
        energy_class="E",
        energy_kwh_m2_year=120.0,
        features=["Ascensore"],
        attributes={},
        description=description,
        agency_name="Agenzia",
        agency_id="1",
        agency_address=None,
        latitude=45.0,
        longitude=9.0,
    )
    data.update(kw)
    return Detail(**data)


def state(listing_id: str, status: str = "active", city: str = "milano", contract: str = "vendita", **kw) -> ListingState:
    data = dict(
        source="trovacasa",
        listing_id=listing_id,
        city=city,
        contract=contract,
        url=f"https://www.trovacasa.it/annunci/mi-tc-1-{listing_id}",
        status=status,
        in_scope=True,
        exclusion_reason=None,
        flags=[],
        first_seen=date(2026, 10, 1),
        spell_start=date(2026, 10, 1),
        first_seen_censored=False,
        list_last_seen=date(2026, 10, 25),
        absent_since=None,
        missing_streak=0,
        delisted_date=None,
        detail_gone_date=None,
        last_check_date=None,
        last_fingerprint=None,
        last_price=250000,
        last_detail_date=date(2026, 10, 25),
        last_detail_hash=None,
        photo_ids_hash=None,
        photos_done=0,
    )
    data.update(kw)
    return ListingState(**data)


def by_key(*items):
    return {(i.source, i.listing_id): i for i in items}
