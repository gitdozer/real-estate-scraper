# Source: trovacasa.it

Reconnaissance carried out on 2026-10-25. Code: `packages/scraper/src/scraper/sources/trovacasa.py`. Sample pages used by the tests: `packages/scraper/tests/fixtures/`.

## General notes

- Owned by Immobiliare.it S.p.A. (as stated in the page footer). IIS / ASP.NET server.
- **No anti-bot protection** detected. robots.txt is permissive: it only disallows `?idtags=`, `/similarpartial/`, `/membership/`, `/my/`.
- **Intermittent 500 errors**: some pages respond with a 302 redirect to `/Error/InternalServerError?path=…`; on the second attempt they respond 200. The client treats these as temporary errors and retries.

## Search-result pages

- URL: `https://www.trovacasa.it/case-in-{vendita|affitto}/{municipality-slug}` for page 1; `…?page=N` from page 2 onwards. **`?page=1` responds with a 301**, so page 1 is requested without the parameter.
- 24 listings per page; pagination works all the way to the last page; beyond the last page → 404.
- The declared total appears in the text: "17.430 case in vendita a Milano" ("17,430 homes for sale in Milan"; regex `([\d.]+) cas[ae] in (vendita|affitto) a`). It is used by the completeness check. Edge cases verified on 2026-10-26: with **1 listing** the number does not appear ("case in affitto a Zerbolò") and the total is derived from the listing cards on page 1; with **0 listings** the page responds 200 with "Nessun risultato" ("No results") and the total is 0. Fixtures: `list_zerbolo_affitto_one.html`, `list_morimondo_affitto_none.html`.
- The "case" (homes) category contains flats, lofts, penthouses, villas, terraced houses, detached houses, farmhouses… but also **auctions** and **whole buildings/apartment blocks** (excluded from the scope, see `scope.py`).

### Listing card (`div.card.js_card_immobile`)

| Data | Where | Notes |
|---|---|---|
| Listing ID | `[data-id]` inside the card | also the last number in the URL |
| Listing deleted? | the card's `data-eliminato` attribute | always `False` so far; meaning still to be verified |
| Detail URL | `a.card__title[href]` = `/annunci/<prov>-tc-<inserzionista>-<id>` | `<inserzionista>` (advertiser) = agency ID or private account ID |
| Title | text of `a.card__title` | "Tipologia [da privato] [all'asta] a Comune indirizzo" (property type [private seller] [at auction] in municipality, address) |
| Neighborhood | `span.card__quartiere` | often empty |
| Floor area, rooms | `span.card__info` ("75 m²", "2 locali" / "1 locale") | may be missing |
| Price | `span.card__price` | "450.000 €"; or "Prezzo su richiesta" (price on request; class `noprice`) |
| Features | `p.annuncioTag` | e.g. "Ascensore", "Da Privato", "Nuova Costruzione". **At most 6**: it is an excerpt of the full list on the detail page |
| Photos | `[data-src-list]`, IDs separated by `\|` | empty if the listing has no photos |

**Property type from the title:** the text before "da privato", "all'asta" or " a <comune>" (" in <municipality>"). Splitting on the first " a " is not enough: "Villa a Schiera a Milano" → "Villa a Schiera".

### Photo ID formats

| Format | Example | Thumbnail URL |
|---|---|---|
| Agency | `A_1035_73623446_1273045083` | `https://img.trovacasa.it/annunci/mlis/<id>/foto.jpg` (redirected from `cdn.`) |
| Private/other | `X_999999505_73817239_2036249360` | `https://pic.trovacasa.it/image/<last number>/m-c.jpg` |

Thumbnails are 70 to 135 KB.

## Detail page

URL: the one from the listing card (`/annunci/<prov>-tc-<inserzionista>-<id>`), ~86 KB.

