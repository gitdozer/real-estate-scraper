# Architettura

## Visione d'insieme

```
GitHub Actions (cron giornaliero + avvio manuale)
  └─ python -m scraper run --storage r2
       1. legge lo stato corrente da R2 (state/listings.parquet)
       2. per ogni (fonte, comune, contratto): legge TUTTE le pagine elenco
       3. decide quali dettagli scaricare (nuovi / cambiati / rotazione / verifica scomparsa)
       4. scarica i dettagli, poi le impronte delle foto
       5. calcola gli eventi (nuovo, variazione prezzo, scomparso, ricomparso)
       6. controlli di qualità: se un segmento è incompleto NON registra scomparse
       7. scrive le partizioni Parquet del giorno, poi lo stato, poi il report
Cloudflare R2 (bucket privato)
  └─ Parquet partizionati per data + stato + report  (vedi dizionario-dati.md)
Locale
  └─ DuckDB legge i Parquet da R2 → in fase 3 dashboard Streamlit
```

Il codice non dipende da GitHub Actions: lo stesso comando gira su qualsiasi macchina con le variabili d'ambiente di R2 (piano B: VM Google Cloud, vedi [decisioni/0003](decisioni/0003-github-actions-r2.md)).

## Moduli (`packages/scraper/src/scraper/`)

| Modulo | Responsabilità |
|---|---|
| `config.py` | carica `config/cities.yaml` e `config/settings.yaml` |
| `models.py` | record dei dati (`Card`, `Detail`, …) e `SCHEMA_VERSION` |
| `sources/trovacasa.py` | URL e parsing delle pagine di trovacasa.it |
| `sources/base.py` | interfaccia comune delle fonti |
| `scope.py` | perimetro: cosa è residenziale "vero" |
| `fingerprint.py` | impronte per capire se una scheda o un dettaglio sono cambiati |
| `http.py` | client HTTP con tentativi e freno adattivo |
| `state.py` | riconciliazione dello stato ed eventi (vedi `logica-scomparse.md`) |
| `planner.py` | quali dettagli e quali foto scaricare oggi |
| `quality.py` | completezza dei segmenti e allarme calo |

## Rete

Client: `http.Fetcher` (httpx asincrono), header da browser reale, compressione abilitata.

| Parametro (`config/settings.yaml`) | Default | Effetto |
|---|---|---|
| `site_concurrency` | 6 | richieste contemporanee verso trovacasa.it |
| `image_concurrency` | 8 | richieste contemporanee verso il server delle foto (host diverso) |
| `max_retries` | 4 | tentativi massimi per richiesta |
| `timeout_s` | 30 | timeout della singola richiesta |
| `error_window` | 200 | richieste su cui si misura il tasso di errori |
| `error_threshold` | 0,2 | soglia oltre cui la concorrenza si dimezza |

**Cosa si ritenta:** errori di rete e timeout, risposte 5xx e 429, e il redirect del sito verso `/Error/InternalServerError` (errori 500 intermittenti). L'attesa tra un tentativo e l'altro è quella indicata da `Retry-After`, altrimenti 2, 4, 8… secondi (massimo 30) più una piccola variazione casuale.

**Cosa non si ritenta:** 404 e gli altri 4xx. Un 404 non è un errore: è l'informazione "annuncio rimosso", e non conta nel tasso di errori.

**Freno adattivo:** quando la finestra delle ultime `error_window` richieste è piena e i fallimenti definitivi (dopo tutti i tentativi) superano `error_threshold`, la concorrenza si dimezza (6 → 3 → 1). Se succede di nuovo con concorrenza 1, il client solleva `CircuitOpen`: il run si ferma in modo pulito, scrive quanto raccolto e **non registra scomparse**.

**Scadenza:** `get_many(..., deadline=…)` non avvia nuove richieste dopo la scadenza; quelle non eseguite restano in coda per il giorno dopo.

## Quali dettagli si scaricano ogni giorno

Codice: `planner.py`. Un solo dettaglio per annuncio, con il motivo di priorità più alta. Se il run deve fermarsi per tempo si perdono per primi quelli in fondo, che passano al giorno dopo.

| Priorità | Motivo | Quando |
|---|---|---|
| 1 | `absence_check` | annuncio attivo assente dagli elenchi di oggi (serve a decidere se è scomparso) |
| 2 | `new` | annuncio mai visto, o ricomparso |
| 3 | `changed` | l'impronta della scheda è cambiata (prezzo, superficie, foto, …) |
| 4 | `never_detailed` | dettaglio mai scaricato (es. run precedente interrotto) |
| 5 | `delisted_recheck` | annuncio `delisted`, ricontrollato ogni 7 giorni finché non dà 404 |
| 6 | `rotation` | aggiornamento periodico: ogni annuncio ha un suo **giorno fisso** nel ciclo di 7 giorni (ID modulo 7), oppure il dettaglio ha più di 14 giorni |
| 7 | `full` | solo con `full_details: true` (tutti, ogni giorno) |

Gli annunci fuori perimetro (aste ecc.) non ricevono il dettaglio, salvo il controllo di assenza.

**Perché il giorno fisso:** al bootstrap tutti i dettagli vengono scaricati lo stesso giorno; con la regola "più vecchio di 7 giorni" scadrebbero tutti insieme l'ottavo giorno. Con il giorno fisso ogni giorno se ne aggiorna circa un settimo.

## Quali foto si scaricano

Delle foto si calcola solo l'impronta percettiva; le immagini non si salvano. Ordine, entro il tetto `max_photos_per_run` (si aggiungono solo annunci interi):

1. annunci **nuovi** (non censurati): prime `photos_new` = 6 foto;
2. annunci con **elenco foto cambiato**: prime 6 foto;
3. **arretrato** (annunci attivi senza impronte, es. quelli già online al bootstrap): prime `photos_backlog` = 3 foto, dal più vecchio.
