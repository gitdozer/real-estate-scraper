from datetime import date
from pathlib import Path

import httpx
import pytest
from fakesite import FakeSite

from scraper.config import City, Settings
from scraper.legacy import LEGACY_DATE, import_legacy
from scraper.pipeline import RunOptions, load_state, run_daily
from scraper.storage import LocalStorage, partition_key, read_parquet

CSV = Path(__file__).parent / "fixtures" / "legacy_sample.csv"
MILANO = City(name="Milano", istat="015146", slugs={"trovacasa": "milano"}, contracts=["vendita"])


def test_import_legacy_parses_and_seeds_state(tmp_path):
    s = LocalStorage(tmp_path)
    assert import_legacy(CSV, s) == 5
    legacy = read_parquet(s, "legacy/trovacasa_milano_2026-10-17.parquet").sort("listing_id")
    assert legacy["price_eur"].to_list() == [219000, None, 150000, 1450000, 320000]
    assert legacy["rooms"].to_list() == [2, 6, None, 5, 3] and legacy["bathrooms"].to_list()[0] == 1
    assert legacy["surface_m2"].to_list()[1] == 1200.0
    assert legacy["property_type"].to_list() == ["Appartamento", "Villa a Schiera", "Appartamento", "Attico", "Appartamento"]
    assert legacy["energy_class"].to_list()[1] == "D" and legacy["energy_kwh_m2_year"].to_list()[1] == 69.98
    assert legacy["tags"].to_list()[0] == ["Arredato", "Ascensore"]
    assert legacy["advertiser_id"].to_list()[3] == "901"

    obs = read_parquet(s, partition_key("observations", LEGACY_DATE))
    assert len(obs) == 5 and obs["source_run"].unique().to_list() == ["legacy"]
    assert obs.filter(obs["listing_id"] == "3")["exclusion_reason"].to_list() == ["auction"]
    assert obs.filter(obs["listing_id"] == "4")["is_private"].to_list() == [True]

    state = load_state(s)
    st = state[("trovacasa", "1")]
    assert len(state) == 5 and st.status == "active" and st.first_seen_censored
    assert st.first_seen == st.spell_start == st.list_last_seen == date(2026, 10, 17)
    assert st.last_price == 219000 and st.last_fingerprint is None and st.last_detail_date is None
    assert s.read_bytes(f"legacy/{CSV.name}") == CSV.read_bytes()


def test_import_legacy_refuses_existing_state(tmp_path):
    s = LocalStorage(tmp_path)
    import_legacy(CSV, s)
    with pytest.raises(RuntimeError):
        import_legacy(CSV, s)
    assert import_legacy(CSV, s, force=True) == 5


async def test_first_live_run_after_legacy(tmp_path):
    s = LocalStorage(tmp_path)
    import_legacy(CSV, s)
    site = FakeSite()
    site.listings[("milano", "vendita")] = ["1", "4", "5", "77"]  # 2 e 3 spariti (404), 77 nuovo
    site.prices.update({"1": "209.000 &#x20AC;", "4": "1.450.000 &#x20AC;", "5": "320.000 &#x20AC;"})
    day = date(2026, 10, 26)
    await run_daily(s, [MILANO], Settings(max_retries=1), RunOptions(run_date=day), transport=httpx.MockTransport(site.handler))
    ev = read_parquet(s, partition_key("events", day))
    by_type = {}
    for lid, t in zip(ev["listing_id"], ev["type"]):
        by_type.setdefault(t, set()).add(lid)
    assert by_type["removed"] == {"2", "3"} and by_type["new"] == {"77"} and by_type["price_change"] == {"1"}
    state = load_state(s)
    assert state[("trovacasa", "2")].list_last_seen == date(2026, 10, 17)
    assert state[("trovacasa", "77")].first_seen_censored is True  # primo run completo del segmento
    assert all(state[("trovacasa", k)].last_detail_date == day for k in ("1", "4", "5", "77"))


def test_import_legacy_refuses_after_live_runs_even_with_force(tmp_path):
    s = LocalStorage(tmp_path)
    import_legacy(CSV, s)
    s.write_bytes("runs/dt=2026-10-26/report.json", b"{}")
    with pytest.raises(RuntimeError):
        import_legacy(CSV, s, force=True)
