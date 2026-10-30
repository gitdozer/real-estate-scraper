# Real Estate — collecting property listings

A personal project that collects, every day, the residential property listings (sale and rent) of a few municipalities in Lombardy, in order to build — later on — a model that estimates price and time to sell.

**Status:** Phase 1 ready for production rollout — daily collection from trovacasa.it on GitHub Actions, data on Cloudflare R2. Setup and first start: [`docs/runbook.md`](docs/runbook.md).

| Component | Folder | Status |
|---|---|---|
| Scraper (daily collection) | [`packages/scraper`](packages/scraper) | 0.1.0 |
| Local dashboard (Streamlit) | `packages/dashboard` | Phase 3 |
| Models (price, time to sell) | `packages/models` | Phase 5 |

## Where to start

- **Documentation:** [`docs/README.md`](docs/README.md) — index of everything.
- **Why and how:** [`docs/overview.md`](docs/overview.md).
- **Decisions taken and alternatives considered:** [`docs/decisions/`](docs/decisions).

## Quick start (development)

You need [uv](https://docs.astral.sh/uv/).

```bash
uv sync --package scraper     # creates the environment with Python 3.12 and the dependencies
uv run pytest                 # runs all the tests
```

A quick real-world test on two small municipalities, with data written to `data/` (excluded from git):

```bash
uv run python -m scraper run --cities gorla-minore,marnate --storage local --local-root data
```

The collected data is **not** stored in the repository: it lives on Cloudflare R2 (see `docs/runbook.md`).