| Data | Where |
|---|---|
| Title | `h1.immobile__title` (e.g. "Appartamento in vendita a Milano …") |
| Attribute table | each `dl.row`: `dt.term` (with a trailing ":") → `dd.description`. Attributes observed: Tipologia, Contratto, Comune, Indirizzo, Codice annuncio (`TC<id>`), Riferimento (the advertiser's internal code), Prezzo, Superficie, Numero locali, Numero bagni, Classe energetica, Altre caratteristiche. **The floor does not appear** in the samples (only, sometimes, as the feature "Ultimo Piano", top floor). |
| Energy class | `dd` with `span.ce` (e.g. "C") followed by the consumption "134,00 kWh/m² anno"; or the text "non disponibile" (not available) |
| Features | `a.immobileDetails__tagLabel` (inside "Altre caratteristiche") |
| Description | `p.immobileDetails__text` |
| Advertiser | `.agenzia__name` (text; for agencies it is a link `/agenzie-immobiliari/<nome>-tc-<id>`, for private sellers the text is "Privato" with no link), address in `p.agenzia__address` |
| Coordinates | in the map script: `var latitude = 45.40…;` `var longitude = 9.16…;` |

Phone numbers and email addresses are **not** extracted.

## Removed listing

A non-existent ID responds **404** (verified on made-up ids and on 3,469 real removed listings on 2026-10-31/11-01). **Since ~2026-11-02, one request for a non-existent id from a GitHub runner puts the IP in penalty about 7–11 s later, for hours**: the site keeps answering 404s instantly and leaves every valid page hanging (probes 42473045029 and 42475525510 of 2026-11-08, decision 0007). The daily run therefore requests at most `absence_checks_per_run` such pages, after everything else. A detail page is considered valid only if it contains its own "Codice annuncio" (listing code) `TC<id>`; otherwise (an error page, an anti-bot check, a redesigned site) it counts as an error, not as an empty detail page. How the site behaves for a listing that has actually been removed still has to be verified on the first real cases collected (the HTML of the first checks is saved, see [disappearance-logic.md](../disappearance-logic.md)).

## Measured volumes and speed

Listings as of 2026-10-25:

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

Speed (from a home connection, Milan result pages): 1 connection → 2.5 requests/s; 4 → 11; 8 → 20; 16 → 31; no errors over 710 requests. With 16 connections the median latency rises from 0.35 to 0.46 s: the server starts to struggle.

**From GitHub Actions (a datacenter IP) the limit is much lower** (2026-10-29): at ~12 requests/s, after ~750 requests in the first minute the site leaves almost all requests hanging (30 s timeouts, no 403/429) and serves only 8–20 per minute. At 1, 2 and ~3 requests/s: 2,093 requests, 0 timeouts. On 2026-10-30 it became clear that what matters most is **parallelism**: with 6 connections at 3 requests/s the IP gets penalised after ~710 requests (then 3–4 responses per minute for hours, even after dropping to a single connection); with a single connection, 2,093 requests went through without problems. **Correction (2026-10-30, run 41024689477):** with a single connection at ~2.4 requests/s the run stalled again after ~760 requests (6 minutes). All three stalled runs stopped at 710–760 requests whatever the rate, and the 2,093 "successful" probe requests repeated the same 798 URLs (cache hits). The limit therefore looks like a **volume of distinct pages per IP**, not a rate; being measured again with a probe that never repeats a URL. Measured again on 2026-10-30 (run 41058341202) with a probe that never repeats a URL: **at 0.5 requests/s, 1,303 distinct pages in 45 minutes without stalling** (3 isolated timeouts). Current defaults (since 0.1.4): **search-result pages on 1 connection at 0.3 requests/s; detail pages on 2 connections at 1.5 requests/s** — see [decisions/0006](../decisions/0006-rate-limiting.md). To measure again: the **Rate probe** workflow (`python -m scraper probe`). **Old scraper, 2026-10-06 (GitHub Actions):** search results at 0.30 req/s (714 pages, 0 errors), then 17,132 detail pages at ~2.9 req/s with 4 connections for 99 minutes (2 disconnections): detail pages appear to tolerate a much higher rate than search results — measured on 2026-10-30 with `probe --kind detail`: **3,985 detail pages in 45 minutes with 2 connections, 0 timeouts**. Every stall of our collection started right after a 404 on a search-result page past the last one; the test of 2026-10-31 showed that a single 404 is not enough, but deep and non-existent search-result pages lead to a stall sooner (~450 requests). Since 0.1.4: search results at 0.3 req/s without ever requesting a page past the last one (the pager's "next" link is followed), detail pages at 1.5 req/s with 2 connections — see decision 0006.

## Map endpoint (future option, not used)

The search-results page has a map view that loads, in a single request, `GET /ricerca/geojson?cacheKey=/case-in-vendita/<city>`: a GeoJSON with one point per listing. Checked by hand on 2026-10-30 (Milano sale, a response saved from the browser, ~12 MB):

- 16,129 listings against 17,470 declared (92%): probably the listings without coordinates are missing;
- per listing: `id` (same as our `listing_id`), coordinates (mostly 4 decimals), `prezzodescr`, `mqdescr`, `nrlocalidescr`, `tipodescr`, `titolo`, `urlanteprima` (cover photo) as display text; no address, bathrooms, energy class, agency or tags;
- clicking a point calls `GET /immobile/json?idlist=<id>&codCache=<…>` (title, price, floor area, rooms, URLs).

It could replace most of the search-result requests (1 request per segment instead of hundreds), but it **cannot be the basis for disappearances**: the ~8% of listings missing from the map would look gone every day. Kept as an option for later (decision of 2026-10-30); not implemented.

## Real pipeline test runs

| Date | Where | Scope | Result |
|---|---|---|---|
| 2026-10-25 | Local PC | Gorla Minore + Marnate, sale and rent | 147 listings, 4 complete segments, 105 detail pages, 311 photo fingerprints, ~20 s, 0 errors. Auctions: 39 of the 140 for sale (28%) |
| 2026-10-26 | Local PC | same, the following day | 4 listings removed (real 404s, HTML in `raw/`), 2 new, 70 requests. The site removed the "Non Arredato/Vuoto" (unfurnished/empty) feature from every listing: 38 `detail_changed` events and 51 listing cards with a changed fingerprint (a card shows at most **6 features**: if one disappears, another takes its place) |
| 2026-10-31 | GitHub Actions, scraper 0.1.4 (run 41193385596) | all 16 segments, first full collection | **search results: 1,579 pages in 87.8 min at 0.3 req/s, 0 errors**; 37,678 listings, 13 of 16 segments complete (3 `suspicious_drop` against the stale state). Details: 9,276 downloaded, 105 404s, ~1.47 req/s for the first ~2,000, then the brake halved the pace after a burst of 503s/timeouts (36 503s, 17 timeouts in all) to ~0.72 req/s; 26,725 left in the queue. Photos: 3,077 fingerprints in ~17 min, 26,875 in the queue. Total 297 min |
| 2026-11-01 | GitHub Actions, scraper 0.1.4 (run 41292379710) | all 16 segments | search results again 1,579 pages in 87.8 min, 0 errors; **14 of 16 segments complete** (Gorla Minore and Marnate sale: `suspicious_drop`). Details: 9,734 downloaded at ~1.46 req/s for the first ~10,000 requests, then ~0.72 req/s after the brake (33 503s, 16 timeouts); 3,451 absence checks all answered 404 → 3,451 `removed` (stale listings from the 2026-10-17 history and earlier partial runs; Milano sale `drop_confirmed` after 3 runs), 746 new, 428 price changes. 18,932 details and 26,655 photos still queued. Total 297 min; exit code 1 because of the expected `active_drop` (40,430 → 37,725) and the two small segments |
| 2026-11-02, 11-03 | GitHub Actions, scraper 0.1.4 and 0.1.5 (runs 41421166681, 41611812025) | all 16 segments | search results fine again (1,579 pages, 0 errors, 88 min); then **the details phase never completed its first batch** (no progress line for 4.5 hours) and GitHub cancelled the job at 350 minutes: **nothing written for these two days**. Cause: a detail request that never completes (httpx's timeout applies between bytes) blocks its batch of 500 and, with it, the deadline; reproduced in a test. Fixed in 0.1.6 (total limit per request, heartbeat in every phase, stack dump for stuck runs) |
| 2026-11-04 → 11-07 | GitHub Actions, scraper 0.1.6 (4 runs) | all 16 segments | all **cancelled at 350 minutes, nothing written**. Search results fine (1,579–1,715 pages, 0 errors, ~90 min); then **almost every detail page timed out from the first minute** (11-07: 576 requests, 5 404s, 570 timeouts, ~2 per minute). The same detail pages answer normally from the user's home connection (57/57). Two problems: (1) the deadline was checked only before a request's first attempt, so retries queued behind other requests kept starting after it, one 30 s timeout each, until GitHub cancelled the job — fixed in 0.1.7; (2) the site stopped answering detail pages to GitHub's IPs — **cause found on 2026-11-08**: the detail queue started with the absence checks (404s), and one 404 now puts the IP in penalty (decision 0007) |
| 2026-11-08 | GitHub Actions, scraper 0.1.7 (run 42465190604) | all 16 segments | every search-result request failed with `ConnectTimeout` (64/64: the runner's IP could not reach the site at all, while a fresh runner 85 minutes later could); the run **ended in 32 minutes and wrote** (0 events, no removals), as 0.1.7 intended |
| 2026-11-09 | GitHub Actions, scraper 0.2.0 (run 42596074364) | all 16 segments | **search results: 1,595 pages, all 200, 0 errors; 13 of 16 segments complete** (3 small ones `suspicious_drop`); first run written since 11-01: 5,975 new, 46 reappeared, 0 disappearances (first counted absence). Details (new listings first, no 404 in the queue): **4,602 pages at ~1.4 req/s in 55 min, 0 × 404**, then at 12:11 UTC a few `ReadTimeout`/`RemoteProtocolError` and a **burst of 503s** (435 in 13 min, every request): brake to 1 connection, circuit open at 12:24; photos skipped because of the open circuit; written at 157 min |
| 2026-11-10 | GitHub Actions, scraper 0.2.0 (run 42793962848) | all 16 segments | search results: 1,731 pages, all 200, 0 errors, **all 16 segments collected in full**, 14 flagged `suspicious_drop` against the `active` count inflated by the 11-09 absences (see runbook); 3,491 new, **3,566 `delisted`** (Milano rentals absent on 11-09 and 11-10). Details: **after 44 pages, 3 × 404 among the first new listings** — three listings by private sellers inserted that morning, on page 696 of 739 (the site lists fresh private listings at the end of the results) and online in a browser ten hours later: **the card appears before the page is published** (decision 0009) — then 2 timeouts (the penalty of decision 0007) and the phase stopped (`details_stopped_404`); photos: 29,987 of 29,998 fingerprints in 135 min (the image host is not affected by the penalty); the sampled absence check after the photos timed out; written at 234 min |
| 2026-11-11 | GitHub Actions, scraper 0.2.2 (run 42995000164) | all 16 segments | search results: 1,731 pages, all 200, 0 errors (96 min). Details (first day with decision 0009: no first-day listings in the queue): **~9,930 pages OK at ~1.4 req/s in 127 min**, timeouts rising from 13:00 UTC (22 in the last 4 minutes), then a 404 at ~222 min stopped the phase. Photos: 13,635 OK at ~3 req/s up to the photo deadline (297 min); **the 16,000 photo requests left were then skipped at the configured pace** (0.25 s each) and GitHub cancelled the job at 350 min: **nothing written** (fixed in 0.2.3) |
| 2026-11-08 | GitHub Actions, probes 42399690479 (11-07), 42473045029, 42475525510 | Milano sale, 300 search-result pages then detail pages at 1.5 req/s × 2 connections | 2,017/2,017 detail pages OK with no 404; **0 OK after 10 × 404 placed first**; **0 OK after a single 404 placed after 20 valid pages** (penalty ≈ 11 s later). Trigger of the failed runs found: decision 0007 |
