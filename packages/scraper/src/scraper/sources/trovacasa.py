"""Fonte trovacasa.it: URL e parsing delle pagine. Struttura del sito in docs/sources/trovacasa.md."""

import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser, LexborNode as Node

from scraper.models import Card, Detail, ListPage

NAME = "trovacasa"
BASE_URL = "https://www.trovacasa.it"
PAGE_SIZE = 24

_DECLARED_TOTAL = re.compile(r"([\d.]+) cas[ae] in (?:vendita|affitto) a")
_NO_RESULTS = "Nessun risultato"
_LISTING_URL = re.compile(r"-(\d+)-(\d+)/?$")
_TITLE_MARKERS = (" da privato", " all'asta", " all’asta")


def list_url(city_slug: str, contract: str, page: int) -> str:
    url = f"{BASE_URL}/case-in-{contract}/{city_slug}"
    # La pagina 1 va richiesta senza parametro: "?page=1" risponde 301.
    return url if page == 1 else f"{url}?page={page}"


def detail_url(path_or_id: str) -> str:
    return path_or_id if path_or_id.startswith("http") else f"{BASE_URL}{path_or_id}"


def photo_url(photo_id: str) -> str:
    # Due formati osservati: "A_<agenzia>_<annuncio>_<foto>" (agenzie) e "X_<...>_<annuncio>_<foto>" (privati).
    if photo_id.startswith("A_"):
        return f"https://img.trovacasa.it/annunci/mlis/{photo_id}/foto.jpg"
    return f"https://pic.trovacasa.it/image/{photo_id.rsplit('_', 1)[-1]}/m-c.jpg"


def _to_number(text: str) -> float | None:
    """'1.200,5 m²' → 1200.5 (punto = migliaia, virgola = decimali)."""
    m = re.search(r"\d[\d.]*(?:,\d+)?", text)
    if not m:
        return None
    return float(m.group(0).replace(".", "").replace(",", "."))


def _text(node: Node | None) -> str:
    return node.text(strip=True) if node is not None else ""


def _property_type(title: str, city_slug: str) -> str | None:
    """'Villa a Schiera da privato a Milano via …' → 'Villa a Schiera'.

    La tipologia finisce al primo marcatore ("da privato", "all'asta") oppure
    prima di " a <comune>"; non basta il primo " a " (es. "Villa a Schiera").
    """
    lower = title.lower()
    markers = (*_TITLE_MARKERS, f" a {city_slug.replace('-', ' ')}")
    cut = min((i for i in (lower.find(m) for m in markers) if i > 0), default=-1)
    if cut < 0:
        cut = lower.find(" a ")
    return title[:cut].strip() if cut > 0 else (title.strip() or None)


def _parse_card(node: Node, city: str, contract: str, page: int, position: int) -> Card | None:
    link = node.css_first("a.card__title")
    href = link.attributes.get("href", "") if link is not None else ""
    url_match = _LISTING_URL.search(href)
    id_node = node.css_first("[data-id]")
    listing_id = id_node.attributes.get("data-id") if id_node is not None else None
    listing_id = listing_id or (url_match.group(2) if url_match else "")
    if not href or not listing_id:
        return None  # scheda incompleta: senza link o ID non si può seguire

    title = _text(link)
    lower = title.lower()
    is_auction = "all'asta" in lower or "all’asta" in lower

    surface = rooms = None
    for info in node.css("span.card__info"):
        t = _text(info)
        if "m²" in t or "m2" in t:
            surface = _to_number(t)
        elif "local" in t:
            n = _to_number(t)
            rooms = int(n) if n is not None else None

    price_node = node.css_first("span.card__price")
    price_text = _text(price_node)
    price = _to_number(price_text)

    photos_node = node.css_first("[data-src-list]")
    photos_raw = photos_node.attributes.get("data-src-list", "") if photos_node is not None else ""

    return Card(
        source=NAME,
        listing_id=listing_id,
        city=city,
        contract=contract,
        url=detail_url(href),
        title=title,
        property_type=_property_type(title, city),
        is_private=" da privato" in lower,
        is_auction=is_auction,
        neighborhood=_text(node.css_first("span.card__quartiere")) or None,
        surface_m2=surface,
        rooms=rooms,
        price_eur=int(price) if price is not None else None,
        price_on_request=price_node is not None and price is None and bool(price_text),
        tags=[_text(t) for t in node.css("p.annuncioTag") if _text(t)],
        photo_ids=[p for p in (photos_raw or "").split("|") if p],
        advertiser_id=url_match.group(1) if url_match else None,
        eliminato=(node.attributes.get("data-eliminato") or "").lower() == "true",
        page=page,
        position=position,
    )


