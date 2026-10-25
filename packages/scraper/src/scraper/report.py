"""Riepilogo leggibile del run per il job summary di GitHub.

Il repository è pubblico: qui vanno SOLO numeri aggregati. Niente URL, ID di annunci
o campioni di errori (quelli restano nel report completo su R2).
"""


def _counts(d: dict) -> str:
    return ", ".join(f"{k}: {v}" for k, v in sorted(d.items())) or "—"


def summary_markdown(report: dict) -> str:
    esito = "✅ OK" if report["exit_code"] == 0 else "❌ Da controllare"
    lines = [
        f"## Raccolta del {report['run_date']} — {esito}",
        "",
        f"Durata: {report['duration_s'] / 60:.1f} min · versione `{report['scraper_version']}`"
        + (" · **rerun**" if report.get("rerun") else "")
        + (" · **dry-run**" if report.get("dry_run") else ""),
        "",
        "| Comune | Contratto | Dichiarati | Raccolti | Attivi prima | Pagine | Pagine fallite | Completo |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for s in report["segments"]:
        ok = "sì" if s["ok"] else f"no ({s['reason']})"
        lines.append(
            f"| {s['city']} | {s['contract']} | {s['declared']} | {s['unique']} | {s['prev_active']} | {s['pages']} | {s['failed_pages']} | {ok} |"
        )
    d, p = report["details"], report["photos"]
    lines += [
        "",
        f"**Eventi:** {_counts(report['events'])}",
        "",
        f"**Annunci attivi:** {report['active']['prev']} → {report['active']['now']}",
        "",
        f"**Dettagli pianificati:** {_counts(d.get('planned', {}))} · scaricati {d.get('done', 0)}"
        f" · 404 {d.get('gone', 0)} · errori {d.get('errors', 0)} · oltre la scadenza {d.get('skipped_deadline', 0)}",
        "",
        f"**Foto:** pianificate {p.get('planned', 0)} · impronte {p.get('done', 0)} · fallite {p.get('failed', 0)}"
        f" · oltre la scadenza {p.get('skipped_deadline', 0)}",
    ]
    site = report.get("fetch", {}).get("site")
    if site:
        lines += ["", f"**Richieste al sito:** {site['requests']} · ritentate {site['retries']} · fallite {site['failures']} · concorrenza finale {site['concurrency_now']}"]
    if report["alerts"]:
        lines += ["", f"**⚠️ Avvisi:** {', '.join(report['alerts'])} — vedi docs/runbook.md"]
    return "\n".join(lines) + "\n"
