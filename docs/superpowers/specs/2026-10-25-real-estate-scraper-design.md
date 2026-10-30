# Real Estate Scraper — Design document

Date: 2026-10-25 · Status: approved by the user on 2026-10-25

## 1. Why it exists

Collect, every day, the residential real-estate listings (sale and rent) of a set of municipalities so that, in a later phase, we can build:

- a **pricing model**: estimate the price at which an estate agent would list a property for sale or rent, given its characteristics;
- an estimate of the **average time to sell** and a **time-to-sell model** given the characteristics.

Listing history cannot be recovered after the fact: every day without collection is lost for good. **The top priority is to get the daily collection into production as soon as possible**; advanced deduplication, a user interface and new sources come later, on top of the data already accumulated.

A personal, spare-time project, using free tools only.

## 2. Goals, non-goals, anti-goals

**Goals (Phase 1, this document)**
- Automatic daily collection of all residential sale and rent listings (kept separate) in the configured municipalities.
- For each listing, as much data as the detail page provides (photos excluded; for photos we store only their perceptual fingerprints).
- Per-listing history: first appearance, last presence, price changes, disappearance.
- From day one, collect every signal needed to recognize **re-listings** and **duplicates** after the fact (agency reference code, coordinates, photo fingerprints, description).
- Adding a municipality = adding one line of configuration.

**Non-goals (Phase 1)**
- Pricing and time-to-sell models.
- A graphical interface (Phase 3; but the data must already be readable locally with DuckDB).
- The deduplication/re-listing algorithm (Phase 2): in Phase 1 we collect the signals, we do not do the matching.
- Sources other than trovacasa.it (Phase 4).
- Storing the photos.

**Anti-goals (failure even if it "works")**
- **False disappearances**: a network error, a timeout or incomplete pagination recorded as "listing gone". Since *gone = sold*, this corrupts the most important piece of data. It is the number-one risk.
- Silent gaps: the job fails, or collects half the data, and nobody notices.
- Getting blocked by the site.
- Bypassing anti-bot protections (casa.it is excluded for this reason: it is protected by DataDome).
- Exceeding the free tiers of GitHub Actions or Cloudflare R2.

## 3. Decisions taken with the user

| Topic | Decision |
|---|---|
| Initial municipalities | Milano, Busto Arsizio, Gallarate, Monza, Legnano, Gorla Minore, Marnate, Castellanza |
| Contracts | Sale **and** rent, kept separate |
| Property types | Residential only. Excluded: auctions, lots/whole buildings/palazzi, garages, commercial, land |
| Definition of sold | **The listing disappears** from the site. Re-listings (removed and published again as new) must be recognized, even after the fact |
| Pricing target | The asking price in the listing |
| Data depth | The detail page is required. It can be skipped only if the listing was already known and has not changed |
| Speed | Have all the data every day; push as hard as possible without getting blocked |
| Infrastructure | No machine owned by the user. Scraping on **GitHub Actions**, storage on **Cloudflare R2**. Repository created by the user, **public at first** (unlimited minutes) to measure real usage; possibly switched to private later if usage fits within 2,000 min/month |
| Code | Readable and documented. **No obfuscation** (proposed by the user, rejected: it does not reduce any risk and conflicts with the documentation requirement) |
| Documentation | Clear, complete and **always up to date** from the first commit, understandable even when picking the project up again after months (see §12) |
| Repository | A single monorepo for scraper, dashboard, models and documentation (see §11) |
| Historical data | The only history available: a Milano sale snapshot from 2026-10-17 produced by the old scraper (17,304 listings), to be imported (see §6.5) |
| Photos | Not stored; we store perceptual fingerprints (pHash) of several photos per listing |
| Initial source | trovacasa.it. casa.it excluded (DataDome). Agency websites in Phase 4 |
| Old scraper | The user's previous personal repository (a trial scraper on GitHub Actions): a starting point only, not to be copied |

## 4. What we know about the source (reconnaissance on 2026-10-25)

trovacasa.it (owned by Immobiliare.it S.p.A.), IIS/ASP.NET server, no anti-bot protection detected. Permissive robots.txt (it only disallows `?idtags=`, `/similarpartial/`, `/membership/`, `/my/`).

