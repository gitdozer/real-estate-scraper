from conftest import fx

from scraper.fingerprint import detail_hash
from scraper.sources.trovacasa import parse_detail_page


def test_parse_detail_73623446():
    d = parse_detail_page(fx("detail_73623446.html"), "73623446")
    assert d.source == "trovacasa" and d.listing_id == "73623446"
    assert d.title == "Appartamento in vendita a Milano milano Costantino Baroni,216"
    assert d.price_eur == 235000 and d.price_on_request is False
    assert d.surface_m2 == 105.0 and d.rooms == 4 and d.bathrooms == 2
    assert d.listing_code == "TC73623446" and d.agency_reference == "A.C. - BARONIVRG"
    assert d.property_type == "Appartamento" and d.contract_label == "Vendita" and d.municipality == "Milano"
    assert d.address == "Milano Costantino Baroni,216"
    assert d.energy_class == "non disponibile" and d.energy_kwh_m2_year is None and d.floor is None
    assert d.agency_name == "Rozzano" and d.agency_id == "1035"
    assert d.agency_address.startswith("Via Dei Gerani 15-17")
    assert abs(d.latitude - 45.4030377) < 1e-6 and abs(d.longitude - 9.1697216) < 1e-6
    assert len(d.features) == 12 and "Ascensore" in d.features
    assert d.description.startswith("In stabile di recente ristrutturazione")
    assert d.attributes["Tipologia"] == "Appartamento" and "Altre caratteristiche" not in d.attributes


def test_parse_detail_private_rent_with_energy_class():
    d = parse_detail_page(fx("detail_73816329.html"), "73816329")
    assert d.contract_label == "Affitto" and d.price_eur == 850 and d.surface_m2 == 38.0 and d.rooms == 1
    assert d.energy_class == "C" and d.energy_kwh_m2_year == 134.0
    assert d.agency_name == "Privato" and d.agency_id is None
    assert d.agency_reference == "133692952" and len(d.features) == 9
    assert abs(d.latitude - 45.4995) < 1e-6


def test_parse_detail_missing_blocks_returns_nones():
    minimal = (
        "<html><body><h1 class='immobile__title headingOne'>Titolo</h1>"
        "<dl class='row'><dt class='term'>Codice annuncio:</dt><dd class='description'>TC1</dd></dl></body></html>"
    )
    d = parse_detail_page(minimal, "1")
    assert d.title == "Titolo"
    assert d.price_eur is None and d.latitude is None and d.agency_name is None
    assert d.features == [] and d.attributes == {"Codice annuncio": "TC1"} and d.description is None


def test_detail_hash_changes_with_description():
    a = parse_detail_page(fx("detail_73623446.html"), "73623446")
    b = a.model_copy(update={"description": a.description + " Modificato."})
    assert detail_hash(a) != detail_hash(b) and len(detail_hash(a)) == 16
    assert detail_hash(a) == detail_hash(a.model_copy())
