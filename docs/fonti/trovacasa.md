# Fonte: trovacasa.it

Ricognizione del 2026-10-25. Codice: `packages/scraper/src/scraper/sources/trovacasa.py`. Pagine di esempio usate dai test: `packages/scraper/tests/fixtures/`.

## Generalità

- Proprietà di Immobiliare.it S.p.A. (indicato a piè di pagina). Server IIS / ASP.NET.
- **Nessuna protezione anti-bot** rilevata. robots.txt permissivo: vieta solo `?idtags=`, `/similarpartial/`, `/membership/`, `/my/`.
- **Errori 500 intermittenti**: alcune pagine rispondono con un redirect 302 verso `/Error/InternalServerError?path=…`; al secondo tentativo rispondono 200. Il client li tratta come errori temporanei e ritenta.

## Pagine elenco

- URL: `https://www.trovacasa.it/case-in-{vendita|affitto}/{slug-comune}` per la pagina 1; `…?page=N` dalla 2 in poi. **`?page=1` risponde 301**, quindi la pagina 1 si chiede senza parametro.
- 24 annunci per pagina; paginazione completa fino all'ultima pagina; oltre l'ultima → 404.
- Totale dichiarato nel testo: "17.430 case in vendita a Milano" (regex `([\d.]+) case in (vendita|affitto) a`). Serve al controllo di completezza.
- La categoria "case" contiene appartamenti, loft, attici, ville, ville a schiera, case indipendenti, rustici… ma anche **aste** e **interi stabili/palazzi** (esclusi dal perimetro, vedi `scope.py`).

### Scheda (`div.card.js_card_immobile`)

| Dato | Dove | Note |
|---|---|---|
| ID annuncio | `[data-id]` dentro la scheda | anche ultimo numero dell'URL |
| Annuncio eliminato? | attributo `data-eliminato` della scheda | sempre `False` finora; significato da verificare |
| URL dettaglio | `a.card__title[href]` = `/annunci/<prov>-tc-<inserzionista>-<id>` | `<inserzionista>` = ID agenzia o account privato |
| Titolo | testo di `a.card__title` | "Tipologia [da privato] [all'asta] a Comune indirizzo" |
| Quartiere | `span.card__quartiere` | spesso vuoto |
| Superficie, locali | `span.card__info` ("75 m²", "2 locali" / "1 locale") | possono mancare |
| Prezzo | `span.card__price` | "450.000 €"; oppure "Prezzo su richiesta" (classe `noprice`) |
| Caratteristiche | `p.annuncioTag` | es. "Ascensore", "Da Privato", "Nuova Costruzione" |
| Foto | `[data-src-list]`, ID separati da `\|` | vuoto se l'annuncio non ha foto |

**Tipologia dal titolo:** il testo prima di "da privato", "all'asta" o " a <comune>". Non basta il primo " a ": "Villa a Schiera a Milano" → "Villa a Schiera".

### Formati degli ID foto

| Formato | Esempio | URL miniatura |
|---|---|---|
| Agenzia | `A_1035_73623446_1273045083` | `https://img.trovacasa.it/annunci/mlis/<id>/foto.jpg` (da `cdn.` con redirect) |
| Privato/altro | `X_999999505_73817239_2036249360` | `https://pic.trovacasa.it/image/<ultimo numero>/m-c.jpg` |

Miniature da 70 a 135 KB.

## Pagina dettaglio

URL: quello della scheda (`/annunci/<prov>-tc-<inserzionista>-<id>`), ~86 KB.

| Dato | Dove |
|---|---|
| Titolo | `h1.immobile__title` (es. "Appartamento in vendita a Milano …") |
| Tabella attributi | ogni `dl.row`: `dt.term` (con ":" finale) → `dd.description`. Attributi osservati: Tipologia, Contratto, Comune, Indirizzo, Codice annuncio (`TC<id>`), Riferimento (codice interno dell'inserzionista), Prezzo, Superficie, Numero locali, Numero bagni, Classe energetica, Altre caratteristiche. **Il piano non compare** nei campioni (solo, a volte, come caratteristica "Ultimo Piano"). |
| Classe energetica | `dd` con `span.ce` (es. "C") seguito dal consumo "134,00 kWh/m² anno"; oppure il testo "non disponibile" |
| Caratteristiche | `a.immobileDetails__tagLabel` (dentro "Altre caratteristiche") |
| Descrizione | `p.immobileDetails__text` |
| Inserzionista | `.agenzia__name` (testo; per le agenzie è un link `/agenzie-immobiliari/<nome>-tc-<id>`, per i privati il testo è "Privato" senza link), indirizzo in `p.agenzia__address` |
| Coordinate | nello script della mappa: `var latitude = 45.40…;` `var longitude = 9.16…;` |

Telefoni ed email **non** vengono estratti.

## Annuncio rimosso

Un ID inesistente risponde **404**. Il comportamento per un annuncio realmente rimosso va verificato sui primi casi raccolti (si salva l'HTML dei primi controlli, vedi `logica-scomparse.md`).

## Volumi e velocità misurati

Annunci al 2026-10-25:

| Comune | Vendita | Affitto |
|---|---|---|
| Milano | 17.433 | 15.746 |
| Monza | 1.533 | 342 |
| Busto Arsizio | 1.006 | 91 |
| Gallarate | 680 | 76 |
| Legnano | 649 | 80 |
| Castellanza | 147 | 33 |
| Gorla Minore | 80 | 2 |
| Marnate | 60 | 4 |

Velocità (da rete domestica, pagine elenco di Milano): 1 connessione → 2,5 richieste/s; 4 → 11; 8 → 20; 16 → 31; nessun errore su 710 richieste. Con 16 connessioni la latenza mediana sale da 0,35 a 0,46 s: il server inizia a soffrire. Default scelto: 6 connessioni.

## Prove reali della pipeline

| Data | Dove | Perimetro | Risultato |
|---|---|---|---|
| 2026-10-25 | PC locale | Gorla Minore + Marnate, vendita e affitto | 147 annunci, 4 segmenti completi, 105 dettagli, 311 impronte foto, ~20 s, 0 errori. Aste: 39 su 140 in vendita (28%) |