**Volumes**: ~38,000 listings in total.

| Municipality | Sale | Rent |
|---|---|---|
| Milano | 17,433 | 15,746 |
| Monza | 1,533 | 342 |
| Busto Arsizio | 1,006 | 91 |
| Gallarate | 680 | 76 |
| Legnano | 649 | 80 |
| Castellanza | 147 | 33 |
| Gorla Minore | 80 | 2 |
| Marnate | 60 | 4 |

**Search-result pages**: `https://www.trovacasa.it/case-in-{vendita|affitto}/{slug-comune}?page=N`, 24 listings per page, complete pagination up to the last page (beyond the last page: 404). Page 1 has no parameter; `?page=1` answers 301. The page states the total ("17.433 case in vendita a Milano", i.e. "17,433 homes for sale in Milan"), which can be used as a completeness check.

Each listing card (`div.card.js_card_immobile`) contains: ID (`data-id`), `data-eliminato`, detail URL (`/annunci/<prefix>-<id>`), title (property type + "da privato" (private seller) / "all'asta" (at auction) + address), neighborhood, floor area, rooms, price, tags (features), agency logo, and the **full list of photo IDs** (`data-src-list`).

**Detail page** (~86 KB): price, address, floor area, rooms, bathrooms, property type, contract, municipality, energy class, listing code (`TC<id>`), **the agency's internal reference**, the "altre caratteristiche" (other features) list, full description, agency and branch, **latitude/longitude** (in the map script). The floor is not always present: extract it when it is.

**Non-existent/removed listing**: the detail page answers **404**.

**Property types observed**: Appartamento, Loft, Attico, Mansarda, Villa, Villa Bifamiliare, Casa Indipendente, Porzione di Casa, Rustico, Cascina, Intero Stabile, Palazzo; plus "da privato" and "all'asta" variants. Auctions are listed inside the "case" (homes) category (15% in Busto Arsizio). Relevant tags: `All'asta/Asta Giudiziaria` (judicial auction), `Nuova Costruzione` (new build), `Affitto con riscatto` (rent-to-buy), `A Reddito` (sold with a sitting tenant / income-producing).

**Measured speed** (from a home connection, Milano result pages): 1 connection → 2.5 req/s; 4 → 11 req/s; 8 → 20 req/s; 16 → 31 req/s, always 0 errors over 710 requests. At 16 connections latency goes up (0.35 → 0.46 s median): the server starts to struggle. The site produces **intermittent 500 errors** (302 to `/Error/InternalServerError`) that go away on the second attempt.

**Photos**: thumbnails of 70–135 KB; URL `img.trovacasa.it/annunci/mlis/<photo_id>/foto.jpg` (via a redirect from `cdn.`) or `pic.trovacasa.it/image/<id>/m-c.jpg`.

**To be verified on the first run**: behavior from GitHub Actions IPs (the old repo has a "Fix 403" commit that hints at past problems); whether rooms/beds-for-rent appear among Milano rentals.

## 5. Architecture

```
GitHub Actions (daily cron, public repo at first)
  └─ python -m scraper run
       1. download the current state from R2
       2. for each (source, city, contract): read ALL result pages
       3. decide which detail pages to download (new / changed / rotation / disappearance check)
       4. download detail pages + photo fingerprints for new listings
       5. compute events (new, price change, gone, reappeared)
       6. quality checks → if they fail, do NOT record disappearances
       7. write the day's Parquet partitions to R2, then the updated state, then the report
Cloudflare R2 (private bucket)
  └─ Parquet partitioned by date + state + report
Local (user)
  └─ DuckDB reads the Parquet files from R2 (or from a synced copy) → Streamlit in Phase 3
```

**Source abstraction**: each source implements a common interface (result-page URL per municipality/contract, listing-card parsing, detail URL, detail parsing, existence check). trovacasa is the first implementation; agency websites are added as new classes without touching the rest.

