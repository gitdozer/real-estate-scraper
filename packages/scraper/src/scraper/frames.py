"""Schemi espliciti delle tabelle Parquet (documentati in docs/dizionario-dati.md).

Tipi fissi anche quando una colonna è tutta nulla o la tabella è vuota: così i file di
giorni diversi si leggono insieme senza conflitti di tipo.
"""

import polars as pl

from scraper.models import ListingState

S, I, F, B, D = pl.Utf8, pl.Int64, pl.Float64, pl.Boolean, pl.Date
LS = pl.List(pl.Utf8)

OBSERVATIONS = {
    "source": S, "listing_id": S, "city": S, "contract": S, "url": S, "title": S,
    "property_type": S, "is_private": B, "is_auction": B, "neighborhood": S,
    "surface_m2": F, "rooms": I, "price_eur": I, "price_on_request": B, "tags": LS,
    "photo_ids": LS, "advertiser_id": S, "eliminato": B, "page": I, "position": I,
    "in_scope": B, "exclusion_reason": S, "flags": LS, "fingerprint": S,
    "run_date": D, "source_run": S,
}  # fmt: skip

DETAILS = {
    "source": S, "listing_id": S, "city": S, "contract": S, "title": S,
    "price_eur": I, "price_on_request": B, "address": S, "property_type": S,
    "contract_label": S, "municipality": S, "listing_code": S, "agency_reference": S,
    "surface_m2": F, "rooms": I, "bathrooms": I, "floor": S, "energy_class": S,
    "energy_kwh_m2_year": F, "features": LS, "attributes": S, "description": S,
    "agency_name": S, "agency_id": S, "agency_address": S, "latitude": F,
    "longitude": F, "detail_hash": S, "run_date": D,
}  # fmt: skip

PHOTOS = {
    "source": S, "listing_id": S, "city": S, "contract": S, "photo_index": I,
    "photo_id": S, "phash": S, "dhash": S, "run_date": D,
}  # fmt: skip

EVENTS = {
    "source": S, "listing_id": S, "city": S, "contract": S, "run_date": D, "type": S,
    "old_value": S, "new_value": S, "spell_start": D, "list_last_seen": D, "delisted_date": D,
}  # fmt: skip

RAW = {
    "source": S, "listing_id": S, "city": S, "contract": S, "reason": S, "url": S,
    "final_url": S, "status": I, "html": S, "run_date": D,
}  # fmt: skip

SEGMENTS = {"source": S, "city": S, "contract": S, "first_complete_run": D, "last_complete_run": D}

_PY = {str: S, int: I, float: F, bool: B}


def _state_schema() -> dict:
    import datetime
    import types
    import typing

    schema = {}
    for name, field in ListingState.model_fields.items():
        t = field.annotation
        args = [a for a in typing.get_args(t) if a is not type(None)]
        if isinstance(t, types.UnionType) or typing.get_origin(t) is typing.Union:
            t = args[0]
        if t is datetime.date:
            schema[name] = D
        elif typing.get_origin(t) is list:
            schema[name] = LS
        elif typing.get_origin(t) is typing.Literal:
            schema[name] = S
        else:
            schema[name] = _PY[t]
    return schema


STATE = _state_schema()


def frame(rows: list[dict], schema: dict) -> pl.DataFrame:
    """DataFrame con lo schema dato; le chiavi delle righe devono essere esattamente le colonne."""
    return pl.DataFrame([{k: r.get(k) for k in schema} for r in rows], schema=schema)
