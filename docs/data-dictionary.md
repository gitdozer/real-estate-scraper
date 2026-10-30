# Data dictionary

All data lives on Cloudflare R2 as Parquet files (zstd compression), partitioned by collection date (`dt=YYYY-MM-DD`). You can query them directly with DuckDB.

## Common conventions

- **Listing key:** `(source, listing_id)`. `source` is the source website (currently only `trovacasa`); `listing_id` is the listing's ID on that source, stored as a string.
- **Segment:** `(source, city, contract)`, e.g. `(trovacasa, milano, vendita)`. Sale (`vendita`) and rent (`affitto`) listings are never mixed.
- `city` is the municipality **slug** used by the source (see `config/cities.yaml`).
- `run_date` is the collection date in the `Europe/Rome` time zone.
- Every file has two version columns:
  - `schema_version` — the schema version (an integer). Every column change increments it and is described at the end of this document, under [Schema history](#schema-history).
  - `scraper_version` — the version of the code that produced the data, e.g. `0.1.0+abc1234` (version + commit) or `0.1.0+local`.

## File layout (R2 bucket, or a local folder during development)

| Path | Contents | When it is written |
|---|---|---|
| `observations/dt=YYYY-MM-DD/part-0.parquet` | every listing card seen in the search results that day | every run (~38k rows) |
| `details/dt=YYYY-MM-DD/part-0.parquet` | detail pages downloaded that day | every run |
| `photos/dt=YYYY-MM-DD/part-0.parquet` | photo fingerprints computed that day | every run |
| `events/dt=YYYY-MM-DD/part-0.parquet` | the day's events (new, price change, gone, …) | every run |
| `raw/dt=YYYY-MM-DD/raw.parquet` | gzip-compressed HTML of new or changed detail pages (at most `raw_max_per_run` = 3000 per run) and of the first 50 disappearance checks, so that pages can be re-parsed later | every run; kept for **90 days** |
| `state/listings.parquet` | current state: one row per listing | overwritten at the end of each run |
| `state/history/dt=YYYY-MM-DD/listings.parquet` | a copy of the state **before** that day's run, used for recovery and for reruns. It is the first thing a run writes: if it exists, a run has already happened that day | first run of the day; kept for **30 days** |
| `runs/crash/<date-time>.txt` | details of an unexpected error (traceback), which must not go into the public logs | only when an error occurs |
| `state/segments.parquet` | segment registry: first and last complete collection | every run |
| `runs/dt=YYYY-MM-DD/report.json` | run report: requests, errors, completeness, events, outcome | every run |
| `legacy/` | historical data imported once (original CSV + Parquet) | once |

Write order within a run: copy of the starting state (`state/history/dt=<day>/`, which marks that a run happened that day) → the day's partitions → new state → segment registry → report. Rerunning the same day overwrites that day's partitions for the municipalities that were collected.

Reading with DuckDB (example):

```sql
INSTALL httpfs; LOAD httpfs;
CREATE SECRET r2 (TYPE r2, KEY_ID '…', SECRET '…', ACCOUNT_ID '…');
SELECT * FROM read_parquet('r2://<bucket>/observations/*/*.parquet', hive_partitioning = true);
```

## observations — one row per listing card seen in the search results

Path: `observations/dt=YYYY-MM-DD/part-0.parquet`. Contains **all** the listing cards seen that day, including out-of-scope ones (auctions etc.), which are flagged as such.

| Column | Type | Meaning |
|---|---|---|
| `source` | str | source (`trovacasa`) |
| `listing_id` | str | listing ID on the source |
| `city` | str | municipality slug of the segment |
| `contract` | str | `vendita` (sale) or `affitto` (rent) |
| `url` | str | URL of the detail page |
| `title` | str | listing card title, e.g. "Appartamento da privato a Milano via Masaccio, 18" |
| `property_type` | str? | property type derived from the title (Appartamento, Loft, Villa a Schiera, …) |
| `is_private` | bool | listing from a private seller ("da privato" in the title) |
| `is_auction` | bool | auction ("all'asta" in the title) |
| `neighborhood` | str? | neighborhood/area given by the source |
| `surface_m2` | float? | floor area in m² |
| `rooms` | int? | number of rooms |
| `price_eur` | int? | asking price in euros (for rentals: the monthly rent). Null if not given |
| `price_on_request` | bool | the card shows text instead of a price (e.g. "Prezzo su richiesta", "price on request") |
| `tags` | list[str] | features shown on the card |
| `photo_ids` | list[str] | photo IDs, in the source's order |
| `advertiser_id` | str? | advertiser ID (agency or private account), taken from the URL |
| `eliminato` | bool | the card's `data-eliminato` attribute; its meaning has yet to be verified |
| `page` | int? | result page on which the card was seen (null in `legacy` rows) |
| `position` | int? | position on the page (0–23; null in `legacy` rows) |
| `in_scope` | bool | within the collection's scope (see `scope.py`) |
| `exclusion_reason` | str? | why it was excluded: `auction`, `whole_building`, `room` |
| `flags` | list[str] | borderline cases that are included but flagged: `new_build`, `rent_to_buy`, `investment` |
| `fingerprint` | str? | (null in `legacy` rows) fingerprint of the card (16 hex characters): it changes when the price, floor area, rooms, title, features or photos change; it does not depend on page or position |
| `run_date` | date | collection day |
| `source_run` | str | `daily` for the normal collection, `legacy` for the historical-data import |

## details — data from the detail page

Path: `details/dt=YYYY-MM-DD/part-0.parquet`. One row for each detail page downloaded that day (new, changed, weekly rotation, disappearance checks that returned 200). The typed fields are extracted from the attribute table; `attributes` still keeps all the original key/value pairs.

| Column | Type | Meaning |
|---|---|---|
| `source`, `listing_id` | str | listing key |
| `title` | str? | page title (e.g. "Appartamento in vendita a Milano …") |
| `price_eur` | int? | asking price (for rentals: the monthly rent) |
| `price_on_request` | bool | text shown instead of the price |
| `address` | str? | address as written by the advertiser |
| `property_type` | str? | "Tipologia" (property type) attribute |
| `city`, `contract` | str | segment (municipality slug, `vendita`/`affitto`) |
| `contract_label` | str? | "Contratto" (contract) attribute as written on the page (`Vendita`/`Affitto`) |
| `municipality` | str? | "Comune" (municipality) attribute |
| `listing_code` | str? | the source's listing code (`TC<id>`) |
| `agency_reference` | str? | **the advertiser's internal reference**: it often stays the same when a listing is republished (a signal for Phase 2) |
| `surface_m2` | float? | floor area in m² |
| `rooms` | int? | number of rooms |
| `bathrooms` | int? | number of bathrooms |
| `floor` | str? | "Piano" (floor) attribute, if present (rare) |
| `energy_class` | str? | energy class (`A4`…`G`) or "non disponibile" (not available) |
| `energy_kwh_m2_year` | float? | declared energy consumption in kWh/m² per year |
| `features` | list[str] | "Altre caratteristiche" (other features: Ascensore, Cantina, Arredato, …) |
| `attributes` | str (JSON) | all the pairs from the attribute table, in their original text, as a JSON object (`json.loads` / `json_extract` in DuckDB) |
| `description` | str? | full description |
| `agency_name` | str? | advertiser name ("Privato" for private sellers) |
| `agency_id` | str? | agency ID on the source (null for private sellers) |
| `agency_address` | str? | agency address |
| `latitude`, `longitude` | float? | map coordinates (precision as declared by the advertiser) |
| `detail_hash` | str | fingerprint of all the fields above: it changes whenever anything on the detail page changes |
| `run_date` | date | collection day |

## photos — perceptual photo fingerprints

Path: `photos/dt=YYYY-MM-DD/part-0.parquet`. The images themselves are **not** stored: only their fingerprints. In Phase 2 they will be used to recognize the same property republished under a new ID (agencies re-upload the same photos).

| Column | Type | Meaning |
|---|---|---|
| `source`, `listing_id` | str | listing key |
| `city`, `contract` | str | the listing's segment |
| `photo_index` | int | position of the photo in the listing (0 = first) |
| `photo_id` | str | photo ID on the source |
| `phash` | str | 64-bit pHash perceptual fingerprint (16 hex characters) |
| `dhash` | str | 64-bit dHash fingerprint, complementary to pHash |
| `run_date` | date | day the fingerprint was computed |

**How to compare two photos:** use the Hamming distance between their fingerprints (`scraper.photos.hamming`, or in SQL `bit_count(xor(...))` on the integer values). As a rough guide, ≤ 6 out of 64 bits = same photo (even if resized or recompressed); > 10 = different photos. The final thresholds will be calibrated on real data in Phase 2.

## state — current state, one row per listing

Path: `state/listings.parquet` (overwritten at the end of each run). The states and dates are explained in [disappearance-logic.md](disappearance-logic.md).

| Column | Type | Meaning |
|---|---|---|
| `source`, `listing_id` | str | listing key |
| `city`, `contract` | str | segment in which the listing was last seen |
| `url` | str | URL of the detail page |
| `status` | str | `active`, `delisted` (gone from the search results, but the page is still online), `removed` (page returns 404/410) |
| `in_scope`, `exclusion_reason`, `flags` | | scope, as in `observations` |
| `first_seen` | date | first day the listing was seen |
| `spell_start` | date | start of the current spell (= `first_seen`, or the day of the most recent reappearance) |
| `first_seen_censored` | bool | the listing was already online on the segment's first collection day (or in the imported historical data): its real start date is earlier |
| `list_last_seen` | date | last day the listing was seen in the search results — **the end date used for time to sell** |
| `absent_since` | date? | first day of the current absence (null if the listing is present) |
| `missing_streak` | int | number of checks that returned 200 during the current absence |
| `delisted_date` | date? | first day of the confirmed absence (confirmed by a conclusive check result) |
| `detail_gone_date` | date? | first day the detail page returned 404/410 |
| `last_check_date` | date? | most recent detail-page check during an absence |
| `last_fingerprint` | str? | fingerprint of the last listing card seen |
| `last_price` | int? | last price seen in the search results |
| `last_detail_date` | date? | last day the detail page was downloaded |
| `last_detail_hash` | str? | fingerprint of the last detail page |
| `photo_ids_hash` | str? | fingerprint of the photo list for which photo fingerprints were computed |
| `photos_done` | int | number of photos whose fingerprint has been computed |

## events — what happened, one event per row

Path: `events/dt=YYYY-MM-DD/part-0.parquet`.

| Column | Type | Meaning |
|---|---|---|
| `source`, `listing_id` | str | listing key |
| `city`, `contract` | str | the listing's segment |
| `run_date` | date | day of the run |
| `type` | str | `new`, `price_change`, `delisted`, `removed`, `detail_gone`, `reappeared`, `detail_changed` |
| `old_value` | str? | `price_change`: previous price; `reappeared`: previous status |
| `new_value` | str? | `new`/`price_change`: new price; `reappeared`: `active` |
| `spell_start` | date? | `removed`/`delisted`/`detail_gone`/`reappeared`: start of the spell that is being closed |
| `list_last_seen` | date? | same events: last day seen in the search results (end of the spell) |
| `delisted_date` | date? | same events: first day of the confirmed absence |

Filtering on `type in ('removed', 'delisted')` gives you the list of "sales" with their dates (see [disappearance-logic.md](disappearance-logic.md)).

## segments — segment registry

Path: `state/segments.parquet`. One row per (source, municipality, contract).

| Column | Type | Meaning |
|---|---|---|
| `source`, `city`, `contract` | str | segment |
| `first_complete_run` | date? | first day with a complete collection. New listings in the following 7 days are marked `first_seen_censored` (they were probably already online before) |
| `last_complete_run` | date? | last day with a complete collection |
| `drop_runs` | int | consecutive runs with a suspicious drop (`suspicious_drop`); on the third one the drop is accepted |
| `drop_runs_date` | date? | day of the last suspicious drop that was counted (a rerun on the same day does not count it twice) |

## raw — raw HTML (90 days)

Path: `raw/dt=YYYY-MM-DD/raw.parquet`. Used to re-parse pages if the parser had a bug, and to understand how the site presents removed listings.

| Column | Type | Meaning |
|---|---|---|
| `source`, `listing_id`, `city`, `contract` | str | listing and segment |
| `reason` | str | why the page was downloaded (`new`, `changed`, `never_detailed`, or an absence check that returned 404 or a redirect: the first 50 per run) |
| `url`, `final_url` | str | requested URL and final URL after any redirects |
| `status` | int | HTTP status code |
| `html_gz` | binary | full page, gzip-compressed (`gzip.decompress(...).decode()`) |
| `run_date` | date | day |

## legacy — imported historical data (one-off)

Path: `legacy/trovacasa_milano_2026-10-17.parquet` (plus the original CSV in the same folder). **Milan sale** listings (`milano`, `vendita`) seen on **2026-10-17** by the old scraper: 17,304 rows. The same listings are also in `observations/dt=2026-10-17/` with `source_run = legacy` (without photos, page or fingerprint), and they initialized the state with `first_seen = spell_start = list_last_seen = 2026-10-17` and `first_seen_censored = true`.

| Column | Type | Meaning |
|---|---|---|
| `listing_id`, `url`, `title`, `address` | str | from the CSV (`_id` without the `TC` prefix) |
| `property_type`, `is_private`, `is_auction` | | derived from the title ("Appartamento in vendita a …", "… da privato …", "… all'asta …") |
| `price_eur`, `price_on_request` | int?, bool | price; null if "Prezzo su richiesta" (price on request) |
| `surface_m2`, `rooms`, `bathrooms` | float?, int?, int? | as in the CSV |
| `energy_class`, `energy_kwh_m2_year` | str?, float? | energy class and, when present, consumption |
| `tags` | list[str] | features |
| `advertiser_id` | str? | from the URL |
| `in_scope`, `exclusion_reason` | | scope (564 auctions and 295 whole buildings/apartment blocks excluded) |
| `seen_date` | date | 2026-10-17 |

## Schema history

| Version | Date | Change |
|---|---|---|
| 1 | 2026-10-25 | First version |