**Configuration**: `config/cities.yaml` with the municipality, its ISTAT code, the slug for each source, and the active contracts. Run parameters (concurrency, rotation days, full-detail mode, page limit for tests) come from a file, with overrides from the workflow inputs.

## 6. Daily logic

### 6.1 Search-result pages
- We read **all** the pages of every (municipality, contract), in parallel.
- For each listing card we compute a **card fingerprint** (a hash of price, floor area, rooms, title, tags, photo list).
- Every card seen is saved in the day's observations, including listings that are out of scope (auctions etc.), with an `in_scope` flag and an `exclusion_reason`.
- Completeness: unique listings collected vs. the total declared by the site, per segment (for small segments, below ~50 listings, the threshold is an absolute number instead of a percentage).
- Scope (`in_scope`): we exclude auctions (title "all'asta" or an auction tag), Intero Stabile (whole building), Palazzo, and rooms/beds. Borderline cases (Nuova Costruzione, Affitto con riscatto, A Reddito) are **included and flagged**: wrongly excluding something is irreversible, whereas filtering later is not.

### 6.2 Which detail pages to download (`in_scope` listings only)
1. **New**: an ID never seen before.
2. **Changed**: the card fingerprint differs from the last one.
3. **Rotation**: the detail page is older than N days (default N = 7 → roughly 1/7 of listings per day).
4. **Disappearance check**: listings that were active yesterday and are missing from today's search results (see 6.3).
5. **Full mode** (`full_details=true`): all of them, every day.

### 6.3 Disappearances (the critical part)
We record **separate dates**, because "gone from the search results" and "page removed" do not necessarily coincide (the 404 was verified only on made-up IDs, not on listings that were actually removed):
- `list_last_seen`: the last day the listing appeared in a complete set of search results. **This is the end date used for the time to sell.**
- `delisted_date`: the first day of confirmed absence from the search results.
- `detail_gone_date`: the first day the detail page answers 404 (or shows a "not available" notice, or the card has `data-eliminato=True`).

Rules:
- Missing from today's search results → check the detail page.
  - 404 / not available → `removed` immediately.
  - 200 → probably skipped by pagination (new listings shift the pages while the collection is running): it stays active, but `list_last_seen` is **not** updated. If it stays missing for **2 consecutive complete runs** → state `delisted` (counts as gone for modelling purposes), and the detail page is re-checked weekly until it gives 404.
  - error/timeout after all retries → no decision; retry the next day.
- The cards' `data-eliminato` is always saved; its meaning must be verified in the first few days by comparing it with the 404s.
- We save a sample of the raw detail pages of the first listings that disappear, to see how the site presents a removed listing, and adjust the rules accordingly.
- **Safety lock**: if a segment's completeness is below the threshold (default 97% of the declared total) or its error rate is above the threshold, **no disappearances are recorded** for that segment that day and the run is flagged.
- A `removed` listing that reappears with the same ID → `reappeared` event (the online interval is closed and a new one is opened; nothing is discarded).
- Days without a run: the disappearance date is an interval between `last_seen` and the first day it was observed missing; both are saved.

### 6.4 Photo fingerprints
- For new listings (and when the photo list changes): download the first K photos (default K = 6, configurable) and, for each one, save the **photo ID** and the **64-bit pHash** (plus a dHash). The images themselves are not stored.
- This must be done from the start: once a listing disappears its photos can no longer be downloaded, and without fingerprints the re-listing can no longer be recognized.

### 6.5 Importing the historical data (one-off)
- File: `scraping-data_2026_10_trovacasa_milano_20261017_234300_17304_annunci_completi.csv` (separator `;`), 17,304 Milano sale listings as of 2026-10-17. Fields: `_id` (`TC<id>`), url, price (text, may also be "Prezzo su richiesta" — price on request), title, address, floor area, rooms, bathrooms, energy class (free text), tags. No coordinates, description, agency or photos.
- It is imported as the observation `dt=2026-10-17` with `source_run = legacy` and the missing fields set to null. Its purpose: (a) to know that listings still present on the first run were online at least since 2026-10-17; (b) to record the listings no longer present as gone within the interval (2026-10-17, first run], together with their basic characteristics.
- The file does **not** go into the repository (it is data): it is uploaded to R2 under `legacy/` and ignored by git.
- The old scraper is no longer active and there is no other historical data.

