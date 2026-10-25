from fakesite import card_html, list_page_html

from scraper.scope import classify
from scraper.sources.trovacasa import parse_list_page


def card(title="Appartamento a Milano via Roma, 1", tags=(), contract="vendita"):
    html = list_page_html([card_html("10", title=title, tags=tags)], 1, contract)
    return parse_list_page(html, "milano", contract, 1).cards[0]


def test_regular_apartment_in_scope():
    assert classify(card()) == (True, None, [])


def test_auction_by_title():
    assert classify(card("Appartamento all'asta a Milano via Roma"))[:2] == (False, "auction")


def test_auction_by_title_typographic_apostrophe():
    assert classify(card("Appartamento all’asta a Milano via Roma"))[:2] == (False, "auction")


def test_auction_by_tag():
    assert classify(card(tags=("All'asta/Asta Giudiziaria",)))[:2] == (False, "auction")


def test_whole_building_excluded():
    assert classify(card("Intero Stabile a Milano via Roma"))[:2] == (False, "whole_building")
    assert classify(card("Palazzo a Milano via Roma"))[:2] == (False, "whole_building")


def test_rooms_for_rent_excluded():
    assert classify(card("Stanza a Milano via Roma", contract="affitto"))[:2] == (False, "room")
    assert classify(card("Posto letto a Milano via Roma", contract="affitto"))[:2] == (False, "room")


def test_doubtful_cases_included_and_flagged():
    assert classify(card(tags=("Nuova Costruzione",))) == (True, None, ["new_build"])
    assert classify(card(tags=("Affitto con riscatto",))) == (True, None, ["rent_to_buy"])
    assert classify(card(tags=("A Reddito",))) == (True, None, ["investment"])
