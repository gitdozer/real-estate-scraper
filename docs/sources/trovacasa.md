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

A non-existent ID responds **404**. A detail page is considered valid only if it contains its own "Codice annuncio" (listing code) `TC<id>`; otherwise (an error page, an anti-bot check, a redesigned site) it counts as an error, not as an empty detail page. How the site behaves for a listing that has actually been removed still has to be verified on the first real cases collected (the HTML of the first checks is saved, see [disappearance-logic.md](../disappearance-logic.md)).

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

**From GitHub Actions (a datacenter IP) the limit is much lower** (2026-10-29): at ~12 requests/s, after ~750 requests in the first minute the site leaves almost all requests hanging (30 s timeouts, no 403/429) and serves only 8–20 per minute. At 1, 2 and ~3 requests/s: 2,093 requests, 0 timeouts. On 2026-10-30 it became clear that what matters most is **parallelism**: with 6 connections at 3 requests/s the IP gets penalised after ~710 requests (then 3–4 responses per minute for hours, even after dropping to a single connection); with a single connection, 2,093 requests went through without problems. **Correction (2026-10-30, run 41024689477):** with a single connection at ~2.4 requests/s the run stalled again after ~760 requests (6 minutes). All three stalled runs stopped at 710–760 requests whatever the rate, and the 2,093 "successful" probe requests repeated the same 798 URLs (cache hits). The limit therefore looks like a **volume of distinct pages per IP**, not a rate; being measured again with a probe that never repeats a URL. Measured again on 2026-10-30 (run 41058341202) with a probe that never repeats a URL: **at 0.5 requests/s, 1,303 distinct pages in 45 minutes without stalling** (3 isolated timeouts). Current default: **1 connection, at most 0.5 requests/s** — see [decisions/0006](../decisions/0006-rate-limiting.md). To measure again: the **Diagnosi ritmo** workflow (`python -m scraper probe`). **Old scraper, 2026-10-06 (GitHub Actions):** search results at 0.30 req/s (714 pages, 0 errors), then 17,132 detail pages at ~2.9 req/s with 4 connections for 99 minutes (2 disconnections): detail pages appear to tolerate a much higher rate than search results — measured on 2026-10-30 with `probe --kind detail`: **3,985 detail pages in 45 minutes with 2 connections, 0 timeouts**. Every stall of our collection started right after a 404 on a search-result page past the last one (see decision 0006, being verified).

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
