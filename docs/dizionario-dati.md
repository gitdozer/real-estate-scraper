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

## Layout dei file (bucket R2, o cartella locale in sviluppo)

| Percorso | Contenuto | Quando si scrive |
|---|---|---|
| `observations/dt=YYYY-MM-DD/part-0.parquet` | ogni scheda vista negli elenchi quel giorno | ogni run (~38k righe) |
| `details/dt=YYYY-MM-DD/part-0.parquet` | dettagli scaricati quel giorno | ogni run |
| `photos/dt=YYYY-MM-DD/part-0.parquet` | impronte delle foto calcolate quel giorno | ogni run |
| `events/dt=YYYY-MM-DD/part-0.parquet` | eventi del giorno (nuovo, prezzo, scomparso, …) | ogni run |
| `raw/dt=YYYY-MM-DD/raw.parquet` | HTML compresso dei dettagli nuovi/cambiati e dei primi controlli di scomparsa, per poter ri-analizzare le pagine | ogni run; conservato **90 giorni** |
| `state/listings.parquet` | stato corrente: una riga per annuncio | sovrascritto a fine run |
| `state/history/dt=YYYY-MM-DD/listings.parquet` | copia dello stato **prima** del run di quel giorno, per ripristino e per i rerun | primo run del giorno; conservata **30 giorni** |
| `state/segments.parquet` | registro dei segmenti: prima e ultima raccolta completa | ogni run |
| `runs/dt=YYYY-MM-DD/report.json` | report del run: richieste, errori, completezza, eventi, esito | ogni run |
| `legacy/` | storico importato una tantum (CSV originale + Parquet) | una volta |

Ordine di scrittura di un run: partizioni del giorno → copia dello stato precedente → nuovo stato → report. Rieseguire lo stesso giorno sovrascrive le partizioni di quel giorno.

Lettura con DuckDB (esempio):

```sql
INSTALL httpfs; LOAD httpfs;
CREATE SECRET r2 (TYPE r2, KEY_ID '…', SECRET '…', ACCOUNT_ID '…');
SELECT * FROM read_parquet('r2://<bucket>/observations/*/*.parquet', hive_partitioning = true);
```

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

## details — dati della pagina di dettaglio

Percorso: `details/dt=YYYY-MM-DD/part-0.parquet`. Una riga per ogni dettaglio scaricato quel giorno (nuovi, cambiati, rotazione settimanale, controlli di scomparsa con risposta 200). I campi tipizzati sono estratti dalla tabella attributi; `attributes` conserva comunque tutte le coppie originali.

