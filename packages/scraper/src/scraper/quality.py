"""Controlli di qualità: quando una raccolta è abbastanza completa da poter registrare scomparse."""

from scraper.config import Settings


def segment_ok(
    declared_total: int | None,
    unique_cards: int,
    failed_pages: int,
    settings: Settings,
    prev_active: int = 0,
    drop_runs: int = 0,
) -> tuple[bool, str | None]:
    """Un segmento è completo se nessuna pagina è fallita e gli annunci raccolti coprono il totale dichiarato.

    `prev_active` = annunci attivi del segmento prima del run. Se oggi ne vediamo molti meno,
    il totale dichiarato dal sito potrebbe essere sbagliato (stessa pagina, stesso guasto):
    il segmento non è affidabile (`suspicious_drop`). Se però il calo si ripete per
    `drop_confirm_runs` run consecutivi (`drop_runs` = run precedenti già in calo), lo si
    considera reale (`drop_confirmed`) e le scomparse vengono registrate.
    Restituisce (ok, motivo). Solo i segmenti ok possono generare scomparse.
    """
    if failed_pages > 0:
        return False, "failed_pages"
    if declared_total is None:
        return False, "no_declared_total"
    reason = None
    allowed_drop = max(settings.small_segment_max_missing, settings.active_drop_alert * prev_active)
    if prev_active - unique_cards > allowed_drop:
        if drop_runs + 1 < settings.drop_confirm_runs:
            return False, "suspicious_drop"
        reason = "drop_confirmed"
    if declared_total < settings.small_segment_threshold:
        ok = declared_total - unique_cards <= settings.small_segment_max_missing
    else:
        ok = unique_cards / declared_total >= settings.completeness_min
    return (True, reason) if ok else (False, "incomplete")


def active_drop_alert(prev_active: int, now_active: int, settings: Settings) -> bool:
    """Vero se gli annunci attivi sono calati più della soglia rispetto al run precedente."""
    return prev_active > 0 and (prev_active - now_active) / prev_active > settings.active_drop_alert
