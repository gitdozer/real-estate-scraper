# Regole per le sessioni AI su questo repository

Leggere prima: `docs/README.md`, poi la spec `docs/superpowers/specs/2026-10-25-real-estate-scraper-design.md` e il piano in `docs/superpowers/plans/`.

## Obbligatorie

1. **Documentazione sempre aggiornata.** Ogni modifica che cambia comportamento, dati raccolti, schema o modo di esecuzione aggiorna la documentazione in `docs/` **nello stesso commit**. Ogni colonna nuova o modificata va in `docs/dizionario-dati.md`; ogni modifica di schema incrementa `SCHEMA_VERSION` e si annota nella storia dello schema. Ogni decisione non banale diventa una scheda in `docs/decisioni/`.
2. **Mai dati degli annunci nei log o nel job summary di GitHub** (il repository è pubblico): solo conteggi aggregati. Il dettaglio degli errori va nel report su R2.
3. **Nessun dato nel repository**, tranne le fixture HTML dei test. CSV, Parquet, `.docx`, credenziali restano fuori (`.gitignore`).
4. **Nessun offuscamento** del codice; codice leggibile e commentato dove la logica non è ovvia.
5. **Mai aggirare protezioni anti-bot** (proxy, rotazione IP, risoluzione captcha). Se una fonte blocca, la si scarta.
6. **Scomparse false = il rischio numero uno.** Qualsiasi modifica a `state.py`, `planner.py`, `quality.py` o alla pipeline deve avere test che dimostrano che errori di rete, pagine mancanti o run parziali non producono eventi `removed`/`delisted`.

## Convenzioni

- Codice e identificatori in inglese; documentazione, commenti di dominio e messaggi all'utente in italiano.
- Test prima del codice (pytest). Comando: `uv run pytest`.
- Commit Conventional Commits con ambito: `feat(scraper): …`, `fix(scraper): …`, `docs: …`, `ci: …`.
- Versioni per componente con tag `scraper-vX.Y.Z`, `dashboard-vX.Y.Z`, `models-vX.Y.Z`; annotarle in `CHANGELOG.md`.
