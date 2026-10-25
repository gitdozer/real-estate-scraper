# 0004 — Monorepo unico

Data: 2026-10-25 · Stato: accettata

## Contesto
Il progetto avrà scraper, dashboard, modelli e documentazione. È stata valutata l'idea di versionare il progetto in un repository e far girare lo scraper in un altro, anche su un secondo account GitHub.

## Decisione
**Un solo repository** su un solo account, workspace `uv` con un pacchetto per componente in `packages/` (`scraper`, `dashboard`, `models`), ognuno con le proprie dipendenze (GitHub Actions installa solo lo scraper).

Versionamento:
- branch `main` sempre funzionante, branch brevi per il lavoro;
- commit Conventional Commits con ambito;
- versioni SemVer **per componente** con tag `scraper-vX.Y.Z`, `dashboard-vX.Y.Z`, `models-vX.Y.Z`; `CHANGELOG.md` per componente;
- **versione dentro i dati**: ogni Parquet ha `schema_version` e `scraper_version` (versione + commit).

## Alternative scartate
- **Due repository / due account**: lo schema dei dati scritto dallo scraper e quello letto da dashboard e modelli divergerebbero senza accorgersene; manutenzione doppia; i Termini di GitHub ammettono un solo account gratuito per persona (oltre ai "machine account" per l'automazione).

## Conseguenze
- Se in futuro serve che il codice sia privato, si rende privato l'intero repository (verificando i minuti consumati).
