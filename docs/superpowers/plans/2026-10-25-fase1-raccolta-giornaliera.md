# Fase 1 — Raccolta giornaliera: piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** mettere in produzione la raccolta giornaliera degli annunci trovacasa.it (vendita + affitto, 8 comuni) su GitHub Actions con storage su Cloudflare R2, senza mai registrare scomparse false.

**Architecture:** monorepo `uv` con il pacchetto `packages/scraper` (modulo Python `scraper`). Logica pura e testabile (parser, perimetro, impronta, pianificazione dettagli, riconciliazione stato, controlli qualità) separata dall'I/O (client HTTP asincrono, storage locale/R2). Una pipeline orchestra un run giornaliero e scrive Parquet partizionati per data, poi lo stato, poi il report.

**Tech Stack:** Python 3.12, uv, httpx (async), selectolax, polars + pyarrow, boto3, imagehash + Pillow, pydantic v2, PyYAML, pytest (+ pytest-asyncio), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-25-real-estate-scraper-design.md` (leggerla prima di ogni task: i § citati sotto rimandano lì).

## Global Constraints

- `requires-python = ">=3.12"`; file `.python-version` = `3.12`.
- Identificatori del codice in inglese; documentazione, commenti di dominio e messaggi utente in italiano.
- Ogni task che cambia comportamento, dati o esecuzione aggiorna la documentazione **nello stesso commit** (spec §12). Ogni nuova colonna va in `docs/dizionario-dati.md`.
- Commit in stile Conventional Commits con ambito: `feat(scraper): …`, `test(scraper): …`, `docs: …`, `ci: …`. Messaggi terminano con la riga `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nessun dato degli annunci nei log o nel job summary: solo conteggi aggregati (repo pubblico, spec §8). Dettagli per-URL degli errori solo nel report su R2.
- Nessun dato nel repository tranne le fixture HTML dei test (spec §9). `.gitignore` esclude `*.csv`, `*.docx`, `data/`, `.env`.
- Ogni file Parquet scritto ha le colonne `schema_version` (int, `SCHEMA_VERSION = 1`) e `scraper_version` (str).
- Default di rete (spec §6.6): concorrenza sito **6**, immagini **8**, **4** tentativi, timeout 30 s, freno al **20%** di errori su finestra mobile di 200 richieste.
- Default di logica: rotazione dettagli **7** giorni; foto **K = 6** per annunci nuovi, **K = 3** per arretrato; completezza **97%**; segmenti piccoli (< **50** dichiarati) ammettono al massimo **2** mancanti; allarme se gli annunci attivi calano > **5%**; ricontrollo `delisted` ogni **7** giorni; retention raw **90** giorni, copie dello stato **30** giorni.
- `run_date` = data corrente nel fuso `Europe/Rome` all'avvio del run.
- Mai aggirare protezioni anti-bot: niente proxy, rotazione IP o simili.

## Review Focus

1. **Run limitato ad alcuni comuni** (`--cities`, o `--max-pages`): gli annunci dei segmenti non raccolti o incompleti non devono cambiare stato. Test: `test_reconcile_ignores_unscraped_segments` (Task 6) e `test_max_pages_marks_segment_incomplete` (Task 9).
2. **Stesso annuncio due volte negli elenchi** (paginazione che slitta durante la raccolta): va contato una volta sola. Test: `test_collect_cards_dedupes_by_key` (Task 9).
3. **Run interrotto per tempo** (bootstrap o sito lento): il run deve chiudersi scrivendo comunque dati e stato; il lavoro non fatto resta in coda per il giorno dopo. Test: `test_pipeline_respects_deadline` (Task 9).
4. **Rieseguire lo stesso giorno** (re-run manuale dopo un errore): deve sovrascrivere le partizioni del giorno senza duplicare eventi né falsare `first_seen`. Test: `test_pipeline_rerun_same_day_is_idempotent` (Task 9).
5. **Prezzo assente** ("Prezzo su richiesta", `Trattativa Riservata`): niente crash, `price_eur = None`, e il passaggio prezzo→nessun prezzo è un `price_change`. Test: `test_parse_card_price_on_request` (Task 2) e `test_reconcile_price_to_none_is_change` (Task 6).

---

## Mappa dei file

```
.gitignore  .python-version  pyproject.toml (workspace)  README.md  CLAUDE.md  CHANGELOG.md
config/cities.yaml            comuni, ISTAT, slug per fonte, contratti
config/settings.yaml          parametri di esecuzione (default sopra)
packages/scraper/pyproject.toml
packages/scraper/src/scraper/
  __init__.py                 __version__ = "0.1.0"
  __main__.py                 entrypoint → cli.main()
  config.py                   City, Settings, load_cities(), load_settings()
  models.py                   Card, Detail, ListingState, Event, chiavi, SCHEMA_VERSION
  scope.py                    classify(card) → perimetro
  fingerprint.py              card_fingerprint(), detail_hash(), photo_ids_hash()
  sources/base.py             Source (Protocol)
  sources/trovacasa.py        URL + parse_list_page() + parse_detail_page()
  http.py                     Fetcher (retry, freno, statistiche)
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
.github/workflows/ci.yml      test su ogni push
.github/workflows/scrape.yml  run giornaliero + manuale
docs/ README.md panoramica.md architettura.md dizionario-dati.md logica-scomparse.md
      fonti/trovacasa.md runbook.md decisioni/0001…0005
```

---

### Task 1: Monorepo, configurazione e scheletro della documentazione

