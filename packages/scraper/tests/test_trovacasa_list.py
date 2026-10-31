from conftest import fx
from fakesite import card_html, list_page_html

from scraper.sources.trovacasa import list_url, parse_list_page, photo_url


def test_parse_list_page_milano_p1():
    p = parse_list_page(fx("list_milano_vendita_p1.html"), "milano", "vendita", 1)
    assert p.declared_total == 17430 and len(p.cards) == 24
    c = next(c for c in p.cards if c.listing_id == "73817239")
    assert c.url == "https://www.trovacasa.it/annunci/mi-tc-3427-73817239"
    assert c.title == "Appartamento da privato a Milano via Masaccio, 18"
    assert c.property_type == "Appartamento" and c.is_private and not c.is_auction
    assert c.neighborhood == "Monte Rosa - Lotto"
    assert (c.surface_m2, c.rooms, c.price_eur) == (75.0, 2, 450000)
    assert c.price_on_request is False
    assert "Da Privato" in c.tags and c.advertiser_id == "3427"
    assert c.photo_ids[0] == "X_999999505_73817239_2036249360" and c.eliminato is False
    assert (c.source, c.city, c.contract, c.page) == ("trovacasa", "milano", "vendita", 1)
    assert [x.position for x in p.cards] == list(range(24))


def test_parse_list_page_empty_neighborhood_is_none():
    p = parse_list_page(fx("list_milano_vendita_p1.html"), "milano", "vendita", 1)
    c = next(c for c in p.cards if c.listing_id == "73623446")
    assert c.neighborhood is None and c.advertiser_id == "1035"


def test_parse_card_price_on_request():
    html = list_page_html([card_html("1", price="Prezzo su richiesta")], 1)
    c = parse_list_page(html, "milano", "vendita", 1).cards[0]
    assert c.price_eur is None and c.price_on_request is True


def test_parse_card_missing_infos():
    html = list_page_html([card_html("2", surface=None, rooms="1 locale")], 1)
    c = parse_list_page(html, "milano", "vendita", 1).cards[0]
    assert c.surface_m2 is None and c.rooms == 1


def test_parse_card_large_surface_with_thousands_separator():
    html = list_page_html([card_html("3", surface="1.200 m&#xB2;")], 1)
    assert parse_list_page(html, "milano", "vendita", 1).cards[0].surface_m2 == 1200.0


def test_parse_list_page_busto_has_auctions():
    p = parse_list_page(fx("list_busto-arsizio_vendita_p1.html"), "busto-arsizio", "vendita", 1)
    assert p.declared_total == 1006 and len(p.cards) == 24
    auctions = [c for c in p.cards if c.is_auction]
    assert auctions and all(c.property_type == "Appartamento" for c in auctions)
    assert any(c.is_private for c in p.cards)


def test_parse_list_page_affitto():
    p = parse_list_page(fx("list_milano_affitto_p1.html"), "milano", "affitto", 1)
    assert p.declared_total == 15748 and len(p.cards) == 24
    assert all(c.price_eur and c.price_eur < 100000 for c in p.cards if c.price_eur)


def test_parse_list_page_last_page_has_fewer_cards():
    p = parse_list_page(fx("list_milano_vendita_last.html"), "milano", "vendita", 727)
    assert len(p.cards) == 9 and p.cards[0].page == 727


def test_parse_list_page_without_cards():
    p = parse_list_page("<html><body>Nessun risultato</body></html>", "milano", "vendita", 800)
    assert p.cards == [] and p.declared_total is None


def test_list_url_first_page_has_no_param():
    assert list_url("milano", "vendita", 1) == "https://www.trovacasa.it/case-in-vendita/milano"
    assert list_url("milano", "affitto", 3) == "https://www.trovacasa.it/case-in-affitto/milano?page=3"


def test_photo_url_formats():
    assert photo_url("A_1035_73623446_1273045083") == "https://img.trovacasa.it/annunci/mlis/A_1035_73623446_1273045083/foto.jpg"
    assert photo_url("X_999999505_73817239_2036249360") == "https://pic.trovacasa.it/image/2036249360/m-c.jpg"


def test_property_type_with_inner_a():
    html = list_page_html(
        [
            card_html("4", title="Villa a Schiera a Milano via Giuseppe Rossi"),
            card_html("5", title="Villa a Schiera da privato a Milano viale Monza, 3"),
            card_html("6", title="Appartamento a Busto Arsizio via Roma"),
        ],
        3,
    )
    types = [c.property_type for c in parse_list_page(html, "milano", "vendita", 1).cards]
    assert types[:2] == ["Villa a Schiera", "Villa a Schiera"]
    types_busto = parse_list_page(html, "busto-arsizio", "vendita", 1).cards[2].property_type
    assert types_busto == "Appartamento"


def test_property_types_from_last_page_fixture():
    p = parse_list_page(fx("list_milano_vendita_last.html"), "milano", "vendita", 727)
    assert "Villa a Schiera" in {c.property_type for c in p.cards}


def test_has_next_follows_the_pager():
    # The collection follows the pager's "next" link instead of requesting a page past the end
    # (decision 0006): the last page has no "next" link.
    assert parse_list_page(fx("list_milano_vendita_p1.html"), "milano", "vendita", 1).has_next is True
    assert parse_list_page(fx("list_milano_vendita_last.html"), "milano", "vendita", 727).has_next is False
    assert parse_list_page(fx("list_zerbolo_affitto_one.html"), "zerbolo", "affitto", 1).has_next is False
