from pathlib import Path

import pytest
from pydantic import ValidationError

from scraper.config import load_cities, load_settings

REPO = Path(__file__).resolve().parents[3]


def test_load_cities_reads_all_eight():
    cities = load_cities(REPO / "config/cities.yaml")
    assert len(cities) == 8
    assert cities[0].slugs["trovacasa"] == "milano" and cities[0].istat == "015146"
    assert all(c.contracts == ["vendita", "affitto"] for c in cities)


def test_load_cities_rejects_unknown_contract(tmp_path):
    bad = tmp_path / "cities.yaml"
    bad.write_text(
        "cities:\n  - {name: X, istat: '000001', slugs: {trovacasa: x}, contracts: [asta]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_cities(bad)


def test_settings_overrides_win():
    s = load_settings(REPO / "config/settings.yaml", {"full_details": True, "max_pages": 2})
    assert s.full_details is True and s.max_pages == 2 and s.rotation_days == 7


def test_settings_file_matches_defaults():
    s = load_settings(REPO / "config/settings.yaml", {})
    assert s.site_concurrency == 6 and s.image_concurrency == 8 and s.max_retries == 4
    assert s.completeness_min == 0.97 and s.photos_new == 6 and s.photos_backlog == 3


def test_settings_ignores_none_overrides():
    s = load_settings(REPO / "config/settings.yaml", {"max_pages": None})
    assert s.max_pages == 0
