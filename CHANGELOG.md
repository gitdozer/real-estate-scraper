# Changelog

Modifiche per componente. Versioni [SemVer](https://semver.org/lang/it/), tag `<componente>-vX.Y.Z`.

## scraper

### 0.1.0 — 2026-10-25
- Raccolta giornaliera da trovacasa.it: elenchi, dettagli, impronte foto, stato ed eventi, controlli di qualità, CLI `run`/`status`/`import-legacy`; import dello storico Milano del 2026-10-17.
- Workflow GitHub Actions: test a ogni push, raccolta giornaliera (02:17 UTC) e avvio manuale.
- Struttura del monorepo, configurazione dei comuni (`config/cities.yaml`) e dei parametri (`config/settings.yaml`).
