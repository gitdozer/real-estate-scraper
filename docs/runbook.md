# Runbook — how to use it and what to do when something goes wrong

Run every command from the repository root.

## Initial setup (once)

### 1. Cloudflare R2

1. In the Cloudflare dashboard: **R2 Object Storage** → enable R2 (you may be asked for a payment method; the free tier includes 10 GB).
2. **Create bucket**, e.g. `real-estate-data`, with automatic location. Keep it **private** (no public access).
3. **Manage R2 API Tokens** → **Create API token**: permission **Object Read & Write**, restricted to **that bucket only**. Write down the *Access Key ID*, the *Secret Access Key* and the *Account ID* (shown on the R2 page).
4. Optional but recommended: set a billing alert at €1.

### 2. GitHub

1. Create the repository (public, see [decisions/0003](decisions/0003-github-actions-r2.md)) and push the `main` branch.
2. **Settings → Secrets and variables → Actions → New repository secret**, four secrets:
   `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.
3. The workflows live in `.github/workflows/`: `Test` (on every push) and `Raccolta giornaliera` (the daily collection: every night at 02:17 UTC, plus manual trigger from **Actions → Raccolta giornaliera → Run workflow**).

### 3. First start (bootstrap)

In this order:

1. **Import the historical data** from your machine to R2 (see "Importing the historical data" below), with the 4 `R2_*` variables set in the terminal.
2. **Test from GitHub on two small municipalities**: Run workflow with `cities = gorla-minore,marnate`. Check in the summary that the segments are complete and that there are no errors. The summary includes a **Codici HTTP** (HTTP status codes) line: **if it shows 403 (or 401/451), or the `circuit_open` warning appears**, trovacasa is blocking GitHub's IPs: stop and switch to plan B (at the end of this page).
3. **Full bootstrap**, to be started **during the day** (not between midnight and 04:00, because the nightly cron would also start and would be treated as a rerun of the same day): Run workflow with the default `max_runtime_minutes = 330` and the other fields empty (the job has a 350-minute limit: the margin covers installation and writing). At 0.5 requests/s it takes ~3 days of runs to download the detail pages of all listings (the queue carries over from one day to the next), then the first photo fingerprints (roughly 1–2 hours). Missing fingerprints are filled in over the following days.
4. Check the summary and `uv run python -m scraper status --storage r2`.
5. From now on the cron runs by itself every night. Record the duration, errors and minutes consumed by the first runs in `docs/sources/trovacasa.md`.

## Running the collection

```bash
uv sync --package scraper                      # once, or after a dependency update
uv run python -m scraper run [options]
```

| Option | Effect |
|---|---|
| `--storage local` / `--storage r2` | where data is read from and written to. `local` (the default) uses the `--local-root` folder (default `data/`, excluded from git); `r2` uses the environment variables `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` |
| `--cities gorla-minore,marnate` | only these municipalities (slugs from `config/cities.yaml`); default: all |
| `--date 2026-10-26` | date of the run (default: today, Europe/Rome time zone) |
| `--full-details` | downloads the detail page of every listing, not just new / changed / rotation ones |
| `--max-pages N` | only the first N pages per segment — **for testing only**: it blocks the recording of disappearances and makes the run exit with an error |
| `--max-runtime-minutes M` | maximum duration (default 100). Past 85% no more detail pages are downloaded, past 90% no more photos: the remaining work is carried over to the next day |
| `--dry-run` | runs everything but writes nothing |

The command exits with **code 1** (and GitHub sends the failure email) if a segment is incomplete, if active listings drop by more than 5%, or if the site returns too many errors (circuit breaker open). The collected data is written anyway.

Quick local test (2 small municipalities, ~20 seconds):

```bash
uv run python -m scraper run --cities gorla-minore,marnate --storage local --local-root data
```

## Importing the historical data (once only, before the first run)

```bash
uv run python -m scraper import-legacy docs/scraping-data_2026_10_trovacasa_milano_20261017_234300_17304_annunci_completi.csv --storage r2
```

It refuses to start if the state already exists (`--force` overrides this: it overwrites the state, so use it only on an empty bucket). The CSV is not in the repository: it lives in the local `docs/` folder and is copied to R2 under `legacy/`.

## Checking that the collection is up to date

```bash
uv run python -m scraper status --storage r2 [--max-age-days 2]
```

It prints the date and outcome of the last run, and exits with code 1 if that run is older than `--max-age-days` days. **Run it every now and then**: GitHub disables scheduled workflows in a public repository after 60 days without commits, and when that happens no email is sent.

## Rerunning a day

You can rerun **only the most recent collected day**: just launch `run` again (with the same `--date`, if it is not today). For the municipalities being collected, the run restarts from the state as it was **before** that day — from the copy in `state/history/dt=<date>/`, which is the first thing every run writes, so this works even if the previous run was interrupted halfway. It overwrites that day's partitions for those municipalities and leaves the other municipalities' partitions untouched. This means you can also rerun a single municipality (`--cities`).

A date **earlier than the last run is rejected** (exit code 2): it would roll the state back. A skipped day stays skipped; disappearance dates account for it (the interval between `list_last_seen` and `delisted_date`). `--dry-run` is always allowed.

## Restoring the state

If a run produced a wrong state (e.g. because of a bug), the state as it was before each run is kept for 30 days in `state/history/dt=YYYY-MM-DD/listings.parquet`:

1. copy `state/history/dt=<day of the bad run>/listings.parquet` over `state/listings.parquet`. The registry `state/segments.parquet` has no copies: if the bad run altered it (first complete collection, suspicious drops), fix it by hand or delete it (it gets rebuilt, but the segments then count as "new" again for 7 days for censoring purposes);
2. to redo that day from scratch: delete `state/history/dt=<day>/`, `runs/dt=<day>/` and that day's partitions (`observations/`, `details/`, `photos/`, `events/`, `raw/` with `dt=<day>`);
3. launch the run again for that day (it must be the most recent collected day).

## Adding a municipality

1. Find the municipality's slug on trovacasa.it: it is the last part of the URL `https://www.trovacasa.it/case-in-vendita/<slug>`.
2. Find its ISTAT code (6 digits).
3. Add a line to `config/cities.yaml`, update `docs/overview.md` and commit.