def parse_list_page(html: str, city: str, contract: str, page: int) -> ListPage:
    tree = HTMLParser(html)
    parsed = [_parse_card(n, city, contract, page, i) for i, n in enumerate(tree.css("div.card.js_card_immobile"))]
    cards = [c for c in parsed if c is not None]
    m = _DECLARED_TOTAL.search(html)
    if m:
        declared = int(m.group(1).replace(".", ""))
    elif page == 1 and not parsed and _NO_RESULTS in html:
        declared = 0  # comune senza annunci: la pagina dice "Nessun risultato"
    elif page == 1 and 0 < len(parsed) < PAGE_SIZE:
        declared = len(parsed)  # con 1 annuncio il sito non scrive il numero ("case in affitto a …")
    else:
        declared = None
    has_next = tree.css_first("a.pager__link.next") is not None
    return ListPage(cards=cards, declared_total=declared, skipped_cards=len(parsed) - len(cards), has_next=has_next)


_LAT = re.compile(r"var latitude = (-?[\d.]+);")
_LON = re.compile(r"var longitude = (-?[\d.]+);")
_AGENCY_ID = re.compile(r"-tc-(\d+)")
_FEATURES_TERM = "Altre caratteristiche"


def _to_int(text: str | None) -> int | None:
    n = _to_number(text or "")
    return int(n) if n is not None else None


def _energy(dd: Node | None) -> tuple[str | None, float | None]:
    """'<span class="ce c">C </span> 134,00 kWh/m² anno' → ('C', 134.0); 'non disponibile' → ('non disponibile', None)."""
    if dd is None:
        return None, None
    label = dd.css_first("span.ce")
    if label is None:
        return (_text(dd) or None), None
    rest = _text(dd).replace(_text(label), "", 1)
    return _text(label) or None, _to_number(rest)


def parse_detail_page(html: str, listing_id: str) -> Detail:
    tree = HTMLParser(html)

    attributes: dict[str, str] = {}
    energy_dd = None
    for row in tree.css("dl.row"):
        term = _text(row.css_first("dt.term")).rstrip(":").strip()
        dd = row.css_first("dd.description")
        if not term or term == _FEATURES_TERM:
            continue
        if term == "Classe energetica":
            energy_dd = dd
        attributes[term] = _text(dd)

    # Una pagina senza il codice di questo annuncio non è il suo dettaglio (pagina di errore,
    # verifica anti-bot, sito ridisegnato): meglio un errore che un dettaglio vuoto.
    if attributes.get("Codice annuncio") != f"TC{listing_id}":
        raise ValueError("pagina di dettaglio non riconosciuta")

    price_text = attributes.get("Prezzo") or _text(tree.css_first("span.price"))
    price = _to_number(price_text)
    energy_class, energy_kwh = _energy(energy_dd)

    agency = tree.css_first(".agenzia__name")
    agency_href = agency.attributes.get("href") if agency is not None else None
    agency_match = _AGENCY_ID.search(agency_href or "")
    lat, lon = _LAT.search(html), _LON.search(html)

    return Detail(
        source=NAME,
        listing_id=listing_id,
        title=_text(tree.css_first("h1.immobile__title")) or None,
        price_eur=int(price) if price is not None else None,
        price_on_request=price is None and bool(price_text),
        address=attributes.get("Indirizzo") or (_text(tree.css_first("a.indirizzo")) or None),
        property_type=attributes.get("Tipologia"),
        contract_label=attributes.get("Contratto"),
        municipality=attributes.get("Comune"),
        listing_code=attributes.get("Codice annuncio"),
        agency_reference=attributes.get("Riferimento") or None,
        surface_m2=_to_number(attributes.get("Superficie", "")),
        rooms=_to_int(attributes.get("Numero locali")),
        bathrooms=_to_int(attributes.get("Numero bagni")),
        floor=attributes.get("Piano") or None,
        energy_class=energy_class,
        energy_kwh_m2_year=energy_kwh,
        features=[_text(t) for t in tree.css("a.immobileDetails__tagLabel") if _text(t)],
        attributes=attributes,
        description=_text(tree.css_first("p.immobileDetails__text")) or None,
        agency_name=_text(agency) or None,
        agency_id=agency_match.group(1) if agency_match else None,
        agency_address=_text(tree.css_first("p.agenzia__address")) or None,
        latitude=float(lat.group(1)) if lat else None,
        longitude=float(lon.group(1)) if lon else None,
    )


class _Trovacasa:
    """Implementazione di sources.base.Source per trovacasa.it."""

    name = NAME
    page_size = PAGE_SIZE
    list_url = staticmethod(list_url)
    detail_url = staticmethod(detail_url)
    parse_list_page = staticmethod(parse_list_page)
    parse_detail_page = staticmethod(parse_detail_page)
    photo_url = staticmethod(photo_url)


TROVACASA = _Trovacasa()