**Files:**
- Create: `.gitignore`, `.python-version`, `pyproject.toml`, `README.md`, `CLAUDE.md`, `CHANGELOG.md`
- Create: `config/cities.yaml`, `config/settings.yaml`
- Create: `packages/scraper/pyproject.toml`, `packages/scraper/src/scraper/{__init__,__main__,config}.py`
- Create: `docs/README.md`, `docs/panoramica.md`, `docs/decisioni/0001-fonte-trovacasa.md`, `0002-esclusione-casa-it.md`, `0003-github-actions-r2.md`, `0004-monorepo.md`, `0005-sparito-uguale-venduto.md`
- Test: `packages/scraper/tests/test_config.py`

**Interfaces:**
- Produces: `City(name: str, istat: str, slugs: dict[str, str], contracts: list[Literal["vendita","affitto"]])`; `Settings` (pydantic, campi: `site_concurrency=6, image_concurrency=8, max_retries=4, timeout_s=30.0, error_window=200, error_threshold=0.2, rotation_days=7, photos_new=6, photos_backlog=3, max_photos_per_run=30000, completeness_min=0.97, small_segment_threshold=50, small_segment_max_missing=2, active_drop_alert=0.05, delisted_recheck_days=7, raw_retention_days=90, state_history_days=30, max_runtime_minutes=100, full_details=False, max_pages=0`); `load_cities(path: Path) -> list[City]`; `load_settings(path: Path, overrides: dict) -> Settings`.

- [ ] **Step 1:** `git init` nella cartella del progetto, branch `main`. Il remote lo aggiunge l'utente (crea lui il repo GitHub): non creare repository remoti.
- [ ] **Step 2:** Workspace uv: root `pyproject.toml` con `[tool.uv.workspace] members = ["packages/*"]`; `packages/scraper/pyproject.toml` (nome `scraper`, build backend `hatchling`, layout `src/`) con dipendenze `httpx, selectolax, polars, pyarrow, boto3, imagehash, pillow, pydantic, pyyaml, tzdata` e gruppo dev `pytest, pytest-asyncio`. `uv sync` deve completare.
- [ ] **Step 3:** `config/cities.yaml` con questi valori esatti (ISTAT verificati il 2026-10-25):

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

  `config/settings.yaml` riporta tutti i default di `Settings` con un commento italiano per ciascuno.
- [ ] **Step 4: test che falliscono** in `test_config.py`:

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

