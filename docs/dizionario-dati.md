# Dizionario dei dati

Tutti i dati vivono su Cloudflare R2 in file Parquet (compressione zstd), partizionati per data di raccolta (`dt=YYYY-MM-DD`). Si leggono direttamente con DuckDB.

## Convenzioni comuni

- **Chiave di un annuncio:** `(source, listing_id)`. `source` è la fonte (oggi solo `trovacasa`); `listing_id` è l'ID dell'annuncio sulla fonte, come stringa.
- **Segmento:** `(source, city, contract)` — es. `(trovacasa, milano, vendita)`. Vendita e affitto non si mescolano mai.
- `city` è lo **slug** del comune usato dalla fonte (vedi `config/cities.yaml`).
- `run_date` è la data della raccolta nel fuso `Europe/Rome`.
- Ogni file ha due colonne di versione:
  - `schema_version` — versione dello schema (intero). Ogni modifica di colonne la incrementa ed è descritta in fondo, in "Storia dello schema".
  - `scraper_version` — versione del codice che ha prodotto il dato, es. `0.1.0+abc1234` (versione + commit) o `0.1.0+local`.

## observations — una riga per ogni scheda vista negli elenchi

Percorso: `observations/dt=YYYY-MM-DD/part-0.parquet`. Contiene **tutte** le schede viste quel giorno, anche quelle fuori perimetro (aste ecc.), marcate.

| Colonna | Tipo | Significato |
|---|---|---|
| `source` | str | fonte (`trovacasa`) |
| `listing_id` | str | ID dell'annuncio sulla fonte |
| `city` | str | slug del comune del segmento |
| `contract` | str | `vendita` o `affitto` |
| `url` | str | URL della pagina di dettaglio |
| `title` | str | titolo della scheda, es. "Appartamento da privato a Milano via Masaccio, 18" |
| `property_type` | str? | tipologia ricavata dal titolo (Appartamento, Loft, Villa a Schiera, …) |
| `is_private` | bool | annuncio di un privato ("da privato" nel titolo) |
| `is_auction` | bool | asta ("all'asta" nel titolo) |
| `neighborhood` | str? | quartiere/zona indicato dalla fonte |
| `surface_m2` | float? | superficie in m² |
| `rooms` | int? | numero di locali |
| `price_eur` | int? | prezzo richiesto in euro (affitto: canone mensile). Nullo se non indicato |
| `price_on_request` | bool | la scheda riporta un testo al posto del prezzo (es. "Prezzo su richiesta") |
| `tags` | list[str] | caratteristiche mostrate nella scheda |
| `photo_ids` | list[str] | ID delle foto, nell'ordine della fonte |
| `advertiser_id` | str? | ID dell'inserzionista (agenzia o account privato) preso dall'URL |
| `eliminato` | bool | attributo `data-eliminato` della scheda; significato da verificare |
| `page` | int | pagina dell'elenco in cui è stata vista |
| `position` | int | posizione nella pagina (0–23) |
| `in_scope` | bool | dentro il perimetro della raccolta (vedi `scope.py`) |
| `exclusion_reason` | str? | motivo dell'esclusione: `auction`, `whole_building`, `room` |
| `flags` | list[str] | casi dubbi inclusi ma marcati: `new_build`, `rent_to_buy`, `investment` |
| `fingerprint` | str | impronta della scheda (16 caratteri esadecimali): cambia se cambiano prezzo, superficie, locali, titolo, caratteristiche o foto; non dipende da pagina e posizione |
| `run_date` | date | giorno della raccolta |
| `source_run` | str | `daily` per la raccolta normale, `legacy` per l'import dello storico |

## Storia dello schema

| Versione | Data | Modifica |
|---|---|---|
| 1 | 2026-10-25 | Prima versione |
