"""Human-readable run summary for the GitHub job summary.

The repository is public: ONLY aggregate numbers go here. No URLs, listing IDs
or error samples (those stay in the full report on R2).
"""


def _counts(d: dict) -> str:
    return ", ".join(f"{k}: {v}" for k, v in sorted(d.items())) or "—"


def summary_markdown(report: dict) -> str:
    esito = "✅ OK" if report["exit_code"] == 0 else "❌ Needs checking"
    lines = [
        f"## Collection of {report['run_date']} — {esito}",
        "",
        f"Duration: {report['duration_s'] / 60:.1f} min · version `{report['scraper_version']}`"
        + (" · **rerun**" if report.get("rerun") else "")
        + (" · **dry-run**" if report.get("dry_run") else ""),
        "",
        "| City | Contract | Declared | Collected | Active before | Pages | Failed pages | Complete |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for s in report["segments"]:
        ok = "yes" if s["ok"] else f"no ({s['reason']})"
        lines.append(
            f"| {s['city']} | {s['contract']} | {s['declared']} | {s['unique']} | {s['prev_active']} | {s['pages']} | {s['failed_pages']} | {ok} |"
        )
    d, p = report["details"], report["photos"]
    lines += [
        "",
        f"**Events:** {_counts(report['events'])}",
        "",
        f"**Active listings:** {report['active']['prev']} → {report['active']['now']}",
        "",
        f"**Detail pages planned:** {_counts(d.get('planned', {}))} · downloaded {d.get('done', 0)}"
        f" · 404 {d.get('gone', 0)} · errors {d.get('errors', 0)} · past the deadline {d.get('skipped_deadline', 0)}",
        "",
        f"**Photos:** planned {p.get('planned', 0)} · fingerprints {p.get('done', 0)} · failed {p.get('failed', 0)}"
        f" · past the deadline {p.get('skipped_deadline', 0)}",
    ]
    # "site" = reports written before 0.1.4, when lists and details shared one client
    for key, label in (("lists", "search results"), ("details", "detail pages"), ("site", "the site")):
        stats = report.get("fetch", {}).get(key)
        if stats:
            lines += ["", f"**Requests to {label}:** {stats['requests']} · retried {stats['retries']} · failed {stats['failures']} · final concurrency {stats['concurrency_now']}"]
            lines += ["", f"**HTTP status codes ({label}):** {_counts(stats.get('by_status', {}))}"]  # e.g. 403 = the site is blocking us
    if report["alerts"]:
        lines += ["", f"**⚠️ Warnings:** {', '.join(report['alerts'])} — see docs/runbook.md"]
    return "\n".join(lines) + "\n"
