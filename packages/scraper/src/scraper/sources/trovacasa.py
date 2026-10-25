"""Fonte trovacasa.it: URL e parsing delle pagine. Struttura del sito in docs/fonti/trovacasa.md."""

import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser, LexborNode as Node

from scraper.models import Card, ListPage

NAME = "trovacasa"
BASE_URL = "https://www.trovacasa.it"
PAGE_SIZE = 24

_DECLARED_TOTAL = re.compile(r"([\d.]+) case in (?:vendita|affitto) a")
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


def _parse_card(node: Node, city: str, contract: str, page: int, position: int) -> Card:
    link = node.css_first("a.card__title")
    href = link.attributes.get("href", "") if link is not None else ""
    url_match = _LISTING_URL.search(href)
    id_node = node.css_first("[data-id]")
    listing_id = id_node.attributes.get("data-id") if id_node is not None else None
    listing_id = listing_id or (url_match.group(2) if url_match else "")

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
        url=detail_url(href) if href else "",
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
    cards = [_parse_card(n, city, contract, page, i) for i, n in enumerate(tree.css("div.card.js_card_immobile"))]
    m = _DECLARED_TOTAL.search(html)
    declared = int(m.group(1).replace(".", "")) if m else None
    return ListPage(cards=cards, declared_total=declared)


class _Trovacasa:
    """Implementazione di sources.base.Source per trovacasa.it."""

    name = NAME
    page_size = PAGE_SIZE
    list_url = staticmethod(list_url)
    detail_url = staticmethod(detail_url)
    parse_list_page = staticmethod(parse_list_page)
    photo_url = staticmethod(photo_url)


TROVACASA = _Trovacasa()
