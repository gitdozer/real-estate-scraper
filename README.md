# Real Estate — raccolta annunci immobiliari

Progetto personale per raccogliere ogni giorno gli annunci immobiliari residenziali (vendita e affitto) di alcuni comuni lombardi e costruire, più avanti, un modello di stima del prezzo e del tempo di vendita.

**Stato:** fase 1 pronta per la messa in produzione — raccolta giornaliera da trovacasa.it su GitHub Actions, dati su Cloudflare R2. Configurazione e primo avvio: [`docs/runbook.md`](docs/runbook.md).

| Componente | Cartella | Stato |
|---|---|---|
| Scraper (raccolta giornaliera) | [`packages/scraper`](packages/scraper) | 0.1.0 |
| Dashboard locale (Streamlit) | `packages/dashboard` | fase 3 |
| Modelli (prezzo, tempo di vendita) | `packages/models` | fase 5 |

## Da dove partire

- **Documentazione:** [`docs/README.md`](docs/README.md) — indice di tutto.
- **Perché e come:** [`docs/panoramica.md`](docs/panoramica.md).
- **Decisioni prese e alternative scartate:** [`docs/decisioni/`](docs/decisioni).

## Avvio rapido (sviluppo)

Serve [uv](https://docs.astral.sh/uv/).

```bash
uv sync --package scraper     # crea l'ambiente con Python 3.12 e le dipendenze
uv run pytest                 # esegue tutti i test
```

Prova reale veloce su due comuni piccoli, con i dati in `data/` (esclusa da git):

```bash
uv run python -m scraper run --cities gorla-minore,marnate --storage local --local-root data
```

I dati raccolti **non** stanno nel repository: vivono su Cloudflare R2 (vedi `docs/runbook.md`).
