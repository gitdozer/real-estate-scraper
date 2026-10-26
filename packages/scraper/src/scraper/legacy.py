"""Import una tantum dello storico del vecchio scraper (spec §6.5).

Il CSV contiene gli annunci di Milano in vendita visti il 2026-10-17. Serve a:
- sapere che gli annunci ancora online al primo run lo erano almeno dal 2026-10-17;
- registrare come scomparsi, con le loro caratteristiche, quelli spariti nel frattempo.
Si scrive: il Parquet completo in legacy/, una partizione observations del 2026-10-17
(source_run = "legacy"), il CSV originale in legacy/ e, se non esiste, lo stato iniziale.
"""

import ast
import csv
import re
from datetime import date
from pathlib import Path


from scraper import frames
from scraper.models import Card, ListingState
from scraper.pipeline import STATE_KEY
from scraper.scope import classify
from scraper.storage import Storage, partition_key, scraper_version, write_parquet

LEGACY_DATE = date(2026, 10, 17)
SOURCE, CITY, CONTRACT = "trovacasa", "milano", "vendita"
_TYPE_END = (" in ", " da privato", " all'asta", " all’asta", " a milano")
_URL = re.compile(r"-(\d+)-(\d+)/?$")
_ENERGY = re.compile(r"^\s*([A-G]\d?\+?)\s*(?:([\d.,]+)\s*kWh)?", re.IGNORECASE)

LEGACY_SCHEMA = {
    "listing_id": frames.S, "url": frames.S, "title": frames.S, "address": frames.S,
    "property_type": frames.S, "is_private": frames.B, "is_auction": frames.B,
    "price_eur": frames.I, "price_on_request": frames.B, "surface_m2": frames.F,
    "rooms": frames.I, "bathrooms": frames.I, "energy_class": frames.S,
    "energy_kwh_m2_year": frames.F, "tags": frames.LS, "advertiser_id": frames.S,
    "in_scope": frames.B, "exclusion_reason": frames.S, "seen_date": frames.D,
}  # fmt: skip


def _number(text: str) -> float | None:
    m = re.search(r"\d[\d.]*(?:,\d+)?", text or "")
    return float(m.group(0).replace(".", "").replace(",", ".")) if m else None


def _int(text: str) -> int | None:
    """'2.0' → 2 (nel CSV i conteggi sono scritti come float)."""
    try:
        return int(float(text)) if text else None
    except ValueError:
        return None


def _energy(text: str) -> tuple[str | None, float | None]:
    m = _ENERGY.match(text or "")
    if not m:
        return (text.strip() or None), None
    return m.group(1).upper(), _number(m.group(2)) if m.group(2) else None


def _property_type(title: str) -> str | None:
    lower = title.lower()
    cut = min((i for i in (lower.find(m) for m in _TYPE_END) if i > 0), default=-1)
    return title[:cut].strip() if cut > 0 else (title.strip() or None)


def _parse_row(row: dict) -> tuple[dict, Card]:
    title = row["titolo"].strip()
    lower = title.lower()
    price = _number(row["prezzo"])
    url_match = _URL.search(row["url"])
    tags = ast.literal_eval(row["tags"]) if row["tags"].strip() else []
    energy_class, energy_kwh = _energy(row["classe_ener"])
    listing_id = row["_id"].removeprefix("TC")
    card = Card(
        source=SOURCE, listing_id=listing_id, city=CITY, contract=CONTRACT, url=row["url"], title=title,
        property_type=_property_type(title), is_private="da privato" in lower,
        is_auction="all'asta" in lower or "all’asta" in lower, neighborhood=None,
        surface_m2=_number(row["superficie_m2"]), rooms=_int(row["num_locali"]),
        price_eur=int(price) if price is not None else None,
        price_on_request=price is None and bool(row["prezzo"].strip()), tags=list(tags), photo_ids=[],
        advertiser_id=url_match.group(1) if url_match else None, eliminato=False, page=0, position=0,
    )  # fmt: skip
    in_scope, reason, _ = classify(card)
    legacy = dict(
        listing_id=listing_id, url=card.url, title=title, address=row["indirizzo"] or None,
        property_type=card.property_type, is_private=card.is_private, is_auction=card.is_auction,
        price_eur=card.price_eur, price_on_request=card.price_on_request, surface_m2=card.surface_m2,
        rooms=card.rooms, bathrooms=_int(row["num_bagni"]), energy_class=energy_class,
        energy_kwh_m2_year=energy_kwh, tags=card.tags, advertiser_id=card.advertiser_id,
        in_scope=in_scope, exclusion_reason=reason, seen_date=LEGACY_DATE,
    )  # fmt: skip
    return legacy, card


def import_legacy(csv_path: Path, storage: Storage, force: bool = False) -> int:
    if storage.list_keys("runs/"):
        raise RuntimeError("Ci sono già run giornalieri: importare lo storico ora sovrascriverebbe lo stato raccolto.")
    if storage.read_bytes(STATE_KEY) is not None and not force:
        raise RuntimeError("Lo stato esiste già: l'import dello storico va fatto prima del primo run (usa --force per forzare).")
    version = scraper_version()
    with open(csv_path, encoding="utf-8", newline="") as f:
        parsed = [_parse_row(r) for r in csv.DictReader(f, delimiter=";")]

    legacy_rows = [p[0] for p in parsed]
    cards = {c.key: c for _, c in parsed}
    write_parquet(storage, "legacy/trovacasa_milano_2026-10-17.parquet", frames.frame(legacy_rows, LEGACY_SCHEMA), version)
    storage.write_bytes(f"legacy/{Path(csv_path).name}", Path(csv_path).read_bytes())

    obs = []
    for c in cards.values():
        in_scope, reason, flags = classify(c)
        obs.append(c.model_dump() | dict(in_scope=in_scope, exclusion_reason=reason, flags=flags, fingerprint=None,
                                         run_date=LEGACY_DATE, source_run="legacy", page=None, position=None))  # fmt: skip
    write_parquet(storage, partition_key("observations", LEGACY_DATE), frames.frame(obs, frames.OBSERVATIONS), version)

    states = []
    for c in cards.values():
        in_scope, reason, flags = classify(c)
        states.append(
            ListingState(
                source=SOURCE, listing_id=c.listing_id, city=CITY, contract=CONTRACT, url=c.url, status="active",
                in_scope=in_scope, exclusion_reason=reason, flags=flags, first_seen=LEGACY_DATE, spell_start=LEGACY_DATE,
                first_seen_censored=True, list_last_seen=LEGACY_DATE, absent_since=None, missing_streak=0,
                delisted_date=None, detail_gone_date=None, last_check_date=None, last_fingerprint=None,
                last_price=c.price_eur, last_detail_date=None, last_detail_hash=None, photo_ids_hash=None, photos_done=0,
            ).model_dump()
        )  # fmt: skip
    write_parquet(storage, STATE_KEY, frames.frame(states, frames.STATE), version)
    return len(cards)