- [ ] **Step 5:** `uv run pytest packages/scraper/tests/test_config.py -v` → FAIL (import error). Implementare `config.py`. Rieseguire → PASS.
- [ ] **Step 6: documentazione.** `README.md` (cos'è, stato, avvio rapido `uv sync` / `uv run pytest`, link a `docs/README.md`); `CLAUDE.md` con le regole: aggiornare la documentazione nello stesso commit, niente dati nei log, nessun offuscamento, lingua (codice EN / docs IT), riferimento a spec e piano; `CHANGELOG.md` con sezione `scraper` → `0.1.0 (in sviluppo)`; `docs/README.md` (indice con tutti i file di spec §12, quelli non ancora scritti marcati "in arrivo"); `docs/panoramica.md` (scopo, fasi 1–5, stato attuale); i 5 file in `docs/decisioni/` nel formato *Contesto / Decisione / Alternative scartate / Conseguenze*, contenuti presi dalla spec §3 e dalla conversazione (DataDome su casa.it; Actions+R2 vs VM Google vs Cloudflare Workers; monorepo vs due repo/account; sparito = venduto con date separate).
- [ ] **Step 7: commit** `chore: scaffold monorepo, configurazione e documentazione di base`.

---

### Task 2: Parser della pagina elenco, perimetro e impronta della scheda

**Files:**
- Create: `packages/scraper/src/scraper/{models,scope,fingerprint}.py`, `sources/base.py`, `sources/trovacasa.py`
- Create: `packages/scraper/tests/fixtures/` (vedi Step 1), `tests/test_trovacasa_list.py`, `tests/test_scope.py`, `tests/test_fingerprint.py`
- Create: `docs/fonti/trovacasa.md`, `docs/dizionario-dati.md` (sezione `observations`)

**Interfaces:**
- Produces:
  - `ListingKey = tuple[str, str]` (source, listing_id); `SegmentKey = tuple[str, str, str]` (source, city_slug, contract).
  - `Card` (pydantic): `source, listing_id: str, city: str, contract: str, url: str, title: str, property_type: str|None, is_private: bool, is_auction: bool, neighborhood: str|None, surface_m2: float|None, rooms: int|None, price_eur: int|None, price_on_request: bool, tags: list[str], photo_ids: list[str], advertiser_id: str|None, eliminato: bool, page: int, position: int`; property `key -> ListingKey`.
  - `ListPage(cards: list[Card], declared_total: int|None)`.
  - `trovacasa.list_url(city_slug: str, contract: str, page: int) -> str` (pagina 1 **senza** `?page`); `trovacasa.detail_url(path_or_id)`; `trovacasa.parse_list_page(html: str, city: str, contract: str, page: int) -> ListPage`; `trovacasa.photo_url(photo_id: str) -> str`.
  - `Source` Protocol in `sources/base.py` con queste funzioni come metodi; `TROVACASA` istanza.
  - `classify(card: Card) -> tuple[bool, str|None, list[str]]` → (in_scope, exclusion_reason, flags).
  - `card_fingerprint(card: Card) -> str` (16 hex), `photo_ids_hash(ids: list[str]) -> str` (16 hex).

- [ ] **Step 1: fixture.** Copiare in `tests/fixtures/` le pagine già salvate in ricognizione:
  `C:\Users\Dennis\AppData\Local\Temp\claude\c--Users-Dennis-Documents-DENNIS-Dev---Data-science-03-DATA-SCIENCE-real-estate-scraper\f782616b-0938-4749-b652-53b7bb16cd7b\scratchpad\fixtures\list_milano_vendita_p1.html` e `detail_73623446.html`.
  Scaricarne altre tre con header da browser: `list_busto-arsizio_vendita_p1.html` (contiene aste e ville), `list_milano_affitto_p1.html`, `list_milano_vendita_last.html` (ultima pagina, meno di 24 schede). Preferire annunci di agenzie per eventuali fixture di dettaglio aggiuntive.
- [ ] **Step 2: test che falliscono** (`test_trovacasa_list.py`), valori presi dalla fixture Milano:

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
def test_parse_card_price_on_request():   # scheda sintetica con "Prezzo su richiesta" → price_eur None, price_on_request True
def test_parse_list_page_busto_has_auctions():  # almeno una scheda con is_auction True e una "Villa"
def test_parse_list_page_last_page_has_fewer_cards()
def test_list_url_first_page_has_no_param():
    assert list_url("milano", "vendita", 1) == "https://www.trovacasa.it/case-in-vendita/milano"
    assert list_url("milano", "affitto", 3) == "https://www.trovacasa.it/case-in-affitto/milano?page=3"
def test_photo_url_formats():
    assert photo_url("A_1035_73623446_1273045083") == "https://img.trovacasa.it/annunci/mlis/A_1035_73623446_1273045083/foto.jpg"
    assert photo_url("X_999999505_73817239_2036249360") == "https://pic.trovacasa.it/image/2036249360/m-c.jpg"
```

  `test_scope.py`: asta per titolo (`"Appartamento all'asta a …"`, anche con apostrofo tipografico `’`) → `(False, "auction", …)`; asta per tag `"All'asta/Asta Giudiziaria"` → `auction`; `Intero Stabile` e `Palazzo` → `whole_building`; affitto con titolo che inizia per `Stanza` o `Posto letto` → `room`; `Nuova Costruzione` → in scope con flag `new_build`; `Affitto con riscatto` → flag `rent_to_buy`; `A Reddito` → flag `investment`; appartamento normale → `(True, None, [])`.
  `test_fingerprint.py`: stessa scheda con `page`/`position` diversi → stessa impronta; prezzo diverso → impronta diversa; ordine dei tag diverso → stessa impronta.
- [ ] **Step 3:** eseguire i test → FAIL.
- [ ] **Step 4: implementare.** Parsing con selectolax: scheda = `div.card.js_card_immobile` (ID da `div[data-id]` dentro la scheda, `data-eliminato`, `data-src-list` separato da `|`); titolo `a.card__title`; quartiere `span.card__quartiere` (vuoto → None); `span.card__info` riconosciuti per suffisso `m²` / `locale|locali`; prezzo `span.card__price` (cifre con `.` delle migliaia; nessuna cifra → None + `price_on_request`); tag `p.annuncioTag`. `property_type` = testo del titolo prima del primo tra `" da privato"`, `" all'asta"`/`" all’asta"`, `" a "`. `advertiser_id` = penultimo segmento numerico dell'URL `/annunci/<prov>-tc-<advertiser>-<id>`. `declared_total` da regex `([\d.]+) case in (vendita|affitto) a`. Impronta = sha1 di `price_eur, price_on_request, surface_m2, rooms, title, sorted(tags), photo_ids` serializzati in JSON, primi 16 hex.
- [ ] **Step 5:** test → PASS.
- [ ] **Step 6: documentazione.** `docs/fonti/trovacasa.md`: URL, paginazione (24/pagina, 301 su `?page=1`, 404 oltre l'ultima), selettori, formati ID foto, totale dichiarato, velocità misurate ed errori 500 intermittenti (spec §4). `docs/dizionario-dati.md`: introduzione (chiavi, `schema_version`, `scraper_version`) + tabella colonne di `observations` (tutti i campi di `Card` + `in_scope, exclusion_reason, flags, fingerprint, run_date, source_run`).
- [ ] **Step 7: commit** `feat(scraper): parser pagina elenco trovacasa, perimetro e impronta`.

---

### Task 3: Parser della pagina di dettaglio

**Files:**
- Modify: `packages/scraper/src/scraper/models.py`, `sources/trovacasa.py`, `fingerprint.py`
- Test: `packages/scraper/tests/test_trovacasa_detail.py`
- Modify: `docs/dizionario-dati.md` (sezione `details`), `docs/fonti/trovacasa.md`

**Interfaces:**
- Produces: `Detail` (pydantic): `source, listing_id, title, price_eur: int|None, price_on_request: bool, address: str|None, property_type, contract, municipality, listing_code, agency_reference: str|None, surface_m2: float|None, rooms: int|None, bathrooms: int|None, floor: str|None, energy_class: str|None, features: list[str], attributes: dict[str, str]` (tutte le coppie `dt`/`dd`, chiavi senza i due punti finali), `description: str|None, agency_name: str|None, agency_id: str|None, agency_address: str|None, latitude: float|None, longitude: float|None`. `trovacasa.parse_detail_page(html: str, listing_id: str) -> Detail`. `detail_hash(d: Detail) -> str` (16 hex, su tutti i campi tranne `source`).

- [ ] **Step 1: test che falliscono**, valori dalla fixture `detail_73623446.html`:

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
def test_parse_detail_missing_blocks_returns_nones():  # HTML minimo senza mappa né agenzia → campi None, nessuna eccezione
def test_detail_hash_changes_with_description()
```

- [ ] **Step 2:** test → FAIL.
- [ ] **Step 3: implementare.** Selettori: titolo `h1.immobile__title`; prezzo primo `span.price`; indirizzo primo `a.indirizzo`; attributi `dl.row` → `dt.term`/`dd.description`; caratteristiche `a.immobileDetails__tagLabel`; descrizione `p.immobileDetails__text`; agenzia `a.agenzia__name` (testo + id da `-tc-(\d+)` nell'href), `p.agenzia__address`; coordinate con regex `var latitude = ([\d.]+);` / `var longitude = ([\d.]+);`. Campi tipizzati presi da `attributes` (`Prezzo`, `Superficie`, `Numero locali`, `Numero bagni`, `Classe energetica`, `Piano`, `Codice annuncio`, `Riferimento`, `Tipologia`, `Contratto`, `Comune`). Non estrarre telefoni né email.
- [ ] **Step 4:** test → PASS.
- [ ] **Step 5: documentazione** (colonne `details`, selettori del dettaglio) e **commit** `feat(scraper): parser pagina dettaglio trovacasa`.

---

### Task 4: Client HTTP con tentativi, freno e statistiche

**Files:**
- Create: `packages/scraper/src/scraper/http.py`
- Test: `packages/scraper/tests/test_http.py`
- Create: `docs/architettura.md` (sezione "Rete")

**Interfaces:**
- Produces:
  - `FetchResult(url: str, status: int|None, text: str|None, content: bytes|None, final_url: str|None, error: str|None, attempts: int)`; property `ok` (status 200).
  - `class CircuitOpen(Exception)`.
  - `class Fetcher`: `__init__(self, concurrency: int, settings: Settings, transport: httpx.AsyncBaseTransport|None = None, sleep=asyncio.sleep)`; `async get(url: str, binary: bool = False) -> FetchResult`; `async get_many(urls: list[str], binary=False, deadline: float|None = None) -> list[FetchResult|None]` (None = non eseguito per scadenza); `stats -> dict` (`requests, retries, failures, by_status, concurrency_now`); `async aclose()`.

- [ ] **Step 1: test che falliscono** con `httpx.MockTransport` e `sleep` finto (nessuna attesa reale):

```python
async def test_retries_500_then_succeeds(): # 500, 500, 200 → ok, attempts == 3
async def test_error_redirect_is_retried():  # 302 → /Error/InternalServerError?path=… poi 200 → ok, attempts == 2
async def test_404_not_retried():            # 404 → status 404, attempts == 1, error None
async def test_429_honours_retry_after():    # 429 con Retry-After: 5 → sleep chiamato con 5, poi 200
async def test_gives_up_after_max_retries(): # sempre 503 → status 503, attempts == 4, error valorizzato
async def test_concurrency_halves_on_error_rate(): # finestra con >20% errori → stats["concurrency_now"] == 3 partendo da 6
async def test_circuit_opens_at_concurrency_one(): # errori persistenti → CircuitOpen
async def test_get_many_stops_at_deadline():  # deadline già passata → tutti None
```

- [ ] **Step 2:** test → FAIL.
- [ ] **Step 3: implementare.** `httpx.AsyncClient(follow_redirects=True, headers=BROWSER_HEADERS, timeout=settings.timeout_s)`; header da browser reale (User-Agent Chrome desktop, `Accept`, `Accept-Language: it-IT`, `Accept-Encoding: gzip, deflate, br`). Ritentabili: eccezioni di rete/timeout, 5xx, 429, URL finale con percorso che inizia per `/Error/`. Attesa: `Retry-After` se presente, altrimenti `min(30, 2**attempt) + random.uniform(0, 1)`. Limitatore adattivo: semaforo con limite corrente; sulla finestra mobile delle ultime `error_window` richieste, se il tasso di fallimenti definitivi supera `error_threshold` il limite si dimezza (minimo 1) e la finestra si azzera; se supera ancora la soglia con limite 1 → `CircuitOpen`.
- [ ] **Step 4:** test → PASS.
- [ ] **Step 5: documentazione** (`docs/architettura.md`: schema del flusso giornaliero di spec §5 + sezione Rete con i default) e **commit** `feat(scraper): client HTTP con tentativi e freno adattivo`.

---

### Task 5: Storage locale/R2 e scrittura Parquet versionata

**Files:**
- Create: `packages/scraper/src/scraper/storage.py`
- Test: `packages/scraper/tests/test_storage.py`
- Modify: `docs/dizionario-dati.md` (layout dei percorsi, spec §7)

**Interfaces:**
- Produces:
  - `class Storage(Protocol)`: `read_bytes(key: str) -> bytes|None`, `write_bytes(key: str, data: bytes) -> None`, `list_keys(prefix: str) -> list[str]`, `delete(key: str) -> None`.
  - `LocalStorage(root: Path)`; `R2Storage.from_env()` (variabili `R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET`; endpoint `https://{account_id}.r2.cloudflarestorage.com`, `region_name="auto"`).
  - `write_parquet(storage, key: str, df: pl.DataFrame, scraper_version: str) -> None` (aggiunge `schema_version`, `scraper_version`; compressione zstd); `read_parquet(storage, key) -> pl.DataFrame|None`.
  - `scraper_version() -> str` = `f"{__version__}+{GITHUB_SHA[:7]}"` oppure `f"{__version__}+local"`.
  - `partition_key(dataset: str, run_date: date, name: str = "part-0.parquet") -> str` → `f"{dataset}/dt={run_date:%Y-%m-%d}/{name}"`.
  - `prune_partitions(storage, dataset: str, keep_days: int, run_date: date) -> int`.

- [ ] **Step 1: test che falliscono:** round-trip Parquet su `LocalStorage(tmp_path)` con colonne di versione presenti e `schema_version == 1`; `read_parquet` di chiave inesistente → `None`; `partition_key("observations", date(2026,10,26))` → `"observations/dt=2026-10-26/part-0.parquet"`; `prune_partitions` con partizioni di 100 e 10 giorni fa e `keep_days=90` → cancella solo la prima; `scraper_version()` con `GITHUB_SHA=abcdef123` → termina con `+abcdef1`.
- [ ] **Step 2:** test → FAIL. **Step 3:** implementare. **Step 4:** test → PASS.
- [ ] **Step 5: documentazione** (percorsi e retention, spec §7) e **commit** `feat(scraper): storage locale e R2 con Parquet versionati`.

---

### Task 6: Riconciliazione dello stato ed eventi (il cuore anti-scomparse-false)

**Files:**
- Modify: `packages/scraper/src/scraper/models.py`
- Create: `packages/scraper/src/scraper/state.py`
- Test: `packages/scraper/tests/test_state.py`
- Create: `docs/logica-scomparse.md`

**Interfaces:**
- Consumes: `Card`, `Detail`, `ListingKey`, `SegmentKey`, `card_fingerprint`, `detail_hash`, `classify`.
- Produces:
  - `ListingState` (pydantic): `source, listing_id, city, contract, url, status: Literal["active","delisted","removed"], in_scope: bool, exclusion_reason: str|None, flags: list[str], first_seen: date, first_seen_censored: bool, list_last_seen: date, absent_since: date|None, missing_streak: int, delisted_date: date|None, detail_gone_date: date|None, last_check_date: date|None, last_fingerprint: str|None, last_price: int|None, last_detail_date: date|None, last_detail_hash: str|None, photo_ids_hash: str|None, photos_done: int`; property `segment -> SegmentKey`.
  - `Event(source, listing_id, run_date: date, type: Literal["new","price_change","delisted","removed","detail_gone","reappeared","detail_changed"], old_value: str|None, new_value: str|None)`.
  - `CheckOutcome = Literal["alive","gone","error"]`.
  - `reconcile(prev: dict[ListingKey, ListingState], cards: dict[ListingKey, Card], details: dict[ListingKey, Detail], checks: dict[ListingKey, CheckOutcome], scraped_segments: set[SegmentKey], segment_ok: dict[SegmentKey, bool], bootstrap_segments: set[SegmentKey], run_date: date) -> tuple[dict[ListingKey, ListingState], list[Event]]`.

**Regole (spec §6.3; decisioni del costruttore marcate ◆):**
- Presente oggi, sconosciuto → nuovo stato `active`, `first_seen = run_date`, `first_seen_censored = segment in bootstrap_segments`, evento `new`.
- Presente, `active` → `list_last_seen = run_date`, `missing_streak = 0`, `absent_since = None`; prezzo diverso da `last_price` (incluso valore↔None) → `price_change` (old/new come stringa o None).
- Presente, `delisted`/`removed` → `reappeared`, torna `active` con `delisted_date = detail_gone_date = absent_since = None`, `missing_streak = 0`; `first_seen` invariato (la storia resta negli eventi).
- Assente, segmento non raccolto o `segment_ok` falso → **nessuna modifica**.
- Assente, `active`, segmento ok, check `gone` o `alive`: `absent_since = absent_since or run_date`, `last_check_date = run_date`; poi `gone` → `removed`, `delisted_date = absent_since`, `detail_gone_date = run_date`, evento `removed`; `alive` → `missing_streak += 1`, e se `>= 2` → `delisted`, `delisted_date = absent_since`, evento `delisted`.
- Assente, `active`, check `error` o mancante → nessuna modifica (◆ nemmeno `absent_since`).
- ◆ Solo 404/410 valgono come `gone`. Un eventuale avviso di "non disponibile" con risposta 200 si gestirà dopo aver osservato i campioni raw dei primi annunci scomparsi (spec §6.3).
- Assente, `delisted`, check `gone` → `removed`, `detail_gone_date = run_date`, evento `detail_gone`.
- ◆ `data-eliminato` non cambia lo stato (solo osservato, spec §6.3).
- Dettaglio presente in `details` → `last_detail_date = run_date`; hash diverso dal precedente non nullo → `detail_changed`; aggiornare `last_detail_hash`.
- Aggiornare sempre `last_fingerprint`, `last_price`, `in_scope/exclusion_reason/flags` dalle schede presenti.

- [ ] **Step 1: test che falliscono** (`test_state.py`, uno per regola):

```python
test_reconcile_new_listing_emits_new
test_reconcile_new_in_bootstrap_segment_is_censored
test_reconcile_price_change_emits_event
test_reconcile_price_to_none_is_change
test_reconcile_absent_gone_is_removed_with_dates   # list_last_seen invariato, delisted_date == run_date, detail_gone_date == run_date
test_reconcile_absent_alive_once_stays_active      # missing_streak == 1, status active, nessun evento
test_reconcile_absent_alive_twice_is_delisted      # due giorni → delisted, delisted_date == primo giorno di assenza
test_reconcile_absent_error_changes_nothing
test_reconcile_segment_not_ok_changes_nothing      # anche con check "gone"
test_reconcile_ignores_unscraped_segments
test_reconcile_delisted_then_gone_emits_detail_gone
test_reconcile_removed_reappears
test_reconcile_detail_change_emits_event
test_reconcile_present_resets_absence              # presente dopo un'assenza → missing_streak 0, absent_since None
```

- [ ] **Step 2:** test → FAIL. **Step 3:** implementare `reconcile` come funzione pura (nessun I/O). **Step 4:** test → PASS.
- [ ] **Step 5: documentazione.** `docs/logica-scomparse.md`: diagramma degli stati (`active → delisted → removed`, `reappeared`), significato delle tre date, perché `list_last_seen` è la data di fine per il tempo di vendita, blocco di sicurezza, cosa resta da verificare (`data-eliminato`, comportamento reale degli annunci rimossi). Colonne `state` ed `events` nel dizionario dati.
- [ ] **Step 6: commit** `feat(scraper): riconciliazione stato annunci ed eventi`.

---

### Task 7: Pianificazione dettagli e foto, controlli di qualità

**Files:**
- Create: `packages/scraper/src/scraper/planner.py`, `quality.py`
- Test: `packages/scraper/tests/test_planner.py`, `test_quality.py`

**Interfaces:**
- Consumes: `ListingState`, `Card`, `Settings`.
- Produces:
  - `DetailTask(key: ListingKey, url: str, reason: Literal["absence_check","new","changed","never_detailed","delisted_recheck","rotation","full"])`.
  - `plan_details(prev, cards: dict[ListingKey, Card], scraped_segments, settings, run_date) -> list[DetailTask]` — un solo task per annuncio (motivo con priorità più alta), lista ordinata per priorità nell'ordine del Literal.
  - `PhotoTask(key: ListingKey, photo_id: str, index: int)`.
  - `plan_photos(state: dict[ListingKey, ListingState], cards, new_keys: set[ListingKey], settings) -> list[PhotoTask]`.
  - `segment_ok(declared_total: int|None, unique_cards: int, failed_pages: int, settings) -> tuple[bool, str|None]`.
  - `active_drop_alert(prev_active: int, now_active: int, settings) -> bool`.

**Regole:**
- Dettagli solo per schede `in_scope`, tranne `absence_check`/`delisted_recheck` che valgono per ogni annuncio tracciato.
- `absence_check`: stato `active` nel segmento raccolto e assente oggi. `delisted_recheck`: `delisted` e `last_check_date` nullo o più vecchio di `delisted_recheck_days`.
- `new`: chiave assente in `prev` o stato non `active`. `changed`: impronta diversa. `never_detailed`: `last_detail_date` nullo. `full`: `settings.full_details`.
- `rotation` (◆ distribuita, per evitare che dopo il bootstrap scadano tutti lo stesso giorno): `int(listing_id) % rotation_days == run_date.toordinal() % rotation_days` e `last_detail_date < run_date`, oppure `last_detail_date` più vecchio di `2 * rotation_days`.
- Foto: per `new_keys` non censurati → prime `photos_new` foto; poi arretrato = annunci `active`, `in_scope`, `photos_done == 0`, ordinati per `first_seen` crescente poi `listing_id` → prime `photos_backlog` foto; annunci con `photo_ids_hash` cambiato → rifare le prime `photos_new`; totale troncato a `max_photos_per_run`.
- `segment_ok`: `declared_total` None → `(False, "no_declared_total")`; `failed_pages > 0` → `(False, "failed_pages")`; dichiarati < `small_segment_threshold` → ok se `declared - unique <= small_segment_max_missing`; altrimenti ok se `unique / declared >= completeness_min`; motivo `"incomplete"`.
- `active_drop_alert`: `prev_active > 0 and (prev_active - now_active) / prev_active > active_drop_alert`.

- [ ] **Step 1: test che falliscono** — `test_planner.py`: un test per motivo; `test_plan_details_one_task_per_listing_highest_priority`; `test_plan_details_skips_out_of_scope_except_checks`; `test_rotation_spreads_over_days` (1.000 annunci dettagliati lo stesso giorno → nei 7 giorni successivi ogni giorno ne riceve tra 100 e 200); `test_plan_photos_new_full_k_backlog_k3_and_cap`. `test_quality.py`: `segment_ok(17430, 17000, 0)` → ok (97,5%); `(17430, 16800, 0)` → `incomplete`; `(4, 2, 0)` → ok; `(4, 1, 0)` → `incomplete`; `(None, 10, 0)` → `no_declared_total`; `(100, 100, 1)` → `failed_pages`; `active_drop_alert(1000, 940)` → True, `(1000, 960)` → False, `(0, 10)` → False.
- [ ] **Step 2:** test → FAIL. **Step 3:** implementare. **Step 4:** test → PASS.
- [ ] **Step 5: documentazione** (`logica-scomparse.md`: controlli di qualità e soglie; `architettura.md`: priorità dei dettagli e rotazione) e **commit** `feat(scraper): pianificazione dettagli/foto e controlli di qualità`.

---

### Task 8: Impronte delle foto

**Files:**
- Create: `packages/scraper/src/scraper/photos.py`
- Test: `packages/scraper/tests/test_photos.py`

**Interfaces:**
- Produces: `hash_image(content: bytes) -> tuple[str, str] | None` → (phash, dhash) in esadecimale a 16 caratteri; `None` se l'immagine non è decodificabile.

- [ ] **Step 1: test che falliscono:** immagine generata con Pillow → hash di 16 caratteri hex; stessa immagine ridimensionata al 50% e ricompressa JPEG qualità 60 → distanza di Hamming del pHash ≤ 6; immagine diversa (altro disegno) → distanza > 10; bytes non validi → `None`.
- [ ] **Step 2:** FAIL. **Step 3:** implementare con `imagehash.phash` / `imagehash.dhash` (dimensione hash 8). **Step 4:** PASS.
- [ ] **Step 5: documentazione** (colonne `photos` nel dizionario dati, come confrontare due impronte) e **commit** `feat(scraper): impronte percettive delle foto`.

---

### Task 9: Pipeline giornaliera, report e CLI

**Files:**
- Create: `packages/scraper/src/scraper/{pipeline,report,cli}.py`, modifica `__main__.py`
- Test: `packages/scraper/tests/test_pipeline.py`, `test_report.py`
- Create: `docs/runbook.md` (prima versione)

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces:
  - `RunOptions(run_date: date, cities: list[str]|None, dry_run: bool)`.
  - `async run_daily(storage: Storage, cities: list[City], settings: Settings, options: RunOptions, transport: httpx.AsyncBaseTransport|None = None, clock=time.monotonic) -> dict` (restituisce il report; il codice di uscita è `report["exit_code"]`).
  - `build_report(...) -> dict`, `summary_markdown(report: dict) -> str` (solo aggregati).
  - CLI `python -m scraper`:
    - `run [--date YYYY-MM-DD] [--cities milano,monza] [--full-details] [--max-pages N] [--max-runtime-minutes M] [--dry-run] [--storage local|r2] [--local-root PATH]`
    - `status [--storage …] [--max-age-days 2]` → stampa data dell'ultimo report; uscita 1 se più vecchio di `max-age-days` o assente.
    - `import-legacy CSV_PATH [--storage …] [--force]` (Task 10).

**Flusso di `run_daily`** (spec §5 e §7):
1. Legge `state/listings.parquet` (vuoto se assente). `bootstrap_segments` = segmenti selezionati senza alcun annuncio nello stato.
2. Elenchi: per ogni segmento, pagina 1 → `declared_total`; pagine `2..ceil(declared/24)+1` in parallelo (404 sull'ultima +1 accettato); con `max_pages > 0` ci si ferma lì. Schede deduplicate per chiave (prima occorrenza). `failed_pages` = pagine non 200 dopo i tentativi, esclusa la 404 finale.
3. `segment_ok` per segmento; scadenza dettagli = avvio + 0,85 × `max_runtime_minutes`, foto = 0,90 ×.
4. `plan_details` → fetch → per ogni risultato: 200 → `parse_detail_page` (in `details`), `checks[key] = "alive"`; 404/410 → `"gone"`; altro o non eseguito → `"error"` per i task di controllo. HTML dei dettagli `new`/`changed`/`never_detailed` e dei primi 50 controlli `gone` del run → `raw`.
5. `reconcile` → nuovo stato + eventi.
6. `plan_photos` (con `new_keys` = eventi `new`) → fetch binari con concorrenza immagini → `hash_image` → aggiornare `photos_done` e `photo_ids_hash` negli stati.
7. Se non `dry_run`: scrivere `observations`, `details`, `photos`, `events`, `raw` del giorno → copia dello stato precedente in `state/history/listings-YYYY-MM-DD.parquet` → nuovo `state/listings.parquet` → `runs/dt=…/report.json`; potatura raw (90 gg) e storico stato (30 gg).
8. `exit_code = 1` se un segmento non ok, `active_drop_alert`, `CircuitOpen` (in quel caso: elenchi già raccolti vengono scritti, nessuna scomparsa) o eccezione; altrimenti 0. Se esiste `GITHUB_STEP_SUMMARY`, accodarvi `summary_markdown`.

- [ ] **Step 1: test che falliscono** (`test_pipeline.py`) con un **sito finto** costruito su `httpx.MockTransport` che serve pagine elenco/dettaglio generate da un piccolo modello in memoria (dizionario di annunci per segmento) e `LocalStorage(tmp_path)`:

```python
test_pipeline_day1_bootstrap_all_new_and_censored
test_pipeline_day2_removed_listing_404_becomes_removed
test_pipeline_listing_missing_from_list_but_alive_needs_two_days
test_pipeline_failed_page_blocks_disappearances   # una pagina sempre 500 → nessun removed/delisted, exit_code 1
test_max_pages_marks_segment_incomplete
test_collect_cards_dedupes_by_key                 # lo stesso annuncio su due pagine → una riga
test_pipeline_respects_deadline                   # clock finto oltre la scadenza → dati scritti, dettagli rimasti con last_detail_date None
test_pipeline_rerun_same_day_is_idempotent        # due run stesso giorno → stessi file, eventi non duplicati, first_seen invariato
test_pipeline_dry_run_writes_nothing
test_pipeline_writes_versioned_partitions_and_report
```

  `test_report.py`: `summary_markdown` non contiene nessun URL né `listing_id` presenti nel report di input.
- [ ] **Step 2:** FAIL. **Step 3:** implementare `pipeline.py`, `report.py`, `cli.py` (argparse; `--storage r2` usa `R2Storage.from_env()`; log solo aggregati). **Step 4:** PASS (`uv run pytest -v`, tutta la suite).
- [ ] **Step 5: prova reale locale, limitata:** `uv run python -m scraper run --cities gorla-minore,marnate --storage local --local-root data/` → uscita 0, segmenti ok, file in `data/` (cartella ignorata da git); seconda esecuzione subito dopo → nessun evento `removed`. Annotare in `docs/fonti/trovacasa.md` durata e conteggi osservati.
- [ ] **Step 6: documentazione.** `docs/runbook.md`: eseguire in locale, opzioni CLI, rieseguire un giorno, ripristinare lo stato da `state/history/`, controllare la freschezza con `status`, aggiungere un comune (una riga in `cities.yaml`). Aggiornare `docs/architettura.md` con il flusso reale.
- [ ] **Step 7: commit** `feat(scraper): pipeline giornaliera, report e CLI`.

---

### Task 10: Import dello storico del 2026-10-17

**Files:**
- Create: `packages/scraper/src/scraper/legacy.py`
- Test: `packages/scraper/tests/test_legacy.py` (+ fixture `fixtures/legacy_sample.csv` con 5 righe **sintetiche**, non copiate dal CSV reale)
- Modify: `cli.py`, `docs/dizionario-dati.md`, `docs/runbook.md`

**Interfaces:**
- Produces: `import_legacy(csv_path: Path, storage: Storage, force: bool = False) -> int` (righe importate).

**Regole (spec §6.5):** CSV `;`, UTF-8, colonne `_id;url;prezzo;titolo;indirizzo;superficie_m2;num_locali;num_bagni;classe_ener;tags;attivo;data_comparsa;data_aggiornamento;data_scomparsa`. `listing_id` = `_id` senza `TC`; prezzo `"219.000 €"` → 219000, `"Prezzo su richiesta"` → None + `price_on_request`; `num_locali`/`num_bagni` `"2.0"` → 2; `tags` con `ast.literal_eval`; `property_type` = titolo prima di `" in vendita"`; città `milano`, contratto `vendita`, fonte `trovacasa`, `advertiser_id` dall'URL, perimetro con `classify`. Scrive: `legacy/trovacasa_milano_2026-10-17.parquet` (tutte le colonne parsate, incluse bagni e classe energetica), `observations/dt=2026-10-17/part-0.parquet` con `source_run = "legacy"`, il CSV originale in `legacy/` e, **solo se lo stato non esiste** (altrimenti errore salvo `force`), lo stato iniziale: `active`, `first_seen = list_last_seen = 2026-10-17`, `first_seen_censored = True`, `last_fingerprint = last_detail_date = None`.

- [ ] **Step 1: test che falliscono:** import del campione → 5 righe, prezzi e locali convertiti, stato con 5 annunci `active` censurati; secondo import senza `force` → errore; poi `run_daily` col sito finto in cui 3 dei 5 annunci sono negli elenchi e 2 danno 404 → 2 eventi `removed` con `list_last_seen == date(2026,10,17)`; i 3 presenti non generano `new` (sono già noti) e ricevono il dettaglio (motivo `changed`, perché l'impronta importata è nulla). Lo stato importato ha `last_price` = prezzo del CSV, così un prezzo cambiato dal 17/10 genera `price_change`.
- [ ] **Step 2:** FAIL. **Step 3:** implementare + sottocomando CLI. **Step 4:** PASS.
- [ ] **Step 5: documentazione e commit** `feat(scraper): import dello storico Milano 2026-10-17`.

---

### Task 11: GitHub Actions e messa in produzione

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/scrape.yml`
- Modify: `docs/runbook.md`, `README.md`, `CHANGELOG.md`

- [ ] **Step 1: `ci.yml`:** su `push` e `pull_request`: checkout, `astral-sh/setup-uv` (verificare l'ultima versione maggiore disponibile), `uv sync --package scraper`, `uv run pytest -q`.
- [ ] **Step 2: `scrape.yml`:** `schedule: cron "17 2 * * *"` (02:17 UTC, notte italiana) + `workflow_dispatch` con input `cities` (stringa, vuoto = tutti), `full_details` (bool), `max_pages` (numero, 0), `max_runtime_minutes` (numero, 100; 340 per il bootstrap), `dry_run` (bool). `concurrency: {group: scrape, cancel-in-progress: false}`; `timeout-minutes: 350` (rete di sicurezza: la scadenza vera è nell'applicazione). Secrets `R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET` come variabili d'ambiente. Comando: `uv run python -m scraper run --storage r2 …input…`. Nessun altro output oltre ai log aggregati e al job summary.
- [ ] **Step 3: verifica locale:** `uv run pytest -q` tutto verde; lint YAML dei workflow (es. `actionlint` se disponibile, altrimenti revisione manuale).
- [ ] **Step 4: documentazione.** `docs/runbook.md`: configurazione una tantum (creare il bucket R2 e il token con permessi di lettura/scrittura sul solo bucket; inserire i 4 secrets su GitHub), avvio manuale, **procedura di bootstrap**, cosa fare se arriva l'email di errore, controllo freschezza, piano B (VM Google, spec §8). `README.md` con badge/stato e link. `CHANGELOG.md` → `scraper 0.1.0`.
- [ ] **Step 5: commit** `ci: workflow test e raccolta giornaliera` e tag `scraper-v0.1.0`.
- [ ] **Step 6: messa in produzione (richiede l'utente):** l'utente crea il repo pubblico, aggiunge il remote e i secrets, fa push. Poi in ordine: (a) `import-legacy` del CSV verso R2 da locale; (b) avvio manuale `cities=gorla-minore,marnate`, `max_pages=0` → verifica che da IP GitHub non ci siano 403 (se ci sono: fermarsi e passare al piano B, spec §8); (c) avvio manuale completo di bootstrap con `max_runtime_minutes=340`; (d) verificare report e conteggi; (e) lasciare attivo il cron. Annotare in `docs/fonti/trovacasa.md` i risultati reali da GitHub Actions (durata, errori, minuti consumati).
