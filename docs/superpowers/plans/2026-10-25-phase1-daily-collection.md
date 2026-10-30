# Phase 1 — Daily collection: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** put the daily collection of trovacasa.it listings (sale + rent, 8 municipalities) into production on GitHub Actions, with storage on Cloudflare R2, without ever recording a false disappearance.

**Architecture:** a `uv` monorepo containing the `packages/scraper` package (Python module `scraper`). Pure, testable logic (parsers, scope, fingerprint, detail planning, state reconciliation, quality checks) is kept separate from I/O (async HTTP client, local/R2 storage). A pipeline orchestrates one daily run: it writes date-partitioned Parquet files first, then the state, then the report.

**Tech Stack:** Python 3.12, uv, httpx (async), selectolax, polars + pyarrow, boto3, imagehash + Pillow, pydantic v2, PyYAML, pytest (+ pytest-asyncio), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-25-real-estate-scraper-design.md` (read it before every task: the § references below point to it).

## Global Constraints

- `requires-python = ">=3.12"`; the `.python-version` file contains `3.12`.
- Code identifiers in English; documentation, domain comments and user-facing messages in Italian.
- Every task that changes behavior, data or how the scraper runs updates the documentation **in the same commit** (spec §12). Every new column goes into `docs/data-dictionary.md`.
- Commits follow Conventional Commits with a scope: `feat(scraper): …`, `test(scraper): …`, `docs: …`, `ci: …`. Messages end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No listing data in the logs or in the job summary: aggregate counts only (the repository is public, spec §8). Per-URL error details go only into the report on R2.
- No data in the repository except the HTML test fixtures (spec §9). `.gitignore` excludes `*.csv`, `*.docx`, `data/`, `.env`.
- Every Parquet file written has the columns `schema_version` (int, `SCHEMA_VERSION = 1`) and `scraper_version` (str).
- Network defaults (spec §6.6): site concurrency **6**, images **8**, **4** attempts, 30 s timeout, backoff when errors reach **20%** over a rolling window of 200 requests.
- Logic defaults: detail rotation every **7** days; **K = 6** photos for new listings, **K = 3** for the backlog; completeness **97%**; small segments (< **50** declared listings) tolerate at most **2** missing; alert if active listings drop by > **5%**; re-check `delisted` listings every **7** days; keep raw pages for **90** days and state copies for **30** days.
- `run_date` = the current date in the `Europe/Rome` time zone when the run starts.
- Never work around anti-bot protections: no proxies, no IP rotation, nothing of the kind.

## Review Focus

1. **Run limited to some municipalities** (`--cities`, or `--max-pages`): listings in segments that were not collected, or were collected incompletely, must not change state. Tests: `test_reconcile_ignores_unscraped_segments` (Task 6) and `test_max_pages_marks_segment_incomplete` (Task 9).
2. **Same listing twice in the search results** (pagination shifts while we are collecting): it must be counted only once. Test: `test_collect_cards_dedupes_by_key` (Task 9).
3. **Run cut short by time** (bootstrap or a slow site): the run must still finish by writing data and state; the work not done stays queued for the next day. Test: `test_pipeline_respects_deadline` (Task 9).
4. **Rerunning the same day** (manual rerun after an error): it must overwrite that day's partitions without duplicating events or corrupting `first_seen`. Test: `test_pipeline_rerun_same_day_is_idempotent` (Task 9).
5. **Missing price** ("Prezzo su richiesta" (price on request), `Trattativa Riservata` (private negotiation)): no crash, `price_eur = None`, and going from a price to no price counts as a `price_change`. Tests: `test_parse_card_price_on_request` (Task 2) and `test_reconcile_price_to_none_is_change` (Task 6).

---

## File map

```
.gitignore  .python-version  pyproject.toml (workspace)  README.md  CLAUDE.md  CHANGELOG.md
config/cities.yaml            municipalities, ISTAT codes, per-source slugs, contracts
config/settings.yaml          run parameters (defaults above)
packages/scraper/pyproject.toml
packages/scraper/src/scraper/
  __init__.py                 __version__ = "0.1.0"
  __main__.py                 entry point → cli.main()
  config.py                   City, Settings, load_cities(), load_settings()
  models.py                   Card, Detail, ListingState, Event, keys, SCHEMA_VERSION
  scope.py                    classify(card) → scope
  fingerprint.py              card_fingerprint(), detail_hash(), photo_ids_hash()
  sources/base.py             Source (Protocol)
  sources/trovacasa.py        URLs + parse_list_page() + parse_detail_page()
  http.py                     Fetcher (retries, backoff, statistics)
  storage.py                  Storage, LocalStorage, R2Storage, write_parquet(), read_parquet()
  planner.py                  plan_details(), plan_photos()
  quality.py                  segment_ok(), active_drop_alert()
  state.py                    reconcile()
  photos.py                   hash_image()
  pipeline.py                 run_daily()
  report.py                   build_report(), summary_markdown()
  legacy.py                   import_legacy()
  cli.py                      run | status | import-legacy