### 6.6 Networking and politeness
- Asynchronous HTTP client with configurable concurrency (default **6** on the site, **8** on the images, which are on a different host); real-browser headers; compression enabled.
- Up to 4 attempts with exponential backoff plus jitter; honour `429`/`Retry-After`; explicitly treat the redirect to `/Error/InternalServerError` as a temporary error.
- Automatic backoff: if the error rate over a sliding window exceeds 20%, concurrency is halved; if it stays high, the run stops cleanly (with no disappearances) and is flagged.

## 7. Data on R2

Parquet format (zstd compression), partitioned by date. Listing key: `(source, listing_id)`.

| Path | Content | Frequency |
|---|---|---|
| `observations/dt=YYYY-MM-DD/` | every card seen that day: key, municipality, contract, position, card fields, fingerprint, `in_scope`, `exclusion_reason` | daily, ~38k rows |
| `details/dt=YYYY-MM-DD/` | detail pages downloaded that day: parsed fields + full description + features + lat/lon + agency + agency reference | downloaded rows only |
| `photos/dt=YYYY-MM-DD/` | key, photo index, photo ID, pHash, dHash | new listings |
| `events/dt=YYYY-MM-DD/` | `new`, `price_change` (old/new), `removed`, `reappeared`, `detail_changed` | daily |
| `raw/dt=YYYY-MM-DD/` | compressed detail HTML (new/changed only), so we can re-parse if the parser had a bug | 90-day retention |
| `state/listings.parquet` | one row per listing: state, first appearance, `last_seen`, first absence, latest fingerprint, latest detail, latest price | overwritten at the end of the run |
| `runs/dt=YYYY-MM-DD/report.json` | metrics: requests, errors, completeness per segment, event counts, duration, outcome of the checks | daily |

Write order: the day's partitions → state → report. Rerunning the same day overwrites that day's partitions (idempotent). The previous state is kept as a dated copy for 30 days (for recovery after a corrupted run).

Personal data: we do not extract people's names or phone numbers/emails as fields. The agency name is kept. The description is stored as-is.

## 8. Running and monitoring

