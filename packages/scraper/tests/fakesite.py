"""HTML sintetico con la stessa struttura di trovacasa.it, per i test.

Riproduce solo gli elementi che il parser legge (vedi docs/fonti/trovacasa.md).
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
