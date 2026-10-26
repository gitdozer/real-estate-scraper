# Runbook — come si usa e cosa fare quando qualcosa va storto

Tutti i comandi si lanciano dalla cartella principale del repository.

## Configurazione iniziale (una volta)

### 1. Cloudflare R2

1. Nel pannello Cloudflare: **R2 Object Storage** → attivare R2 (può essere richiesto un metodo di pagamento; il piano gratuito include 10 GB).
2. **Create bucket**, es. `real-estate-data`, posizione automatica. Lasciarlo **privato** (nessun accesso pubblico).
3. **Manage R2 API Tokens** → **Create API token**: permesso **Object Read & Write**, limitato al **solo bucket** creato. Annotare *Access Key ID*, *Secret Access Key* e l'*Account ID* (visibile nella pagina R2).
4. Facoltativo ma consigliato: impostare un avviso di fatturazione a 1 €.

### 2. GitHub

1. Creare il repository (pubblico, vedi [decisioni/0003](decisioni/0003-github-actions-r2.md)) e fare push del branch `main`.
2. **Settings → Secrets and variables → Actions → New repository secret**, quattro secrets:
   `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.
3. I workflow sono in `.github/workflows/`: `Test` (a ogni push) e `Raccolta giornaliera` (ogni notte alle 02:17 UTC + avvio manuale da **Actions → Raccolta giornaliera → Run workflow**).

### 3. Primo avvio (bootstrap)

In quest'ordine:

1. **Import dello storico** da locale verso R2 (vedi "Importare lo storico" sotto), con le 4 variabili `R2_*` impostate nel terminale.
2. **Prova da GitHub su due comuni piccoli**: Run workflow con `cities = gorla-minore,marnate`. Verificare nel riepilogo che i segmenti siano completi e che non ci siano errori. Il riepilogo riporta la riga **Codici HTTP**: **se compaiono 403 (o 401/451) o l'avviso `circuit_open`**, trovacasa blocca gli IP di GitHub: fermarsi e passare al piano B (in fondo).
3. **Bootstrap completo**, da avviare **di giorno** (non tra mezzanotte e le 4, quando partirebbe anche il cron notturno e verrebbe trattato come riesecuzione dello stesso giorno): Run workflow con `max_runtime_minutes = 320` e gli altri campi vuoti (il job ha un limite di 350 minuti: il margine serve a installazione e scrittura). Scarica i dettagli di tutti i ~38.000 annunci e le prime impronte delle foto (circa 1–2 ore). Le impronte mancanti vengono completate nei giorni successivi.
4. Controllare il riepilogo e `uv run python -m scraper status --storage r2`.
5. Da qui in poi il cron gira da solo ogni notte. Annotare in `docs/fonti/trovacasa.md` durata, errori e minuti consumati dei primi run.

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

## Importare lo storico (una volta sola, prima del primo run)

```bash
uv run python -m scraper import-legacy docs/scraping-data_2026_10_trovacasa_milano_20261017_234300_17304_annunci_completi.csv --storage r2
```

Rifiuta di partire se lo stato esiste già (`--force` per forzare: sovrascrive lo stato, da usare solo su un bucket vuoto). Il CSV non è nel repository: si trova nella cartella `docs/` locale ed è copiato su R2 in `legacy/`.

## Controllare che la raccolta sia aggiornata

```bash
uv run python -m scraper status --storage r2 [--max-age-days 2]
```

Stampa la data e l'esito dell'ultimo run; termina con codice 1 se è più vecchio di `--max-age-days` giorni. **Usarlo ogni tanto**: GitHub disattiva le esecuzioni pianificate di un repository pubblico dopo 60 giorni senza commit, e in quel caso non arriva nessuna email.

## Rieseguire un giorno

Si può rieseguire **solo l'ultimo giorno raccolto**: basta rilanciare `run` (con la stessa `--date`, se non è oggi). Il run riparte dallo stato **precedente** a quel giorno (copia in `state/history/dt=<data>/`, che è la prima cosa scritta da ogni run: vale anche se il run precedente si era interrotto a metà) per i comuni raccolti, sovrascrive le partizioni del giorno per quei comuni e lascia intatte quelle degli altri. Si può quindi rieseguire anche solo un comune (`--cities`).

Una data **precedente all'ultimo run viene rifiutata** (codice di uscita 2): riporterebbe indietro lo stato. Un giorno saltato resta saltato; le date di scomparsa ne tengono conto (intervallo tra `list_last_seen` e `delisted_date`). `--dry-run` è sempre consentito.

## Ripristinare lo stato

Se un run ha prodotto uno stato sbagliato (es. bug), lo stato prima di ogni run è conservato per 30 giorni in `state/history/dt=YYYY-MM-DD/listings.parquet`:

1. copiare `state/history/dt=<giorno del run sbagliato>/listings.parquet` su `state/listings.parquet`. Il registro `state/segments.parquet` non ha copie: se il run sbagliato lo ha alterato (prima raccolta completa, cali sospetti), correggerlo a mano o cancellarlo (si ricostruisce, ma i segmenti tornano "nuovi" per 7 giorni ai fini della censura);
2. per rifare quel giorno da zero: cancellare `state/history/dt=<giorno>/`, `runs/dt=<giorno>/` e le partizioni di quel giorno (`observations/`, `details/`, `photos/`, `events/`, `raw/` con `dt=<giorno>`);
3. rilanciare il run per quel giorno (deve essere l'ultimo giorno raccolto).

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
| `segments_not_ok` con `suspicious_drop` | gli annunci visti sono calati molto rispetto al giorno prima | possibile guasto o cambio del sito: verificare a mano il sito. Se il calo è reale non serve fare nulla: dopo 3 run consecutivi viene accettato da solo |
| `drop_confirmed` | un calo ripetuto per 3 run è stato accettato come reale e le scomparse sono state registrate | verificare che sul sito il numero di annunci sia davvero calato |
| `segments_not_ok` con `no_declared_total` | la pagina 1 non riporta il totale | il sito ha probabilmente cambiato struttura: aggiornare il parser (`sources/trovacasa.py`) e le fixture |
| `active_drop` | gli annunci attivi sono calati più del 5% | verificare sul sito se è un calo reale |
| `circuit_open` | troppi errori anche a concorrenza 1 (compresi 401/403/451): il sito è in difficoltà o ci blocca | guardare la riga "Codici HTTP" del riepilogo; se si ripete per giorni (403 persistenti), passare al **piano B** (sotto) |
| `details_errors` | molti dettagli non scaricati o con pagina non riconosciuta (più di 20 e del 10%) | probabile cambio di struttura del sito o pagina di verifica anti-bot: aprire a mano un annuncio, poi aggiornare il parser e le fixture |

Il report completo, con campioni degli errori, è su R2 in `runs/dt=YYYY-MM-DD/report.json`.

**Errore imprevisto** ("Errore imprevisto: <tipo>" nel log): nel log pubblico compare solo il tipo di errore, perché il testo potrebbe contenere dati degli annunci. Il dettaglio completo (traceback) è su R2 in `runs/crash/<data-ora>.txt`. I dati raccolti fino a quel punto non vengono scritti: rieseguire il run dopo aver capito la causa.

**Run rifiutato** (codice 2): data precedente all'ultimo run, vedi "Rieseguire un giorno".

**"Configurazione: Variabili d'ambiente mancanti per R2: …"**: uno o più secrets non sono impostati o hanno un nome diverso; controllare Settings → Secrets and variables → Actions.

## Piano B: se GitHub Actions viene bloccato

Lo stesso comando gira su qualsiasi macchina: creare una VM gratuita Google Cloud e2-micro (1 GB di RAM: il run elabora i dettagli a blocchi di 500 e resta nell'ordine delle centinaia di MB), installare `uv`, clonare il repository, impostare le 4 variabili `R2_*` e pianificare con cron `uv run python -m scraper run --storage r2` ogni notte. Lo storage su R2 resta lo stesso. Vedi [decisioni/0003](decisioni/0003-github-actions-r2.md).
