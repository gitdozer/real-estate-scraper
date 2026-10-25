from fakesite import card_html, list_page_html

from scraper.fingerprint import card_fingerprint, photo_ids_hash
from scraper.sources.trovacasa import parse_list_page


def card(page=1, price="250.000 &#x20AC;", tags=("Ascensore", "Cantina")):
    html = list_page_html([card_html("10", price=price, tags=tags, photo_ids=("A_1_10_1", "A_1_10_2"))], 1)
    return parse_list_page(html, "milano", "vendita", page).cards[0]


def test_fingerprint_ignores_page_and_position():
    assert card_fingerprint(card(page=1)) == card_fingerprint(card(page=5))


def test_fingerprint_changes_with_price():
    assert card_fingerprint(card()) != card_fingerprint(card(price="240.000 &#x20AC;"))


def test_fingerprint_ignores_tag_order():
    assert card_fingerprint(card(tags=("Ascensore", "Cantina"))) == card_fingerprint(card(tags=("Cantina", "Ascensore")))


def test_fingerprint_is_16_hex():
    fp = card_fingerprint(card())
    assert len(fp) == 16 and int(fp, 16) >= 0


def test_photo_ids_hash_depends_on_order():
    assert photo_ids_hash(["a", "b"]) != photo_ids_hash(["b", "a"])
    assert len(photo_ids_hash([])) == 16