- GitHub Actions workflow with a daily cron (at night, at an odd minute to avoid GitHub's peak load) + manual trigger with parameters (municipalities, `full_details`, page limit, dry-run).
- Workflow `concurrency` to prevent two overlapping runs; 120-minute timeout.
- **Public repository**: workflow logs are public → logs contain only aggregate metrics, never listing data; no data in the repository; Actions secrets are not exposed to forks. GitHub disables cron schedules on public repos after 60 days of inactivity: in that case no failed run shows up at all, so a "freshness" check (latest report on R2 older than 2 days) must be made visible in the dashboard and in the runbook README.
- Secrets: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.
- The run ends with an error (→ automatic email from GitHub) if: it fails, the quality checks do not pass, or the number of listings drops by > 5% compared with the previous day. A readable summary goes in the job summary.
- **Bootstrap**: on the first day all ~38k listings are new. The first run has its timeout extended to 6 hours (GitHub's maximum): search results + detail pages of all in-scope listings (~35–45 min) first, then photo fingerprints. For listings that already existed at bootstrap we use K = 3 photos, in batches over the first few days' runs, starting from the oldest listings (the closest to disappearing); from the second day on, new listings use the full K. Estimated one-off cost ~300–400 minutes.
- **Plan B if GitHub Actions gets blocked** (persistent 403/throttling at the first test): move the same code to a free Google Cloud e2-micro VM (an option already accepted), keeping storage on R2 unchanged. No proxies and no evasion techniques. The code must not depend on GitHub Actions: it must run the same way from any machine that has the R2 environment variables.
- Estimated budget: incremental mode ~20–30 minutes/day (≈ 600–900 min/month out of 2,000 free); full mode ~40–50 minutes/day. Estimated storage ~2–3 GB/year excluding raw (raw is rotated, ≤ 2 GB).

## 9. Stack

Python 3.12, environment managed with `uv`; `httpx` (async) for requests; `selectolax` for parsing; `polars` + `pyarrow` for Parquet; `boto3` for R2 (S3 API); `imagehash` + `Pillow` for fingerprints; `pydantic` for the record schema; `PyYAML` for configuration; `pytest` with saved HTML pages as fixtures. Locally: `duckdb` (reads directly from R2) and, in Phase 3, `streamlit`.

## 10. Later phases (each will get its own document)

- **Phase 2 — Re-listings and duplicates**: a "property" entity that groups listings; candidates = a listing that disappeared + a new listing within ~90 days, same municipality/contract/property type; signals: same agency reference, ≥2 photos with a low pHash distance, floor area within ±5%, coordinates within ~150 m, similar description. Time to sell is measured on the property, from its first appearance to its last disappearance. Applied retroactively to the whole history.
- **Phase 3 — Local interface** (Streamlit + DuckDB): browse listings, filters, price history, maps, statistics by area, time online.
- **Phase 4 — Other sources**: reconnaissance of agency-network websites (Tempocasa, Tecnocasa, Gabetti, Re/Max…); we integrate those with no anti-bot protection and with measured additional coverage.
- **Phase 5 — Models**: pricing (target: the last price before the disappearance, paying attention to listings that stayed online for a long time) and survival analysis for the time to sell; enrichment with OMI price quotations (the Italian Revenue Agency's property market observatory).

## 11. Repository and versioning

**A single monorepo** (one GitHub account). Scraper, dashboard and models share the data schema: keeping them together prevents the schema produced by the scraper and the one read by the dashboard from drifting apart unnoticed. Two repositories on two accounts were considered and rejected: double maintenance, a duplicated schema, and GitHub's Terms of Service allow only one free account per person (only "machine accounts" for automation are allowed in addition).

Layout (`uv` workspace, each component with its own dependencies, so GitHub Actions installs only the scraper):

```
README.md                  overview + quick start
CLAUDE.md                  rules for AI sessions (incl. the duty to keep docs up to date)
CHANGELOG.md               changes per component
pyproject.toml             uv workspace
config/cities.yaml
packages/
  scraper/                 collection (src/ + tests/ with HTML fixtures)
  dashboard/               Phase 3 (Streamlit)
  models/                  Phase 5
docs/                      see §12
.github/workflows/
```

Rules:
- Git with `main` always working; work on short-lived branches; commit messages in Conventional Commits style with a scope (`feat(scraper): …`, `docs: …`).
- SemVer versions **per component** via tags: `scraper-v0.1.0`, `dashboard-v0.1.0`, `models-v0.1.0`.
- **Data versioning**: every Parquet file contains `schema_version` and `scraper_version` (tag + commit). Every schema change increments `schema_version` and is described in the data dictionary, so that old data remains interpretable.
- Data, credentials and local files (historical CSV, `.docx`) are excluded via `.gitignore`.

## 12. Documentation

User requirement: clear, complete, always up to date, and useful even when picking the project up again after months. Every code change that alters behavior, data or how the project runs updates the documentation **in the same commit**; the rule is written in `CLAUDE.md`.

```
docs/
  README.md               index: where to start
  overview.md             what the project is, why, current status, phases
  architecture.md         components, daily flow, block diagram
  data-dictionary.md      every file/column: meaning, type, origin, examples, schema history
  disappearance-logic.md  how new/changed/gone/reappeared is decided, thresholds, edge cases
  sources/trovacasa.md    site structure, selectors, URLs, measured limits, known anomalies
  runbook.md              run, rerun a day, restore the state, add a municipality, rotate the R2 keys
  decisions/NNNN-*.md     decision log (context, decision, alternatives considered)
  superpowers/            specs and work plans
```

## 13. Left to the implementer

- Internal package structure, module and function names.
- The exact list of parsed fields beyond those mentioned (take everything the page exposes in a structured way).
- Final concurrency values and thresholds, to be tuned after the first runs on GitHub Actions (starting from the defaults above).
- The exact cron time.
- How to represent tags/features (a list or boolean columns), as long as no information is lost.
