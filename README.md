# Real Estate — raccolta annunci immobiliari

Progetto personale per raccogliere ogni giorno gli annunci immobiliari residenziali (vendita e affitto) di alcuni comuni lombardi e costruire, più avanti, un modello di stima del prezzo e del tempo di vendita.

**Stato:** fase 1 in sviluppo — raccolta giornaliera da trovacasa.it.

| Componente | Cartella | Stato |
|---|---|---|
| Scraper (raccolta giornaliera) | [`packages/scraper`](packages/scraper) | in sviluppo |
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

I dati raccolti **non** stanno nel repository: vivono su Cloudflare R2 (vedi `docs/runbook.md`).