| Colonna | Tipo | Significato |
|---|---|---|
| `source`, `listing_id` | str | chiave dell'annuncio |
| `title` | str? | titolo della pagina (es. "Appartamento in vendita a Milano …") |
| `price_eur` | int? | prezzo richiesto (affitto: canone mensile) |
| `price_on_request` | bool | testo al posto del prezzo |
| `address` | str? | indirizzo come scritto dall'inserzionista |
| `property_type` | str? | attributo "Tipologia" |
| `city`, `contract` | str | segmento (slug comune, `vendita`/`affitto`) |
| `contract_label` | str? | attributo "Contratto" come scritto nella pagina (`Vendita`/`Affitto`) |
| `municipality` | str? | attributo "Comune" |
| `listing_code` | str? | codice annuncio della fonte (`TC<id>`) |
| `agency_reference` | str? | **riferimento interno dell'inserzionista**: spesso resta uguale quando l'annuncio viene ripubblicato (segnale per la fase 2) |
| `surface_m2` | float? | superficie in m² |
| `rooms` | int? | numero di locali |
| `bathrooms` | int? | numero di bagni |
| `floor` | str? | attributo "Piano", se presente (raro) |
| `energy_class` | str? | classe energetica (`A4`…`G`) oppure "non disponibile" |
| `energy_kwh_m2_year` | float? | consumo dichiarato in kWh/m² anno |
| `features` | list[str] | "Altre caratteristiche" (Ascensore, Cantina, Arredato, …) |
| `attributes` | map[str,str] | tutte le coppie della tabella attributi, testo originale |
| `description` | str? | descrizione completa |
| `agency_name` | str? | nome dell'inserzionista ("Privato" per i privati) |
| `agency_id` | str? | ID agenzia sulla fonte (nullo per i privati) |
| `agency_address` | str? | indirizzo dell'agenzia |
| `latitude`, `longitude` | float? | coordinate della mappa (precisione dichiarata dall'inserzionista) |
| `detail_hash` | str | impronta di tutti i campi sopra: cambia se cambia qualcosa nel dettaglio |
| `run_date` | date | giorno della raccolta |

## photos — impronte percettive delle foto

Percorso: `photos/dt=YYYY-MM-DD/part-0.parquet`. Le immagini **non** vengono salvate: solo le impronte. Servono in fase 2 a riconoscere lo stesso immobile ripubblicato con un nuovo ID (le agenzie ricaricano le stesse foto).

| Colonna | Tipo | Significato |
|---|---|---|
| `source`, `listing_id` | str | chiave dell'annuncio |
| `city`, `contract` | str | segmento dell'annuncio |
| `photo_index` | int | posizione della foto nell'annuncio (0 = prima) |
| `photo_id` | str | ID della foto sulla fonte |
| `phash` | str | impronta percettiva pHash a 64 bit (16 caratteri esadecimali) |
| `dhash` | str | impronta dHash a 64 bit, complementare |
| `run_date` | date | giorno del calcolo |

**Come confrontare due foto:** distanza di Hamming tra le impronte (`scraper.photos.hamming`, oppure in SQL `bit_count(xor(...))` sugli interi). Indicativamente ≤ 6 su 64 bit = stessa foto (anche ridimensionata o ricompressa); > 10 = foto diverse. Le soglie definitive si tareranno in fase 2 su dati reali.

## state — stato corrente, una riga per annuncio

Percorso: `state/listings.parquet` (sovrascritto a fine run). Spiegazione degli stati e delle date: [logica-scomparse.md](logica-scomparse.md).

| Colonna | Tipo | Significato |
|---|---|---|
| `source`, `listing_id` | str | chiave dell'annuncio |
| `city`, `contract` | str | segmento dell'ultima volta in cui è stato visto |
| `url` | str | URL della pagina di dettaglio |
| `status` | str | `active`, `delisted` (sparito dagli elenchi, pagina ancora online), `removed` (pagina 404/410) |
| `in_scope`, `exclusion_reason`, `flags` | | perimetro, come in `observations` |
| `first_seen` | date | primo giorno in cui è stato visto |
| `spell_start` | date | inizio del periodo online corrente (= `first_seen`, o giorno dell'ultima ricomparsa) |
| `first_seen_censored` | bool | già online al primo giorno di raccolta del segmento (o nello storico importato): l'inizio reale è precedente |
| `list_last_seen` | date | ultimo giorno visto negli elenchi — **data di fine per il tempo di vendita** |
| `absent_since` | date? | primo giorno dell'assenza in corso (nullo se presente) |
| `missing_streak` | int | controlli con esito 200 durante l'assenza in corso |
| `delisted_date` | date? | primo giorno dell'assenza confermata (con esito certo del controllo) |
| `detail_gone_date` | date? | primo giorno in cui il dettaglio ha risposto 404/410 |
| `last_check_date` | date? | ultimo controllo del dettaglio durante un'assenza |
| `last_fingerprint` | str? | impronta dell'ultima scheda vista |
| `last_price` | int? | ultimo prezzo visto negli elenchi |
| `last_detail_date` | date? | ultimo giorno in cui è stato scaricato il dettaglio |
| `last_detail_hash` | str? | impronta dell'ultimo dettaglio |
| `photo_ids_hash` | str? | impronta dell'elenco foto per cui sono state calcolate le impronte |
| `photos_done` | int | numero di foto con impronta calcolata |

## events — cosa è successo, un evento per riga

Percorso: `events/dt=YYYY-MM-DD/part-0.parquet`.

| Colonna | Tipo | Significato |
|---|---|---|
| `source`, `listing_id` | str | chiave dell'annuncio |
| `city`, `contract` | str | segmento dell'annuncio |
| `run_date` | date | giorno del run |
| `type` | str | `new`, `price_change`, `delisted`, `removed`, `detail_gone`, `reappeared`, `detail_changed` |
| `old_value` | str? | `price_change`: prezzo precedente; `reappeared`: stato precedente |
| `new_value` | str? | `new`/`price_change`: prezzo nuovo; `reappeared`: `active` |
| `spell_start` | date? | `removed`/`delisted`/`detail_gone`/`reappeared`: inizio del periodo online che si chiude |
| `list_last_seen` | date? | idem: ultimo giorno visto negli elenchi (fine del periodo) |
| `delisted_date` | date? | idem: primo giorno di assenza confermata |

Filtrando `type in ('removed', 'delisted')` si ottiene l'elenco delle "vendite" con le loro date (vedi [logica-scomparse.md](logica-scomparse.md)).

## segments — registro dei segmenti

Percorso: `state/segments.parquet`. Una riga per (fonte, comune, contratto).

| Colonna | Tipo | Significato |
|---|---|---|
| `source`, `city`, `contract` | str | segmento |
| `first_complete_run` | date? | primo giorno con raccolta completa. Gli annunci nuovi nei 7 giorni successivi sono marcati `first_seen_censored` (probabilmente già online prima) |
| `last_complete_run` | date? | ultimo giorno con raccolta completa |

## raw — HTML grezzo (90 giorni)

Percorso: `raw/dt=YYYY-MM-DD/raw.parquet`. Serve a ri-analizzare le pagine se il parser aveva un errore, e a capire come il sito presenta gli annunci rimossi.

| Colonna | Tipo | Significato |
|---|---|---|
| `source`, `listing_id`, `city`, `contract` | str | annuncio e segmento |
| `reason` | str | motivo del download (`new`, `changed`, `never_detailed`, oppure controllo di assenza con esito 404 o redirect: primi 50 per run) |
| `url`, `final_url` | str | URL richiesto e URL finale dopo eventuali redirect |
| `status` | int | codice HTTP |
| `html` | str | pagina completa (compressa dal Parquet) |
| `run_date` | date | giorno |

## Storia dello schema

| Versione | Data | Modifica |
|---|---|---|
| 1 | 2026-10-25 | Prima versione |
