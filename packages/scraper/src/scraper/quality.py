"""Controlli di qualità: quando una raccolta è abbastanza completa da poter registrare scomparse."""

from scraper.config import Settings


def segment_ok(declared_total: int | None, unique_cards: int, failed_pages: int, settings: Settings) -> tuple[bool, str | None]:
    """Un segmento è completo se nessuna pagina è fallita e gli annunci raccolti coprono il totale dichiarato.

    Restituisce (ok, motivo). Solo i segmenti ok possono generare scomparse.
    """
    if declared_total is None:
        return False, "no_declared_total"
    if failed_pages > 0:
        return False, "failed_pages"
    if declared_total < settings.small_segment_threshold:
        ok = declared_total - unique_cards <= settings.small_segment_max_missing
    else:
        ok = unique_cards / declared_total >= settings.completeness_min
    return (True, None) if ok else (False, "incomplete")


def active_drop_alert(prev_active: int, now_active: int, settings: Settings) -> bool:
    """Vero se gli annunci attivi sono calati più della soglia rispetto al run precedente."""
    return prev_active > 0 and (prev_active - now_active) / prev_active > settings.active_drop_alert
