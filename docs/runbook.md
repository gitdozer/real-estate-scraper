# Runbook — come si usa e cosa fare quando qualcosa va storto

Tutti i comandi si lanciano dalla cartella principale del repository.

## Eseguire la raccolta

```bash
uv sync --package scraper                      # una volta, o dopo un aggiornamento delle dipendenze
uv run python -m scraper run [opzioni]
```

| Opzione | Effetto |
|---|---|
| `--storage local` / `--storage r2` | dove leggere/scrivere i dati. `local` (default) usa la cartella `--local-root` (default `data/`, esclusa da git); `r2` usa le variabili d'ambiente `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` |
| `--cities gorla-minore,marnate` | solo questi comuni (slug di `config/cities.yaml`); default tutti |
| `--date 2026-10-26` | data del run (default: oggi, fuso Europe/Rome) |
| `--full-details` | scarica il dettaglio di tutti gli annunci, non solo nuovi/cambiati/rotazione |
| `--max-pages N` | solo le prime N pagine per segmento — **solo per prove**: blocca la registrazione di scomparse e fa terminare il run con errore |
| `--max-runtime-minutes M` | durata massima (default 100). Oltre l'85% non si scaricano altri dettagli, oltre il 90% altre foto: il lavoro restante passa al giorno dopo |
| `--dry-run` | esegue tutto ma non scrive nulla |

Il comando termina con **codice 1** (e su GitHub arriva l'email di errore) se un segmento è incompleto, se gli annunci attivi calano più del 5%, o se il sito restituisce troppi errori (circuito aperto). I dati raccolti vengono comunque scritti.

Prova veloce in locale (2 comuni piccoli, ~20 secondi):

```bash
uv run python -m scraper run --cities gorla-minore,marnate --storage local --local-root data
```

## Controllare che la raccolta sia aggiornata

```bash
uv run python -m scraper status --storage r2 [--max-age-days 2]
```

Stampa la data e l'esito dell'ultimo run; termina con codice 1 se è più vecchio di `--max-age-days` giorni. **Usarlo ogni tanto**: GitHub disattiva le esecuzioni pianificate di un repository pubblico dopo 60 giorni senza commit, e in quel caso non arriva nessuna email.

## Rieseguire un giorno

Basta rilanciare `run` con la stessa `--date`. Il run riparte dallo stato **precedente** a quel giorno (copia in `state/history/dt=<data>/`) per i comuni raccolti, sovrascrive le partizioni del giorno per quei comuni e lascia intatte quelle degli altri comuni. Si può quindi rieseguire anche solo un comune (`--cities`).

## Ripristinare lo stato

Se un run ha prodotto uno stato sbagliato (es. bug), lo stato prima di ogni run è conservato per 30 giorni in `state/history/dt=YYYY-MM-DD/listings.parquet`:

1. copiare `state/history/dt=<giorno del run sbagliato>/listings.parquet` su `state/listings.parquet`;
2. cancellare `runs/dt=<giorno>/report.json` (altrimenti il run successivo dello stesso giorno viene trattato come rerun) e le partizioni di quel giorno se vanno rifatte;
3. rilanciare il run per quel giorno, se serve.

## Aggiungere un comune

1. Trovare lo slug del comune su trovacasa.it: è la parte finale dell'URL `https://www.trovacasa.it/case-in-vendita/<slug>`.
2. Trovare il codice ISTAT (6 cifre).
3. Aggiungere una riga a `config/cities.yaml`, aggiornare `docs/panoramica.md` e fare commit.

I primi 7 giorni di un comune nuovo hanno gli annunci marcati `first_seen_censored` (erano probabilmente già online).

## Cosa fare quando arriva un'email di errore

Aprire il run su GitHub Actions: il riepilogo mostra quale controllo è fallito.

| Avviso | Significato | Cosa fare |
|---|---|---|
| `segments_not_ok` con `failed_pages` | alcune pagine elenco non sono state scaricate nemmeno dopo i tentativi | di solito un problema temporaneo del sito: rieseguire il run (anche solo per quei comuni). Nessuna scomparsa è stata registrata per quei comuni |
| `segments_not_ok` con `incomplete` | raccolti meno del 97% degli annunci dichiarati | controllare se il sito ha cambiato la paginazione; rieseguire |
| `segments_not_ok` con `suspicious_drop` | gli annunci visti sono calati molto rispetto al giorno prima | possibile guasto o cambio del sito: verificare a mano il sito prima di tutto |
| `segments_not_ok` con `no_declared_total` | la pagina 1 non riporta il totale | il sito ha probabilmente cambiato struttura: aggiornare il parser (`sources/trovacasa.py`) e le fixture |
| `active_drop` | gli annunci attivi sono calati più del 5% | verificare sul sito se è un calo reale |
| `circuit_open` | troppi errori anche a concorrenza 1: il sito è in difficoltà o ci blocca | se si ripete per giorni (403 persistenti), passare al **piano B** (sotto) |

Il report completo, con campioni degli errori, è su R2 in `runs/dt=YYYY-MM-DD/report.json`.

## Piano B: se GitHub Actions viene bloccato

Lo stesso comando gira su qualsiasi macchina: creare una VM gratuita Google Cloud e2-micro, installare `uv`, clonare il repository, impostare le 4 variabili `R2_*` e pianificare con cron `uv run python -m scraper run --storage r2` ogni notte. Lo storage su R2 resta lo stesso. Vedi [decisioni/0003](decisioni/0003-github-actions-r2.md).