packages/scraper/tests/       test_*.py + fixtures/*.html
.github/workflows/ci.yml      tests on every push
.github/workflows/scrape.yml  daily + manual run
docs/ README.md overview.md architecture.md data-dictionary.md disappearance-logic.md
      sources/trovacasa.md runbook.md decisions/0001…0005
```

---

### Task 1: Monorepo, configuration and documentation skeleton

**Files:**
- Create: `.gitignore`, `.python-version`, `pyproject.toml`, `README.md`, `CLAUDE.md`, `CHANGELOG.md`
- Create: `config/cities.yaml`, `config/settings.yaml`
- Create: `packages/scraper/pyproject.toml`, `packages/scraper/src/scraper/{__init__,__main__,config}.py`
- Create: `docs/README.md`, `docs/overview.md`, `docs/decisions/0001-trovacasa-as-source.md`, `0002-casa-it-excluded.md`, `0003-github-actions-r2.md`, `0004-monorepo.md`, `0005-gone-means-sold.md`
- Test: `packages/scraper/tests/test_config.py`

**Interfaces:**
- Produces: `City(name: str, istat: str, slugs: dict[str, str], contracts: list[Literal["vendita","affitto"]])`; `Settings` (pydantic, fields: `site_concurrency=6, image_concurrency=8, max_retries=4, timeout_s=30.0, error_window=200, error_threshold=0.2, rotation_days=7, photos_new=6, photos_backlog=3, max_photos_per_run=30000, completeness_min=0.97, small_segment_threshold=50, small_segment_max_missing=2, active_drop_alert=0.05, delisted_recheck_days=7, raw_retention_days=90, state_history_days=30, max_runtime_minutes=100, full_details=False, max_pages=0`); `load_cities(path: Path) -> list[City]`; `load_settings(path: Path, overrides: dict) -> Settings`.

- [ ] **Step 1:** `git init` in the project folder, branch `main`. The user adds the remote (they create the GitHub repository themselves): do not create any remote repositories.
- [ ] **Step 2:** uv workspace: a root `pyproject.toml` with `[tool.uv.workspace] members = ["packages/*"]`; `packages/scraper/pyproject.toml` (name `scraper`, build backend `hatchling`, `src/` layout) with dependencies `httpx, selectolax, polars, pyarrow, boto3, imagehash, pillow, pydantic, pyyaml, tzdata` and a dev group `pytest, pytest-asyncio`. `uv sync` must complete.
- [ ] **Step 3:** `config/cities.yaml` with exactly these values (ISTAT codes verified on 2026-10-25):

```yaml
cities:
  - {name: Milano,        istat: "015146", slugs: {trovacasa: milano},        contracts: [vendita, affitto]}
  - {name: Busto Arsizio, istat: "012026", slugs: {trovacasa: busto-arsizio}, contracts: [vendita, affitto]}
  - {name: Gallarate,     istat: "012070", slugs: {trovacasa: gallarate},     contracts: [vendita, affitto]}
  - {name: Monza,         istat: "108033", slugs: {trovacasa: monza},         contracts: [vendita, affitto]}
  - {name: Legnano,       istat: "015118", slugs: {trovacasa: legnano},       contracts: [vendita, affitto]}
  - {name: Gorla Minore,  istat: "012079", slugs: {trovacasa: gorla-minore},  contracts: [vendita, affitto]}
  - {name: Marnate,       istat: "012098", slugs: {trovacasa: marnate},       contracts: [vendita, affitto]}
  - {name: Castellanza,   istat: "012042", slugs: {trovacasa: castellanza},   contracts: [vendita, affitto]}
```

  `config/settings.yaml` lists every `Settings` default, each with an Italian comment.
- [ ] **Step 4: failing tests** in `test_config.py`:

```python
def test_load_cities_reads_all_eight(): 
    cities = load_cities(REPO / "config/cities.yaml")
    assert len(cities) == 8
    assert cities[0].slugs["trovacasa"] == "milano" and cities[0].istat == "015146"
def test_load_cities_rejects_unknown_contract(tmp_path): # contracts: [asta] → pydantic ValidationError
def test_settings_overrides_win():
    s = load_settings(REPO / "config/settings.yaml", {"full_details": True, "max_pages": 2})
    assert s.full_details is True and s.max_pages == 2 and s.rotation_days == 7
```

- [ ] **Step 5:** `uv run pytest packages/scraper/tests/test_config.py -v` → FAIL (import error). Implement `config.py`. Run again → PASS.
- [ ] **Step 6: documentation.** `README.md` (what the project is, its status, quick start with `uv sync` / `uv run pytest`, link to `docs/README.md`); `CLAUDE.md` with the rules: update the documentation in the same commit, no data in the logs, no obfuscation, language (code in English / docs in Italian), pointers to the spec and the plan; `CHANGELOG.md` with a `scraper` section → `0.1.0 (in sviluppo)` (in development); `docs/README.md` (an index of every file listed in spec §12, with those not yet written marked "in arrivo" (coming soon)); `docs/overview.md` (purpose, Phases 1–5, current status); the 5 files in `docs/decisions/` in the *Context / Decision / Alternatives considered / Consequences* format, with content taken from spec §3 and from the conversation (DataDome on casa.it; Actions + R2 vs. a Google VM vs. Cloudflare Workers; monorepo vs. two repositories/accounts; gone = sold, with separate dates).
- [ ] **Step 7: commit** `chore: scaffold monorepo, configurazione e documentazione di base` (scaffold monorepo, configuration and base documentation).

---

### Task 2: Result-page parser, scope and listing-card fingerprint

**Files:**
- Create: `packages/scraper/src/scraper/{models,scope,fingerprint}.py`, `sources/base.py`, `sources/trovacasa.py`
- Create: `packages/scraper/tests/fixtures/` (see Step 1), `tests/test_trovacasa_list.py`, `tests/test_scope.py`, `tests/test_fingerprint.py`
- Create: `docs/sources/trovacasa.md`, `docs/data-dictionary.md` (`observations` section)

**Interfaces:**
- Produces:
  - `ListingKey = tuple[str, str]` (source, listing_id); `SegmentKey = tuple[str, str, str]` (source, city_slug, contract).
  - `Card` (pydantic): `source, listing_id: str, city: str, contract: str, url: str, title: str, property_type: str|None, is_private: bool, is_auction: bool, neighborhood: str|None, surface_m2: float|None, rooms: int|None, price_eur: int|None, price_on_request: bool, tags: list[str], photo_ids: list[str], advertiser_id: str|None, eliminato: bool, page: int, position: int`; property `key -> ListingKey`.
  - `ListPage(cards: list[Card], declared_total: int|None)`.
  - `trovacasa.list_url(city_slug: str, contract: str, page: int) -> str` (page 1 **without** `?page`); `trovacasa.detail_url(path_or_id)`; `trovacasa.parse_list_page(html: str, city: str, contract: str, page: int) -> ListPage`; `trovacasa.photo_url(photo_id: str) -> str`.
  - A `Source` Protocol in `sources/base.py` with these functions as methods; `TROVACASA` is its instance.
  - `classify(card: Card) -> tuple[bool, str|None, list[str]]` → (in_scope, exclusion_reason, flags).
  - `card_fingerprint(card: Card) -> str` (16 hex chars), `photo_ids_hash(ids: list[str]) -> str` (16 hex chars).

- [ ] **Step 1: fixtures.** Copy into `tests/fixtures/` the pages already saved during reconnaissance:
  `C:\Users\Dennis\AppData\Local\Temp\claude\c--Users-Dennis-Documents-DENNIS-Dev---Data-science-03-DATA-SCIENCE-real-estate-scraper\f782616b-0938-4749-b652-53b7bb16cd7b\scratchpad\fixtures\list_milano_vendita_p1.html` and `detail_73623446.html`.
  Download three more with browser headers: `list_busto-arsizio_vendita_p1.html` (contains auctions and villas), `list_milano_affitto_p1.html`, `list_milano_vendita_last.html` (the last page, with fewer than 24 listing cards). Prefer agency listings for any additional detail-page fixtures.
- [ ] **Step 2: failing tests** (`test_trovacasa_list.py`), with values taken from the Milano fixture:

```python
def test_parse_list_page_milano_p1():
    p = parse_list_page(fx("list_milano_vendita_p1.html"), "milano", "vendita", 1)
    assert p.declared_total == 17430 and len(p.cards) == 24
    c = next(c for c in p.cards if c.listing_id == "73817239")
    assert c.url == "https://www.trovacasa.it/annunci/mi-tc-3427-73817239"
    assert c.property_type == "Appartamento" and c.is_private and not c.is_auction
    assert c.neighborhood == "Monte Rosa - Lotto"
    assert (c.surface_m2, c.rooms, c.price_eur) == (75.0, 2, 450000)
    assert "Da Privato" in c.tags and c.advertiser_id == "3427"
    assert c.photo_ids[0] == "X_999999505_73817239_2036249360" and c.eliminato is False
    assert [x.position for x in p.cards] == list(range(24))
def test_parse_card_price_on_request():   # synthetic card with "Prezzo su richiesta" → price_eur None, price_on_request True
def test_parse_list_page_busto_has_auctions():  # at least one card with is_auction True and one "Villa"
def test_parse_list_page_last_page_has_fewer_cards()
def test_list_url_first_page_has_no_param():
    assert list_url("milano", "vendita", 1) == "https://www.trovacasa.it/case-in-vendita/milano"
    assert list_url("milano", "affitto", 3) == "https://www.trovacasa.it/case-in-affitto/milano?page=3"
def test_photo_url_formats():
    assert photo_url("A_1035_73623446_1273045083") == "https://img.trovacasa.it/annunci/mlis/A_1035_73623446_1273045083/foto.jpg"
    assert photo_url("X_999999505_73817239_2036249360") == "https://pic.trovacasa.it/image/2036249360/m-c.jpg"
```

  `test_scope.py`: auction detected from the title (`"Appartamento all'asta a …"`, also with the typographic apostrophe `’`) → `(False, "auction", …)`; auction detected from the tag `"All'asta/Asta Giudiziaria"` → `auction`; `Intero Stabile` and `Palazzo` (whole building) → `whole_building`; a rental whose title starts with `Stanza` (room) or `Posto letto` (bed in a shared room) → `room`; `Nuova Costruzione` (new build) → in scope with flag `new_build`; `Affitto con riscatto` (rent-to-buy) → flag `rent_to_buy`; `A Reddito` (already let, sold as an investment) → flag `investment`; an ordinary apartment → `(True, None, [])`.
  `test_fingerprint.py`: the same card with a different `page`/`position` → same fingerprint; a different price → different fingerprint; tags in a different order → same fingerprint.
- [ ] **Step 3:** run the tests → FAIL.
- [ ] **Step 4: implement.** Parse with selectolax: a listing card is `div.card.js_card_immobile` (ID from the `div[data-id]` inside the card, `data-eliminato`, `data-src-list` split on `|`); title from `a.card__title`; neighborhood from `span.card__quartiere` (empty → None); `span.card__info` elements recognized by their suffix, `m²` or `locale|locali`; price from `span.card__price` (digits with `.` as the thousands separator; no digits → None + `price_on_request`); tags from `p.annuncioTag`. `property_type` = the title text before the first occurrence of `" da privato"`, `" all'asta"`/`" all’asta"` or `" a "`. `advertiser_id` = the second-to-last numeric segment of the URL `/annunci/<prov>-tc-<advertiser>-<id>`. `declared_total` comes from the regex `([\d.]+) case in (vendita|affitto) a`. Fingerprint = sha1 of `price_eur, price_on_request, surface_m2, rooms, title, sorted(tags), photo_ids` serialized as JSON, first 16 hex chars.
- [ ] **Step 5:** tests → PASS.
- [ ] **Step 6: documentation.** `docs/sources/trovacasa.md`: URLs, pagination (24 per page, 301 on `?page=1`, 404 past the last page), selectors, photo ID formats, declared total, measured speeds and intermittent 500 errors (spec §4). `docs/data-dictionary.md`: introduction (keys, `schema_version`, `scraper_version`) + the column table for `observations` (every `Card` field + `in_scope, exclusion_reason, flags, fingerprint, run_date, source_run`).
- [ ] **Step 7: commit** `feat(scraper): parser pagina elenco trovacasa, perimetro e impronta` (trovacasa result-page parser, scope and fingerprint).

---

### Task 3: Detail-page parser

**Files:**
- Modify: `packages/scraper/src/scraper/models.py`, `sources/trovacasa.py`, `fingerprint.py`
- Test: `packages/scraper/tests/test_trovacasa_detail.py`
- Modify: `docs/data-dictionary.md` (`details` section), `docs/sources/trovacasa.md`

**Interfaces:**
- Produces: `Detail` (pydantic): `source, listing_id, title, price_eur: int|None, price_on_request: bool, address: str|None, property_type, contract, municipality, listing_code, agency_reference: str|None, surface_m2: float|None, rooms: int|None, bathrooms: int|None, floor: str|None, energy_class: str|None, features: list[str], attributes: dict[str, str]` (every `dt`/`dd` pair, with the trailing colon stripped from the keys), `description: str|None, agency_name: str|None, agency_id: str|None, agency_address: str|None, latitude: float|None, longitude: float|None`. `trovacasa.parse_detail_page(html: str, listing_id: str) -> Detail`. `detail_hash(d: Detail) -> str` (16 hex chars, over every field except `source`).

- [ ] **Step 1: failing tests**, with values from the `detail_73623446.html` fixture:

```python
def test_parse_detail_73623446():
    d = parse_detail_page(fx("detail_73623446.html"), "73623446")
    assert d.price_eur == 235000 and d.surface_m2 == 105.0 and d.rooms == 4 and d.bathrooms == 2
    assert d.listing_code == "TC73623446" and d.agency_reference == "A.C. - BARONIVRG"
    assert d.property_type == "Appartamento" and d.contract == "Vendita" and d.municipality == "Milano"
    assert d.energy_class == "non disponibile" and d.floor is None
    assert d.agency_name == "Rozzano" and d.agency_id == "1035"
    assert abs(d.latitude - 45.4030377) < 1e-6 and abs(d.longitude - 9.1697216) < 1e-6
    assert len(d.features) == 12 and "Ascensore" in d.features
    assert d.description.startswith("In stabile di recente ristrutturazione")
    assert "Tipologia" in d.attributes
def test_parse_detail_missing_blocks_returns_nones():  # minimal HTML with no map and no agency → fields None, no exception
def test_detail_hash_changes_with_description()
```

- [ ] **Step 2:** tests → FAIL.
- [ ] **Step 3: implement.** Selectors: title `h1.immobile__title`; price from the first `span.price`; address from the first `a.indirizzo`; attributes from `dl.row` → `dt.term`/`dd.description`; features from `a.immobileDetails__tagLabel`; description from `p.immobileDetails__text`; agency from `a.agenzia__name` (text + ID taken from `-tc-(\d+)` in the href) and `p.agenzia__address`; coordinates via the regexes `var latitude = ([\d.]+);` / `var longitude = ([\d.]+);`. Typed fields are taken from `attributes` (`Prezzo`, `Superficie`, `Numero locali`, `Numero bagni`, `Classe energetica`, `Piano`, `Codice annuncio`, `Riferimento`, `Tipologia`, `Contratto`, `Comune`). Do not extract phone numbers or email addresses.
- [ ] **Step 4:** tests → PASS.
- [ ] **Step 5: documentation** (`details` columns, detail-page selectors) and **commit** `feat(scraper): parser pagina dettaglio trovacasa` (trovacasa detail-page parser).

---

### Task 4: HTTP client with retries, backoff and statistics

**Files:**
- Create: `packages/scraper/src/scraper/http.py`
- Test: `packages/scraper/tests/test_http.py`
- Create: `docs/architecture.md` ("Rete" (Network) section)

**Interfaces:**
- Produces:
  - `FetchResult(url: str, status: int|None, text: str|None, content: bytes|None, final_url: str|None, error: str|None, attempts: int)`; property `ok` (status 200).
  - `class CircuitOpen(Exception)`.
  - `class Fetcher`: `__init__(self, concurrency: int, settings: Settings, transport: httpx.AsyncBaseTransport|None = None, sleep=asyncio.sleep)`; `async get(url: str, binary: bool = False) -> FetchResult`; `async get_many(urls: list[str], binary=False, deadline: float|None = None) -> list[FetchResult|None]` (None = not fetched because the deadline passed); `stats -> dict` (`requests, retries, failures, by_status, concurrency_now`); `async aclose()`.

- [ ] **Step 1: failing tests** using `httpx.MockTransport` and a fake `sleep` (no real waiting):

```python
async def test_retries_500_then_succeeds(): # 500, 500, 200 → ok, attempts == 3
async def test_error_redirect_is_retried():  # 302 → /Error/InternalServerError?path=… then 200 → ok, attempts == 2
async def test_404_not_retried():            # 404 → status 404, attempts == 1, error None
async def test_429_honours_retry_after():    # 429 with Retry-After: 5 → sleep called with 5, then 200
async def test_gives_up_after_max_retries(): # always 503 → status 503, attempts == 4, error set
async def test_concurrency_halves_on_error_rate(): # window with >20% errors → stats["concurrency_now"] == 3, starting from 6
async def test_circuit_opens_at_concurrency_one(): # persistent errors → CircuitOpen
async def test_get_many_stops_at_deadline():  # deadline already passed → all None
```

- [ ] **Step 2:** tests → FAIL.
- [ ] **Step 3: implement.** `httpx.AsyncClient(follow_redirects=True, headers=BROWSER_HEADERS, timeout=settings.timeout_s)`; headers from a real browser (desktop Chrome User-Agent, `Accept`, `Accept-Language: it-IT`, `Accept-Encoding: gzip, deflate, br`). Retryable: network/timeout exceptions, 5xx, 429, and a final URL whose path starts with `/Error/`. Wait time: `Retry-After` if present, otherwise `min(30, 2**attempt) + random.uniform(0, 1)`. Adaptive limiter: a semaphore with a current limit; over the rolling window of the last `error_window` requests, if the rate of definitive failures exceeds `error_threshold`, the limit is halved (minimum 1) and the window is reset; if the rate still exceeds the threshold with the limit at 1 → `CircuitOpen`.
- [ ] **Step 4:** tests → PASS.
- [ ] **Step 5: documentation** (`docs/architecture.md`: the daily-flow diagram from spec §5 + a Network section with the defaults) and **commit** `feat(scraper): client HTTP con tentativi e freno adattivo` (HTTP client with retries and adaptive backoff).

---

### Task 5: Local/R2 storage and versioned Parquet writing

**Files:**
- Create: `packages/scraper/src/scraper/storage.py`
- Test: `packages/scraper/tests/test_storage.py`
- Modify: `docs/data-dictionary.md` (path layout, spec §7)

**Interfaces:**
- Produces:
  - `class Storage(Protocol)`: `read_bytes(key: str) -> bytes|None`, `write_bytes(key: str, data: bytes) -> None`, `list_keys(prefix: str) -> list[str]`, `delete(key: str) -> None`.
  - `LocalStorage(root: Path)`; `R2Storage.from_env()` (variables `R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET`; endpoint `https://{account_id}.r2.cloudflarestorage.com`, `region_name="auto"`).
  - `write_parquet(storage, key: str, df: pl.DataFrame, scraper_version: str) -> None` (adds `schema_version` and `scraper_version`; zstd compression); `read_parquet(storage, key) -> pl.DataFrame|None`.
  - `scraper_version() -> str` = `f"{__version__}+{GITHUB_SHA[:7]}"` or `f"{__version__}+local"`.
  - `partition_key(dataset: str, run_date: date, name: str = "part-0.parquet") -> str` → `f"{dataset}/dt={run_date:%Y-%m-%d}/{name}"`.
  - `prune_partitions(storage, dataset: str, keep_days: int, run_date: date) -> int`.

- [ ] **Step 1: failing tests:** Parquet round trip on `LocalStorage(tmp_path)` with the version columns present and `schema_version == 1`; `read_parquet` of a missing key → `None`; `partition_key("observations", date(2026,10,26))` → `"observations/dt=2026-10-26/part-0.parquet"`; `prune_partitions` with partitions from 100 and 10 days ago and `keep_days=90` → deletes only the first; `scraper_version()` with `GITHUB_SHA=abcdef123` → ends with `+abcdef1`.
- [ ] **Step 2:** tests → FAIL. **Step 3:** implement. **Step 4:** tests → PASS.
- [ ] **Step 5: documentation** (paths and retention, spec §7) and **commit** `feat(scraper): storage locale e R2 con Parquet versionati` (local and R2 storage with versioned Parquet).

---

### Task 6: State reconciliation and events (the core of the false-disappearance protection)

**Files:**
- Modify: `packages/scraper/src/scraper/models.py`
- Create: `packages/scraper/src/scraper/state.py`
- Test: `packages/scraper/tests/test_state.py`
- Create: `docs/disappearance-logic.md`

**Interfaces:**
- Consumes: `Card`, `Detail`, `ListingKey`, `SegmentKey`, `card_fingerprint`, `detail_hash`, `classify`.
- Produces:
  - `ListingState` (pydantic): `source, listing_id, city, contract, url, status: Literal["active","delisted","removed"], in_scope: bool, exclusion_reason: str|None, flags: list[str], first_seen: date, first_seen_censored: bool, list_last_seen: date, absent_since: date|None, missing_streak: int, delisted_date: date|None, detail_gone_date: date|None, last_check_date: date|None, last_fingerprint: str|None, last_price: int|None, last_detail_date: date|None, last_detail_hash: str|None, photo_ids_hash: str|None, photos_done: int`; property `segment -> SegmentKey`.
  - `Event(source, listing_id, run_date: date, type: Literal["new","price_change","delisted","removed","detail_gone","reappeared","detail_changed"], old_value: str|None, new_value: str|None)`.
  - `CheckOutcome = Literal["alive","gone","error"]`.
  - `reconcile(prev: dict[ListingKey, ListingState], cards: dict[ListingKey, Card], details: dict[ListingKey, Detail], checks: dict[ListingKey, CheckOutcome], scraped_segments: set[SegmentKey], segment_ok: dict[SegmentKey, bool], bootstrap_segments: set[SegmentKey], run_date: date) -> tuple[dict[ListingKey, ListingState], list[Event]]`.

**Rules (spec §6.3; decisions made by the implementer are marked ◆):**
- Present today, unknown → new `active` state, `first_seen = run_date`, `first_seen_censored = segment in bootstrap_segments`, `new` event.
- Present, `active` → `list_last_seen = run_date`, `missing_streak = 0`, `absent_since = None`; a price different from `last_price` (including value↔None) → `price_change` (old/new as a string or None).
- Present, `delisted`/`removed` → `reappeared`; goes back to `active` with `delisted_date = detail_gone_date = absent_since = None`, `missing_streak = 0`; `first_seen` unchanged (the history stays in the events).
- Absent, segment not collected or `segment_ok` false → **no change at all**.
- Absent, `active`, segment ok, check `gone` or `alive`: `absent_since = absent_since or run_date`, `last_check_date = run_date`; then `gone` → `removed`, `delisted_date = absent_since`, `detail_gone_date = run_date`, `removed` event; `alive` → `missing_streak += 1`, and if `>= 2` → `delisted`, `delisted_date = absent_since`, `delisted` event.
- Absent, `active`, check `error` or missing → no change (◆ not even `absent_since`).
- ◆ Only 404/410 count as `gone`. A possible "non disponibile" (not available) notice served with a 200 response will be handled after we have looked at the raw samples of the first listings that disappear (spec §6.3).
- Absent, `delisted`, check `gone` → `removed`, `detail_gone_date = run_date`, `detail_gone` event.
- ◆ `data-eliminato` does not change the state (it is only recorded, spec §6.3).
- Detail present in `details` → `last_detail_date = run_date`; a hash different from the previous non-null one → `detail_changed`; update `last_detail_hash`.
- Always update `last_fingerprint`, `last_price` and `in_scope/exclusion_reason/flags` from the listing cards present.

- [ ] **Step 1: failing tests** (`test_state.py`, one per rule):

```python
test_reconcile_new_listing_emits_new
test_reconcile_new_in_bootstrap_segment_is_censored
test_reconcile_price_change_emits_event
test_reconcile_price_to_none_is_change
test_reconcile_absent_gone_is_removed_with_dates   # list_last_seen unchanged, delisted_date == run_date, detail_gone_date == run_date
test_reconcile_absent_alive_once_stays_active      # missing_streak == 1, status active, no events
test_reconcile_absent_alive_twice_is_delisted      # two days → delisted, delisted_date == first day of absence
test_reconcile_absent_error_changes_nothing
test_reconcile_segment_not_ok_changes_nothing      # even with check "gone"
test_reconcile_ignores_unscraped_segments
test_reconcile_delisted_then_gone_emits_detail_gone
test_reconcile_removed_reappears
test_reconcile_detail_change_emits_event
test_reconcile_present_resets_absence              # present after an absence → missing_streak 0, absent_since None
```

- [ ] **Step 2:** tests → FAIL. **Step 3:** implement `reconcile` as a pure function (no I/O). **Step 4:** tests → PASS.
- [ ] **Step 5: documentation.** `docs/disappearance-logic.md`: state diagram (`active → delisted → removed`, `reappeared`), the meaning of the three dates, why `list_last_seen` is the end date for the time to sell, the safety lock, and what still needs to be verified (`data-eliminato`, how removed listings actually behave). The `state` and `events` columns go into the data dictionary.
- [ ] **Step 6: commit** `feat(scraper): riconciliazione stato annunci ed eventi` (listing state reconciliation and events).

---

### Task 7: Detail and photo planning, quality checks

**Files:**
- Create: `packages/scraper/src/scraper/planner.py`, `quality.py`
- Test: `packages/scraper/tests/test_planner.py`, `test_quality.py`

**Interfaces:**
- Consumes: `ListingState`, `Card`, `Settings`.
- Produces:
  - `DetailTask(key: ListingKey, url: str, reason: Literal["absence_check","new","changed","never_detailed","delisted_recheck","rotation","full"])`.
  - `plan_details(prev, cards: dict[ListingKey, Card], scraped_segments, settings, run_date) -> list[DetailTask]` — a single task per listing (the highest-priority reason), with the list sorted by priority in the order of the Literal.
  - `PhotoTask(key: ListingKey, photo_id: str, index: int)`.
  - `plan_photos(state: dict[ListingKey, ListingState], cards, new_keys: set[ListingKey], settings) -> list[PhotoTask]`.
  - `segment_ok(declared_total: int|None, unique_cards: int, failed_pages: int, settings) -> tuple[bool, str|None]`.
  - `active_drop_alert(prev_active: int, now_active: int, settings) -> bool`.

**Rules:**
- Detail pages only for `in_scope` listing cards, except `absence_check`/`delisted_recheck`, which apply to every tracked listing.
- `absence_check`: state `active` in a collected segment and absent today. `delisted_recheck`: `delisted` with `last_check_date` null or older than `delisted_recheck_days`.
- `new`: key missing from `prev`, or state not `active`. `changed`: different fingerprint. `never_detailed`: `last_detail_date` null. `full`: `settings.full_details`.
- `rotation` (◆ spread out, so that after the bootstrap they do not all fall due on the same day): `int(listing_id) % rotation_days == run_date.toordinal() % rotation_days` and `last_detail_date < run_date`, or `last_detail_date` older than `2 * rotation_days`.
- Photos: for non-censored `new_keys` → the first `photos_new` photos; then the backlog = listings that are `active`, `in_scope`, with `photos_done == 0`, sorted by ascending `first_seen` and then `listing_id` → the first `photos_backlog` photos; listings whose `photo_ids_hash` changed → redo the first `photos_new`; the total is truncated to `max_photos_per_run`.
- `segment_ok`: `declared_total` None → `(False, "no_declared_total")`; `failed_pages > 0` → `(False, "failed_pages")`; fewer declared listings than `small_segment_threshold` → ok if `declared - unique <= small_segment_max_missing`; otherwise ok if `unique / declared >= completeness_min`; reason `"incomplete"`.
- `active_drop_alert`: `prev_active > 0 and (prev_active - now_active) / prev_active > active_drop_alert`.

- [ ] **Step 1: failing tests** — `test_planner.py`: one test per reason; `test_plan_details_one_task_per_listing_highest_priority`; `test_plan_details_skips_out_of_scope_except_checks`; `test_rotation_spreads_over_days` (1,000 listings detailed on the same day → over the next 7 days, each day gets between 100 and 200 of them); `test_plan_photos_new_full_k_backlog_k3_and_cap`. `test_quality.py`: `segment_ok(17430, 17000, 0)` → ok (97.5%); `(17430, 16800, 0)` → `incomplete`; `(4, 2, 0)` → ok; `(4, 1, 0)` → `incomplete`; `(None, 10, 0)` → `no_declared_total`; `(100, 100, 1)` → `failed_pages`; `active_drop_alert(1000, 940)` → True, `(1000, 960)` → False, `(0, 10)` → False.
- [ ] **Step 2:** tests → FAIL. **Step 3:** implement. **Step 4:** tests → PASS.
- [ ] **Step 5: documentation** (`disappearance-logic.md`: quality checks and thresholds; `architecture.md`: detail priorities and rotation) and **commit** `feat(scraper): pianificazione dettagli/foto e controlli di qualità` (detail/photo planning and quality checks).

---

### Task 8: Photo fingerprints

**Files:**
- Create: `packages/scraper/src/scraper/photos.py`
- Test: `packages/scraper/tests/test_photos.py`

**Interfaces:**
- Produces: `hash_image(content: bytes) -> tuple[str, str] | None` → (phash, dhash) as 16-character hex strings; `None` if the image cannot be decoded.

- [ ] **Step 1: failing tests:** an image generated with Pillow → a 16-character hex hash; the same image resized to 50% and recompressed as JPEG at quality 60 → pHash Hamming distance ≤ 6; a different image (a different drawing) → distance > 10; invalid bytes → `None`.
- [ ] **Step 2:** FAIL. **Step 3:** implement with `imagehash.phash` / `imagehash.dhash` (hash size 8). **Step 4:** PASS.
- [ ] **Step 5: documentation** (`photos` columns in the data dictionary, how to compare two fingerprints) and **commit** `feat(scraper): impronte percettive delle foto` (perceptual photo fingerprints).

---

### Task 9: Daily pipeline, report and CLI

**Files:**
- Create: `packages/scraper/src/scraper/{pipeline,report,cli}.py`, modify `__main__.py`
- Test: `packages/scraper/tests/test_pipeline.py`, `test_report.py`
- Create: `docs/runbook.md` (first version)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `RunOptions(run_date: date, cities: list[str]|None, dry_run: bool)`.
  - `async run_daily(storage: Storage, cities: list[City], settings: Settings, options: RunOptions, transport: httpx.AsyncBaseTransport|None = None, clock=time.monotonic) -> dict` (returns the report; the exit code is `report["exit_code"]`).
  - `build_report(...) -> dict`, `summary_markdown(report: dict) -> str` (aggregates only).
  - CLI `python -m scraper`:
    - `run [--date YYYY-MM-DD] [--cities milano,monza] [--full-details] [--max-pages N] [--max-runtime-minutes M] [--dry-run] [--storage local|r2] [--local-root PATH]`
    - `status [--storage …] [--max-age-days 2]` → prints the date of the latest report; exits with 1 if it is older than `max-age-days` or missing.
    - `import-legacy CSV_PATH [--storage …] [--force]` (Task 10).

**How `run_daily` works** (spec §5 and §7):
1. Read `state/listings.parquet` (empty if missing). `bootstrap_segments` = the selected segments that have no listing at all in the state.
2. Search results: for each segment, page 1 → `declared_total`; pages `2..ceil(declared/24)+1` in parallel (a 404 on the last page + 1 is accepted); with `max_pages > 0`, stop there. Listing cards are deduplicated by key (first occurrence wins). `failed_pages` = pages that are not 200 after the retries, excluding the final 404.
3. `segment_ok` for each segment; the detail deadline is start + 0.85 × `max_runtime_minutes`, the photo deadline 0.90 ×.
4. `plan_details` → fetch → for each result: 200 → `parse_detail_page` (into `details`), `checks[key] = "alive"`; 404/410 → `"gone"`; anything else, or not fetched → `"error"` for the check tasks. The HTML of `new`/`changed`/`never_detailed` detail pages, and of the first 50 `gone` checks of the run → `raw`.
5. `reconcile` → new state + events.
6. `plan_photos` (with `new_keys` = the `new` events) → fetch the binaries with the image concurrency → `hash_image` → update `photos_done` and `photo_ids_hash` in the states.
7. Unless `dry_run`: write the day's `observations`, `details`, `photos`, `events` and `raw` → copy the previous state to `state/history/listings-YYYY-MM-DD.parquet` → write the new `state/listings.parquet` → `runs/dt=…/report.json`; prune raw (90 days) and state history (30 days).
8. `exit_code = 1` if any segment is not ok, on `active_drop_alert`, on `CircuitOpen` (in that case the search results already collected are written and no disappearances are recorded) or on an exception; otherwise 0. If `GITHUB_STEP_SUMMARY` exists, append `summary_markdown` to it.

- [ ] **Step 1: failing tests** (`test_pipeline.py`) with a **fake site** built on `httpx.MockTransport`, which serves result and detail pages generated from a small in-memory model (a dictionary of listings per segment), and `LocalStorage(tmp_path)`:

```python
test_pipeline_day1_bootstrap_all_new_and_censored
test_pipeline_day2_removed_listing_404_becomes_removed
test_pipeline_listing_missing_from_list_but_alive_needs_two_days
test_pipeline_failed_page_blocks_disappearances   # one page always returns 500 → no removed/delisted, exit_code 1
test_max_pages_marks_segment_incomplete
test_collect_cards_dedupes_by_key                 # the same listing on two pages → one row
test_pipeline_respects_deadline                   # fake clock past the deadline → data written, remaining detail pages left with last_detail_date None
test_pipeline_rerun_same_day_is_idempotent        # two runs on the same day → same files, no duplicated events, first_seen unchanged
test_pipeline_dry_run_writes_nothing
test_pipeline_writes_versioned_partitions_and_report
```

  `test_report.py`: `summary_markdown` contains none of the URLs or `listing_id`s present in the input report.
- [ ] **Step 2:** FAIL. **Step 3:** implement `pipeline.py`, `report.py`, `cli.py` (argparse; `--storage r2` uses `R2Storage.from_env()`; aggregate-only logs). **Step 4:** PASS (`uv run pytest -v`, the whole suite).
- [ ] **Step 5: limited real-world local trial:** `uv run python -m scraper run --cities gorla-minore,marnate --storage local --local-root data/` → exit code 0, segments ok, files in `data/` (a folder ignored by git); a second run straight afterwards → no `removed` events. Record the observed duration and counts in `docs/sources/trovacasa.md`.
- [ ] **Step 6: documentation.** `docs/runbook.md`: running locally, CLI options, rerunning a day, restoring the state from `state/history/`, checking freshness with `status`, adding a municipality (one line in `cities.yaml`). Update `docs/architecture.md` with the actual flow.
- [ ] **Step 7: commit** `feat(scraper): pipeline giornaliera, report e CLI` (daily pipeline, report and CLI).

---

### Task 10: Importing the historical data from 2026-10-17

**Files:**
- Create: `packages/scraper/src/scraper/legacy.py`
- Test: `packages/scraper/tests/test_legacy.py` (+ the fixture `fixtures/legacy_sample.csv` with 5 **synthetic** rows, not copied from the real CSV)
- Modify: `cli.py`, `docs/data-dictionary.md`, `docs/runbook.md`

**Interfaces:**
- Produces: `import_legacy(csv_path: Path, storage: Storage, force: bool = False) -> int` (rows imported).

**Rules (spec §6.5):** a `;`-separated UTF-8 CSV with columns `_id;url;prezzo;titolo;indirizzo;superficie_m2;num_locali;num_bagni;classe_ener;tags;attivo;data_comparsa;data_aggiornamento;data_scomparsa`. `listing_id` = `_id` without `TC`; price `"219.000 €"` → 219000, `"Prezzo su richiesta"` → None + `price_on_request`; `num_locali`/`num_bagni` `"2.0"` → 2; `tags` parsed with `ast.literal_eval`; `property_type` = the title before `" in vendita"`; city `milano`, contract `vendita`, source `trovacasa`, `advertiser_id` from the URL, scope via `classify`. Writes: `legacy/trovacasa_milano_2026-10-17.parquet` (every parsed column, including bathrooms and energy class), `observations/dt=2026-10-17/part-0.parquet` with `source_run = "legacy"`, the original CSV into `legacy/` and, **only if no state exists yet** (otherwise an error, unless `force`), the initial state: `active`, `first_seen = list_last_seen = 2026-10-17`, `first_seen_censored = True`, `last_fingerprint = last_detail_date = None`.

- [ ] **Step 1: failing tests:** importing the sample → 5 rows, prices and room counts converted, a state with 5 censored `active` listings; a second import without `force` → error; then `run_daily` against the fake site, where 3 of the 5 listings are in the search results and 2 return 404 → 2 `removed` events with `list_last_seen == date(2026,10,17)`; the 3 present listings do not generate `new` (they are already known) and get their detail page fetched (reason `changed`, because the imported fingerprint is null). The imported state has `last_price` = the price from the CSV, so a price that has changed since 2026-10-17 generates a `price_change`.
- [ ] **Step 2:** FAIL. **Step 3:** implement + the CLI subcommand. **Step 4:** PASS.
- [ ] **Step 5: documentation and commit** `feat(scraper): import dello storico Milano 2026-10-17` (import the Milano historical data from 2026-10-17).

---

### Task 11: GitHub Actions and production rollout

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/scrape.yml`
- Modify: `docs/runbook.md`, `README.md`, `CHANGELOG.md`

- [ ] **Step 1: `ci.yml`:** on `push` and `pull_request`: checkout, `astral-sh/setup-uv` (check for the latest available major version), `uv sync --package scraper`, `uv run pytest -q`.
- [ ] **Step 2: `scrape.yml`:** `schedule: cron "17 2 * * *"` (02:17 UTC, night-time in Italy) + `workflow_dispatch` with inputs `cities` (string, empty = all), `full_details` (bool), `max_pages` (number, 0), `max_runtime_minutes` (number, 100; 340 for the bootstrap), `dry_run` (bool). `concurrency: {group: scrape, cancel-in-progress: false}`; `timeout-minutes: 350` (a safety net: the real deadline is enforced inside the application). The secrets `R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET` are passed as environment variables. Command: `uv run python -m scraper run --storage r2 …inputs…`. No output other than the aggregate logs and the job summary.
- [ ] **Step 3: local verification:** `uv run pytest -q` all green; lint the workflow YAML (e.g. `actionlint` if available, otherwise a manual review).
- [ ] **Step 4: documentation.** `docs/runbook.md`: one-off setup (create the R2 bucket and a token with read/write permission on that bucket only; add the 4 secrets on GitHub), manual start, the **bootstrap procedure**, what to do when the failure email arrives, the freshness check, plan B (a Google VM, spec §8). `README.md` with badge/status and links. `CHANGELOG.md` → `scraper 0.1.0`.
- [ ] **Step 5: commit** `ci: workflow test e raccolta giornaliera` (test and daily-collection workflows) and tag `scraper-v0.1.0`.
- [ ] **Step 6: production rollout (needs the user):** the user creates the public repository, adds the remote and the secrets, and pushes. Then, in order: (a) run `import-legacy` on the CSV towards R2 from the local machine; (b) manual start with `cities=gorla-minore,marnate`, `max_pages=0` → check that GitHub's IPs get no 403 responses (if they do: stop and switch to plan B, spec §8); (c) a full manual bootstrap run with `max_runtime_minutes=340`; (d) check the report and the counts; (e) leave the cron enabled. Record the real results from GitHub Actions (duration, errors, minutes used) in `docs/sources/trovacasa.md`.
