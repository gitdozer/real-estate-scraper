"""I log di avanzamento dicono in che fase si trova il run, senza dati degli annunci."""

import logging

from test_pipeline import D1, run, site, storage  # noqa: F401 (fixture)


async def test_progress_logs_cover_every_phase_without_listing_data(site, storage, caplog):
    caplog.set_level(logging.INFO, logger="scraper")
    await run(site, storage, D1)
    text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("scraper"))
    for phase in ("avvio", "elenchi", "dettagli", "foto", "scrittura"):
        assert f"[{phase}]" in text, phase
    assert "http" not in text and "trovacasa.it" not in text