During the first 7 days of a new municipality its listings are flagged `first_seen_censored` (they were probably already online).

## What to do when a failure email arrives

Open the run on GitHub Actions: the summary shows which check failed.

| Warning | Meaning | What to do |
|---|---|---|
| `segments_not_ok` with `failed_pages` | some result pages could not be downloaded even after retries | usually a temporary problem on the site: rerun (even just for those municipalities). No disappearances were recorded for those municipalities |
| `segments_not_ok` with `incomplete` | fewer than 97% of the declared listings were collected | check whether the site changed its pagination; rerun |
| `segments_not_ok` with `suspicious_drop` | the number of listings seen dropped sharply compared with the previous day | possibly an outage or a site change: check the site by hand. If the drop is real there is nothing to do: after 3 consecutive runs it is accepted automatically |
| `drop_confirmed` | a drop repeated over 3 runs has been accepted as real and the disappearances have been recorded | check that the number of listings on the site really did go down |
| `segments_not_ok` with `no_declared_total` | page 1 does not show the total | the site has probably changed its structure: update the parser (`sources/trovacasa.py`) and the fixtures |
| `active_drop` | active listings dropped by more than 5% | check on the site whether the drop is real |
| `circuit_open` | too many errors even at concurrency 1 (including 401/403/451): the site is struggling or is blocking us | look at the "Codici HTTP elenchi/dettagli" (HTTP status codes) lines in the summary; if it keeps happening for days (persistent 403s), switch to **plan B** (below) |
| `details_errors` | many detail pages not downloaded or not recognized (more than 20 and more than 10%) | probably a change in the site's structure or an anti-bot check page: open a listing by hand, then update the parser and the fixtures |

The full report, with samples of the errors, is on R2 at `runs/dt=YYYY-MM-DD/report.json`.

**Unexpected error** ("Errore imprevisto: <tipo>" — "Unexpected error: <type>" — in the log): the public log shows only the error type, because the message text could contain listing data. The full details (traceback) are on R2 at `runs/crash/<date-time>.txt`. The data collected up to that point is not written: rerun once you understand the cause.

**Run rejected** (exit code 2): the date is earlier than the last run; see "Rerunning a day".

**"Configurazione: Variabili d'ambiente mancanti per R2: …"** ("Configuration: missing environment variables for R2: …"): one or more secrets are not set or have a different name; check Settings → Secrets and variables → Actions.

## Diagnosing the request rate the site accepts

If the heartbeat in the collection logs shows many `ReadTimeout`s (hanging requests), the site is slowing us down: the `list_rate_per_s` (search results) or `detail_rate_per_s` (detail pages) pace is too high for GitHub's IP — the heartbeat runs during the search-results phase, and the summary has separate "Richieste elenchi" and "Richieste dettagli" lines. To measure a sustainable rate: **Actions → Diagnosi ritmo → Run workflow**, with phases given as `requests_per_second:minutes` (default `0.5:45`). It uses no credentials and writes no data; it requests each search-results page **only once** (a repeated page may come from the site's cache and would not show the limit), logs cumulative counts every minute, and for each phase the summary reports requests, responses, timeouts and latency. To probe **detail pages** instead of search results, set `kind = detail` (and `concurrency`, the connections sharing the rate): the probe first reads 300 sale search-result pages at 0.5 requests/s (~10 minutes) to collect ~7,000 distinct detail URLs, then requests them at the given rate. Locally: `uv run python -m scraper probe --phases "1:2,2:2"`, or `--kind detail --harvest-pages 2 --phases "1:0.5"` for a quick check. `first_page` (list kind) starts from a given search-result page, to reach the end of the results quickly.

## Plan B: if GitHub Actions gets blocked

The same command runs on any machine: create a free Google Cloud e2-micro VM (1 GB of RAM: the run processes detail pages in batches of 500 and stays in the hundreds of MB), install `uv`, clone the repository, set the 4 `R2_*` variables and schedule `uv run python -m scraper run --storage r2` with cron every night. Storage on R2 stays the same. See [decisions/0003](decisions/0003-github-actions-r2.md).
