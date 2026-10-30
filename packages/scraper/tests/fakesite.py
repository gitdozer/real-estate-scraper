"""HTML sintetico con la stessa struttura di trovacasa.it, per i test.

Riproduce solo gli elementi che il parser legge (vedi docs/sources/trovacasa.md).
"""

from html import escape


def card_html(
    listing_id: str,
    title: str = "Appartamento a Milano via Roma, 1",
    price: str = "250.000 &#x20AC;",
    surface: str | None = "80 m&#xB2;",
    rooms: str | None = "3 locali",
    tags: tuple[str, ...] = (),
    photo_ids: tuple[str, ...] = (),
    neighborhood: str = "",
    advertiser: str = "1035",
    prov: str = "mi",
    eliminato: bool = False,
) -> str:
    infos = "".join(f'<span class="card__info">{x}</span>' for x in (surface, rooms) if x)
    tag_html = "".join(f'<p class="annuncioTag">{escape(t)}</p>' for t in tags)
    photos = "|".join(photo_ids)
    return f"""
<div class="immobileListing__card js_immobileListing_card">
  <a name="{listing_id}" style="visibility: hidden;"></a>
  <div data-eliminato="{eliminato}" class="card js_slider_external js_card_immobile">
    <div data-src-list="{photos}" class="card__imgContainer"></div>
    <div class="card__elementsContainer">
      <div data-id="{listing_id}" data-cmd="cuore" class="heart card__heart js_preferiti"></div>
      <a href="/annunci/{prov}-tc-{advertiser}-{listing_id}" class="card__title js_link_immobile">{escape(title)}</a>
      <span class="card__quartiere">{escape(neighborhood)}</span>
      <div class="card__infoContainer">{infos}</div>
      <span class="card__price">{price}</span>
      <div class="card__tagContainer">{tag_html}</div>
    </div>
  </div>
</div>"""


def list_page_html(cards: list[str], declared_total: int | None, contract: str = "vendita", city: str = "Milano") -> str:
    total = "" if declared_total is None else f"<h1>{declared_total:,}".replace(",", ".") + f" case in {contract} a {city}</h1>"
    return f"<html><body>{total}<div class='immobileListing'>{''.join(cards)}</div></body></html>"


def detail_html(listing_id: str, price: str = "250.000 &#x20AC;", description: str = "Bel trilocale luminoso", contract: str = "Vendita") -> str:
    rows = {
        "Tipologia": "Appartamento",
        "Contratto": contract,
        "Comune": "Milano",
        "Indirizzo": "Via Roma, 1",
        "Codice annuncio": f"TC{listing_id}",
        "Riferimento": f"REF-{listing_id}",
        "Prezzo": price,
        "Superficie": "80 m&#xB2;",
        "Numero locali": "3",
        "Numero bagni": "1",
        "Classe energetica": "non disponibile",
    }
    dl = "".join(f'<dl class="row"><dt class="term">{k}:</dt><dd class="description">{v}</dd></dl>' for k, v in rows.items())
    return f"""<html><body>
<h1 class="immobile__title headingOne">Appartamento in {contract.lower()} a Milano via Roma, 1</h1>
<span class="price">{price}</span>
<a href="/agenzie-immobiliari/agenzia-tc-1" class="agenzia__name hoverLink">Agenzia Test</a>
<p class="immobileDetails__text js_fit_descr">{escape(description)}</p>
<div class="immobileDetails__table">{dl}</div>
<a class="immobileDetails__tagLabel">Ascensore</a>
<script>var latitude = 45.46;
var longitude = 9.19;</script>
</body></html>"""


def tiny_png(seed: int = 0) -> bytes:
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (64, 48), "white")
    ImageDraw.Draw(img).rectangle([seed % 40, 5, seed % 40 + 20, 40], fill=(seed * 37 % 255, 80, 160))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


CITY_NAMES = {"milano": "Milano", "monza": "Monza", "marnate": "Marnate"}


class FakeSite:
    """Sito trovacasa simulato per i test della pipeline.

    listings[(slug, contract)] = lista di ID visibili negli elenchi (in ordine).
    alive = ID la cui pagina di dettaglio risponde 200 anche se non sono negli elenchi.
    Tutti gli altri ID rispondono 404 sul dettaglio.
    """

    def __init__(self):
        self.listings: dict[tuple[str, str], list[str]] = {}
        self.prices: dict[str, str] = {}
        self.alive: set[str] = set()
        self.failing_pages: set[tuple[str, str, int]] = set()
        self.declared_override: dict[tuple[str, str], int] = {}
        self.extra_on_page: dict[tuple[str, str, int], list[str]] = {}
        self.missing_pages: set[tuple[str, str, int]] = set()  # pagine che rispondono 404
        self.requests: list[str] = []

    def _page_ids(self, slug: str, contract: str, page: int) -> list[str]:
        ids = self.listings.get((slug, contract), [])
        return ids[(page - 1) * 24 : page * 24] + self.extra_on_page.get((slug, contract, page), [])

    def handler(self, request):
        import httpx

        self.requests.append(str(request.url))
        host, path = request.url.host, request.url.path
        if host in ("img.trovacasa.it", "pic.trovacasa.it"):
            return httpx.Response(200, content=tiny_png(len(path)))
        parts = path.strip("/").split("/")
        if parts[0].startswith("case-in-"):
            contract, slug = parts[0].removeprefix("case-in-"), parts[1]
            page = int(request.url.params.get("page", "1"))
            if (slug, contract, page) in self.failing_pages:
                return httpx.Response(503)
            if (slug, contract, page) in self.missing_pages:
                return httpx.Response(404)
            ids = self._page_ids(slug, contract, page)
            if page > 1 and not ids:
                return httpx.Response(404)
            declared = self.declared_override.get((slug, contract), len(self.listings.get((slug, contract), [])))
            cards = [
                card_html(i, price=self.prices.get(i, "250.000 &#x20AC;"), photo_ids=(f"A_1_{i}_1", f"A_1_{i}_2"), advertiser="1")
                for i in ids
            ]
            return httpx.Response(200, text=list_page_html(cards, declared, contract, CITY_NAMES.get(slug, slug)))
        if parts[0] == "annunci":
            listing_id = parts[1].rsplit("-", 1)[-1]
            visible = any(listing_id in ids for ids in self.listings.values())
            if visible or listing_id in self.alive:
                return httpx.Response(200, text=detail_html(listing_id, price=self.prices.get(listing_id, "250.000 &#x20AC;")))
            return httpx.Response(404, text="non trovato")
        return httpx.Response(404)
