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
