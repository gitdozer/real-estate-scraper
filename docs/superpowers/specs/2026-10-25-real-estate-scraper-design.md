# Real Estate Scraper — Documento di progetto

Data: 2026-10-25 · Stato: approvato dall'utente il 2026-10-25

## 1. Perché esiste

Raccogliere ogni giorno gli annunci immobiliari residenziali (vendita e affitto) di un insieme di comuni per costruire, in una fase successiva:

- un **modello di pricing**: stimare il prezzo a cui un agente immobiliare metterebbe in vendita/affitto un immobile, date le caratteristiche;
- una stima del **tempo medio di vendita** e un **modello del tempo di vendita** date le caratteristiche.

La storia degli annunci non si recupera a posteriori: ogni giorno senza raccolta è perso. **La priorità assoluta è mettere in produzione la raccolta giornaliera il prima possibile**; deduplica avanzata, interfaccia e nuove fonti vengono dopo, sui dati già accumulati.

Progetto personale, nel tempo libero, solo strumenti gratuiti.

## 2. Obiettivi, non-obiettivi, anti-obiettivi

**Obiettivi (fase 1, questo documento)**
- Raccolta giornaliera automatica di tutti gli annunci residenziali di vendita e affitto (tenuti separati) dei comuni configurati.
- Per ogni annuncio, il massimo dei dati disponibili dalla pagina di dettaglio (foto escluse; delle foto si salvano solo le impronte percettive).
- Storico per annuncio: prima comparsa, ultima presenza, variazioni di prezzo, scomparsa.
- Raccolta, fin dal primo giorno, di tutti i segnali necessari a riconoscere a posteriori le **ripubblicazioni** e i **duplicati** (codice di riferimento agenzia, coordinate, impronte foto, descrizione).
- Aggiungere un comune = aggiungere una riga di configurazione.

**Non-obiettivi (fase 1)**
- Modelli di pricing e tempo di vendita.
- Interfaccia grafica (fase 3, ma i dati devono essere già leggibili localmente con DuckDB).
- Algoritmo di deduplica/ripubblicazione (fase 2): in fase 1 si raccolgono i segnali, non si fa il matching.
- Fonti diverse da trovacasa.it (fase 4).
- Salvare le foto.

**Anti-obiettivi (fallimento anche se "funziona")**
- **Scomparse false**: un errore di rete, un timeout o una paginazione incompleta registrati come "annuncio sparito". Siccome *sparito = venduto*, questo corrompe il dato più importante. È il rischio numero uno.
- Buchi silenziosi: il job fallisce o raccoglie metà dati e nessuno se ne accorge.
- Farsi bloccare dal sito.
- Aggirare protezioni anti-bot (casa.it è escluso per questo: è protetto da DataDome).
- Superare i limiti gratuiti di GitHub Actions o Cloudflare R2.

## 3. Decisioni prese con l'utente

| Tema | Decisione |
|---|---|
| Comuni iniziali | Milano, Busto Arsizio, Gallarate, Monza, Legnano, Gorla Minore, Marnate, Castellanza |
| Contratti | Vendita **e** affitto, tenuti separati |
| Tipologie | Solo residenziale. Esclusi: aste, lotti/interi stabili/palazzi, box, commerciale, terreni |
| Definizione di venduto | **L'annuncio sparisce** dal sito. Le ripubblicazioni (rimosso e ripubblicato come nuovo) vanno riconosciute, anche a posteriori |
| Target del pricing | Prezzo richiesto nell'annuncio |
| Profondità dei dati | Serve la pagina di dettaglio. Si può saltarla solo se l'annuncio era già noto e non è cambiato |
| Velocità | Avere tutti i dati ogni giorno; spingere quanto possibile senza farsi bloccare |
| Infrastruttura | Nessuna macchina dell'utente. Scraping su **GitHub Actions**, storage su **Cloudflare R2**. Repository creato dall'utente, **pubblico all'inizio** (minuti illimitati) per misurare i consumi reali; poi eventuale passaggio a privato se si sta nei 2.000 min/mese |
| Codice | Leggibile e documentato. **Nessun offuscamento** (proposto dall'utente, scartato: non riduce alcun rischio e contrasta con la richiesta di documentazione) |
| Documentazione | Chiara, completa e **sempre aggiornata** fin dal primo commit, comprensibile anche riprendendo il progetto dopo mesi (vedi §12) |
| Repository | Monorepo unico per scraper, dashboard, modelli e documentazione (vedi §11) |
| Dati storici | Unico storico disponibile: snapshot Milano vendita del 2026-10-17 dal vecchio scraper (17.304 annunci), da importare (vedi §6.5) |
| Foto | Non si salvano; si salvano impronte percettive (pHash) di più foto per annuncio |
| Fonte iniziale | trovacasa.it. casa.it escluso (DataDome). Siti di agenzie in fase 4 |
| Vecchio scraper | `DennisUnimib/TestGitHubActionsScraper`: solo punto di partenza, non da copiare |

## 4. Cosa sappiamo della fonte (ricognizione del 2026-10-25)

trovacasa.it (proprietà di Immobiliare.it S.p.A.), server IIS/ASP.NET, nessuna protezione anti-bot rilevata. robots.txt permissivo (vieta solo `?idtags=`, `/similarpartial/`, `/membership/`, `/my/`).

**Volumi**: ~38.000 annunci totali.

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

**Pagine elenco**: `https://www.trovacasa.it/case-in-{vendita|affitto}/{slug-comune}?page=N`, 24 annunci per pagina, paginazione completa fino all'ultima pagina (oltre l'ultima: 404). La pagina 1 senza parametro; `?page=1` risponde 301. La pagina dichiara il totale ("17.433 case in vendita a Milano"): usabile come controllo di completezza.

Ogni scheda (`div.card.js_card_immobile`) contiene: ID (`data-id`), `data-eliminato`, URL dettaglio (`/annunci/<prefisso>-<id>`), titolo (tipologia + "da privato"/"all'asta" + indirizzo), quartiere, superficie, locali, prezzo, tag (caratteristiche), logo agenzia, **elenco completo degli ID foto** (`data-src-list`).

**Pagina dettaglio** (~86 KB): prezzo, indirizzo, superficie, locali, bagni, tipologia, contratto, comune, classe energetica, codice annuncio (`TC<id>`), **riferimento interno dell'agenzia**, elenco "altre caratteristiche", descrizione completa, agenzia e sede, **latitudine/longitudine** (nello script della mappa). Il piano non è sempre presente: va estratto se c'è.

**Annuncio inesistente/rimosso**: la pagina dettaglio risponde **404**.

**Tipologie osservate**: Appartamento, Loft, Attico, Mansarda, Villa, Villa Bifamiliare, Casa Indipendente, Porzione di Casa, Rustico, Cascina, Intero Stabile, Palazzo; varianti "da privato" e "all'asta". Le aste sono dentro la categoria "case" (15% a Busto Arsizio). Tag rilevanti: `All'asta/Asta Giudiziaria`, `Nuova Costruzione`, `Affitto con riscatto`, `A Reddito`.

**Velocità misurata** (da rete domestica, pagine elenco Milano): 1 conn → 2,5 req/s; 4 → 11 req/s; 8 → 20 req/s; 16 → 31 req/s, sempre 0 errori su 710 richieste. A 16 la latenza sale (0,35 → 0,46 s mediana): il server inizia a soffrire. Il sito produce **errori 500 intermittenti** (302 verso `/Error/InternalServerError`) che spariscono al secondo tentativo.

**Foto**: miniature 70–135 KB; URL `img.trovacasa.it/annunci/mlis/<photo_id>/foto.jpg` (via redirect da `cdn.`) o `pic.trovacasa.it/image/<id>/m-c.jpg`.

**Da verificare alla prima esecuzione**: comportamento da IP GitHub Actions (il vecchio repo ha un commit "Fix 403" che suggerisce problemi passati); presenza di stanze/posti letto negli affitti di Milano.

## 5. Architettura

```
GitHub Actions (cron giornaliero, repo pubblico all'inizio)
  └─ python -m scraper run
       1. scarica stato corrente da R2
       2. per ogni (fonte, comune, contratto): legge TUTTE le pagine elenco
       3. decide quali dettagli scaricare (nuovi / cambiati / rotazione / verifica scomparsa)
       4. scarica dettagli + impronte foto dei nuovi
       5. calcola eventi (nuovo, variazione prezzo, scomparso, ricomparso)
       6. controlli di qualità → se falliscono, NON registra scomparse
       7. scrive partizioni Parquet del giorno su R2, poi lo stato aggiornato, poi il report
Cloudflare R2 (bucket privato)
  └─ Parquet partizionati per data + stato + report
Locale (utente)
  └─ DuckDB legge i Parquet da R2 (o da copia sincronizzata) → in fase 3 Streamlit
```

**Astrazione fonte**: ogni fonte implementa un'interfaccia comune (URL elenco per comune/contratto, parsing scheda, URL dettaglio, parsing dettaglio, verifica esistenza). trovacasa è la prima implementazione; i siti di agenzie si aggiungono come nuove classi senza toccare il resto.

**Configurazione**: `config/cities.yaml` con comune, codice ISTAT, slug per fonte, contratti attivi. Parametri di esecuzione (concorrenza, giorni di rotazione, modalità dettaglio completo, limite pagine per test) da file + override da input del workflow.

## 6. Logica giornaliera

### 6.1 Pagine elenco
- Si leggono **tutte** le pagine di ogni (comune, contratto), in parallelo.
- Per ogni scheda si calcola una **impronta della scheda** (hash di prezzo, superficie, locali, titolo, tag, elenco foto).
- Ogni scheda vista viene salvata nell'osservazione del giorno, inclusi gli annunci fuori perimetro (aste ecc.), con un flag `in_scope` e un `exclusion_reason`.
- Completezza: annunci unici raccolti vs totale dichiarato dal sito, per segmento (per i segmenti piccoli, sotto ~50 annunci, soglia in valore assoluto invece che percentuale).
- Perimetro (`in_scope`): esclusi aste (titolo "all'asta" o tag asta), Intero Stabile, Palazzo, stanze/posti letto. Casi dubbi (Nuova Costruzione, Affitto con riscatto, A Reddito) **inclusi e marcati**: escludere per errore è irreversibile, filtrare dopo no.

### 6.2 Quali dettagli scaricare (solo annunci `in_scope`)
1. **Nuovi**: ID mai visto.
2. **Cambiati**: impronta della scheda diversa dall'ultima.
3. **Rotazione**: dettaglio più vecchio di N giorni (default N = 7 → circa 1/7 degli annunci al giorno).
4. **Verifica scomparsa**: annunci attivi ieri e assenti oggi dall'elenco (vedi 6.3).
5. **Modalità completa** (`full_details=true`): tutti, ogni giorno.

### 6.3 Scomparse (il punto critico)
Si registrano **date separate**, perché "sparito dagli elenchi" e "pagina rimossa" possono non coincidere (il 404 è stato verificato solo su ID inventati, non su annunci realmente rimossi):
- `list_last_seen`: ultimo giorno in cui l'annuncio compariva in un elenco completo. **È la data di fine usata per il tempo di vendita.**
- `delisted_date`: primo giorno di assenza confermata dagli elenchi.
- `detail_gone_date`: primo giorno in cui il dettaglio risponde 404 (o mostra un avviso di non disponibilità, o la scheda ha `data-eliminato=True`).

Regole:
- Assente dall'elenco oggi → si controlla il dettaglio.
  - 404 / non disponibile → `removed` subito.
  - 200 → probabilmente saltato dalla paginazione (gli annunci nuovi fanno slittare le pagine durante la raccolta): resta attivo, ma **non** si aggiorna `list_last_seen`. Se resta assente da **2 run completi consecutivi** → stato `delisted` (conta come scomparso ai fini del modello), e il dettaglio si ricontrolla settimanalmente finché non dà 404.
  - errore/timeout dopo i tentativi → nessuna decisione; si ritenta il giorno dopo.
- `data-eliminato` delle schede viene salvato sempre; il suo significato va verificato nei primi giorni confrontandolo con i 404.
- Si salva un campione delle pagine dettaglio dei primi annunci scomparsi (raw) per capire come il sito presenta un annuncio rimosso, e si adeguano le regole.
- **Blocco di sicurezza**: se per un segmento la completezza è sotto soglia (default 97% del totale dichiarato) o il tasso di errori supera la soglia, in quel segmento **non si registrano scomparse** quel giorno e il run viene segnalato.
- Un annuncio `removed` che ricompare con lo stesso ID → evento `reappeared` (si chiude e riapre l'intervallo; si conserva tutto).
- Giorni senza esecuzione: la data di scomparsa è un intervallo tra `last_seen` e il primo giorno osservato assente; si salvano entrambe.

### 6.4 Impronte foto
- Per gli annunci nuovi (e quando l'elenco foto cambia): si scaricano le prime K foto (default K = 6, configurabile) e si salva per ciascuna l'**ID foto** e il **pHash a 64 bit** (più dHash). Le immagini non vengono salvate.
- Va fatto da subito: quando un annuncio scompare le sue foto non sono più scaricabili, e senza impronte la ripubblicazione non si può più riconoscere.

### 6.5 Import dello storico (una tantum)
- File: `scraping-data_2026_10_trovacasa_milano_20261017_234300_17304_annunci_completi.csv` (separatore `;`), 17.304 annunci Milano vendita al 2026-10-17. Campi: `_id` (`TC<id>`), url, prezzo (testo, anche "Prezzo su richiesta"), titolo, indirizzo, superficie, locali, bagni, classe energetica (testo libero), tag. Niente coordinate, descrizione, agenzia, foto.
- Si importa come osservazione `dt=2026-10-17` con `source_run = legacy` e campi mancanti nulli. Serve a: (a) sapere che gli annunci ancora presenti al primo run erano online almeno dal 2026-10-17; (b) registrare come scomparsi nell'intervallo (2026-10-17, primo run] quelli non più presenti, con le loro caratteristiche di base.
- Il file **non** va nel repository (dati): si carica su R2 in `legacy/` e si ignora in git.
- Il vecchio scraper non è più attivo e non ci sono altri storici.

### 6.6 Rete e cortesia
- Client HTTP asincrono con concorrenza configurabile (default **6** sul sito, **8** sulle immagini, host diverso); header da browser reale; compressione abilitata.
- Fino a 4 tentativi con attesa esponenziale + casualità; rispetto di `429`/`Retry-After`; gestione esplicita del redirect verso `/Error/InternalServerError` come errore temporaneo.
- Freno automatico: se il tasso di errori su una finestra mobile supera il 20%, la concorrenza si dimezza; se resta alto, il run si ferma in modo pulito (senza scomparse) e viene segnalato.

## 7. Dati su R2

Formato Parquet (compressione zstd), partizionato per data. Chiave annuncio: `(source, listing_id)`.

| Percorso | Contenuto | Frequenza |
|---|---|---|
| `observations/dt=YYYY-MM-DD/` | ogni scheda vista nel giorno: chiave, comune, contratto, posizione, campi della scheda, impronta, `in_scope`, `exclusion_reason` | giornaliero, ~38k righe |
| `details/dt=YYYY-MM-DD/` | dettagli scaricati nel giorno, campi parsati + descrizione completa + caratteristiche + lat/lon + agenzia + riferimento agenzia | solo righe scaricate |
| `photos/dt=YYYY-MM-DD/` | chiave, indice foto, ID foto, pHash, dHash | annunci nuovi |
| `events/dt=YYYY-MM-DD/` | `new`, `price_change` (vecchio/nuovo), `removed`, `reappeared`, `detail_changed` | giornaliero |
| `raw/dt=YYYY-MM-DD/` | HTML dettaglio compresso (solo nuovi/cambiati), per poter ri-parsare se il parser aveva un bug | retention 90 giorni |
| `state/listings.parquet` | una riga per annuncio: stato, prima comparsa, `last_seen`, prima assenza, ultima impronta, ultimo dettaglio, ultimo prezzo | sovrascritto a fine run |
| `runs/dt=YYYY-MM-DD/report.json` | metriche: richieste, errori, completezza per segmento, conteggi eventi, durata, esito controlli | giornaliero |

Ordine di scrittura: partizioni del giorno → stato → report. Rieseguire lo stesso giorno sovrascrive le partizioni di quel giorno (idempotente). Lo stato precedente viene conservato come copia datata per 30 giorni (ripristino in caso di run corrotto).

Dati personali: non si estraggono nomi di persone né numeri di telefono/email come campi. Si conserva il nome dell'agenzia. La descrizione è salvata così com'è.

## 8. Esecuzione e monitoraggio

- Workflow GitHub Actions con cron giornaliero (orario notturno, minuto non tondo per evitare i picchi di GitHub) + avvio manuale con parametri (comuni, `full_details`, limite pagine, dry-run).
- `concurrency` del workflow per evitare due run sovrapposti; timeout 120 minuti.
- **Repository pubblico**: i log dei workflow sono pubblici → nei log solo metriche aggregate, mai dati degli annunci; nessun dato nel repository; i secrets di Actions non sono esposti ai fork. GitHub disattiva i cron dei repo pubblici dopo 60 giorni senza attività: il run fallito non arriva, quindi un controllo di "freschezza" (ultimo report su R2 più vecchio di 2 giorni) va reso visibile nella dashboard e nel README del runbook.
- Secrets: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.
- Il run termina con errore (→ email automatica di GitHub) se: fallimento, controlli di qualità non superati, o calo del numero di annunci > 5% rispetto al giorno prima. Riepilogo leggibile nel job summary.
- **Avvio (bootstrap)**: il primo giorno tutti i ~38k annunci sono nuovi. Primo run con timeout esteso a 6 ore (massimo di GitHub): elenchi + dettaglio di tutti gli annunci in perimetro (~35-45 min) per primi, poi impronte foto. Per gli annunci già esistenti al bootstrap si usano K = 3 foto, a lotti nei run dei primi giorni, a partire dagli annunci più vecchi (più vicini alla scomparsa); dal secondo giorno gli annunci nuovi usano K pieno. Costo una tantum stimato ~300-400 minuti.
- **Piano B se GitHub Actions viene bloccato** (403/throttling persistente al primo test): spostare lo stesso codice su una VM gratuita Google Cloud e2-micro (opzione già ammessa), lasciando invariato lo storage su R2. Niente proxy né tecniche di elusione. Il codice non deve dipendere da GitHub Actions: deve girare uguale da qualsiasi macchina con le variabili d'ambiente di R2.
- Budget stimato: modalità incrementale ~20-30 minuti/giorno (≈ 600-900 min/mese su 2.000 gratuiti); modalità completa ~40-50 minuti/giorno. Storage stimato ~2-3 GB/anno escluso raw (raw a rotazione ≤ 2 GB).

## 9. Stack

Python 3.12, gestione ambiente con `uv`; `httpx` (asincrono) per le richieste; `selectolax` per il parsing; `polars` + `pyarrow` per i Parquet; `boto3` per R2 (API S3); `imagehash` + `Pillow` per le impronte; `pydantic` per lo schema dei record; `PyYAML` per la configurazione; `pytest` con pagine HTML salvate come fixture. In locale: `duckdb` (lettura diretta da R2) e, in fase 3, `streamlit`.

## 10. Fasi successive (ognuna avrà il suo documento)

- **Fase 2 — Ripubblicazioni e duplicati**: entità "immobile" che raggruppa annunci; candidati = annuncio scomparso + annuncio nuovo entro ~90 giorni, stesso comune/contratto/tipologia; segnali: stesso riferimento agenzia, ≥2 foto con distanza pHash bassa, superficie entro ±5%, coordinate entro ~150 m, descrizione simile. Il tempo di vendita si misura sull'immobile, dalla prima comparsa all'ultima scomparsa. Si applica retroattivamente a tutto lo storico.
- **Fase 3 — Interfaccia locale** (Streamlit + DuckDB): consultazione annunci, filtri, storico prezzi, mappe, statistiche per zona, tempi di permanenza.
- **Fase 4 — Altre fonti**: ricognizione sui siti di reti di agenzie (Tempocasa, Tecnocasa, Gabetti, Re/Max…); si integrano quelle senza protezioni anti-bot e con copertura aggiuntiva misurata.
- **Fase 5 — Modelli**: pricing (target: ultimo prezzo prima della scomparsa, con attenzione agli annunci rimasti a lungo) e analisi di sopravvivenza per il tempo di vendita; arricchimento con quotazioni OMI.

## 11. Repository e versionamento

**Monorepo unico** (un solo account GitHub). Scraper, dashboard e modelli condividono lo schema dei dati: tenerli insieme evita che lo schema prodotto dallo scraper e quello letto dalla dashboard divergano senza accorgersene. Due repository su due account sono stati valutati e scartati: doppia manutenzione, schema duplicato, e i Termini di GitHub ammettono un solo account gratuito per persona (sono ammessi solo "machine account" per l'automazione).

Struttura (workspace `uv`, ogni componente con le proprie dipendenze, così GitHub Actions installa solo lo scraper):

```
README.md                  panoramica + avvio rapido
CLAUDE.md                  regole per le sessioni AI (incl. obbligo di aggiornare la documentazione)
CHANGELOG.md               modifiche per componente
pyproject.toml             workspace uv
config/cities.yaml
packages/
  scraper/                 raccolta (src/ + tests/ con fixture HTML)
  dashboard/               fase 3 (Streamlit)
  models/                  fase 5
docs/                      vedi §12
.github/workflows/
```

Regole:
- Git con `main` sempre funzionante; lavoro su branch brevi; messaggi di commit in stile Conventional Commits con ambito (`feat(scraper): …`, `docs: …`).
- Versioni SemVer **per componente** tramite tag: `scraper-v0.1.0`, `dashboard-v0.1.0`, `models-v0.1.0`.
- **Versionamento dei dati**: ogni file Parquet contiene `schema_version` e `scraper_version` (tag + commit). Ogni modifica di schema incrementa `schema_version` ed è descritta nel dizionario dati, così i dati vecchi restano interpretabili.
- Dati, credenziali e file locali (CSV storico, `.docx`) esclusi via `.gitignore`.

## 12. Documentazione

Requisito dell'utente: chiara, completa, sempre aggiornata, utile anche riprendendo il progetto dopo mesi. Ogni modifica al codice che cambia comportamento, dati o esecuzione aggiorna la documentazione **nello stesso commit**; la regola è scritta in `CLAUDE.md`.

```
docs/
  README.md               indice: da dove partire
  panoramica.md           cos'è il progetto, perché, stato attuale, fasi
  architettura.md         componenti, flusso giornaliero, schema a blocchi
  dizionario-dati.md      ogni file/colonna: significato, tipo, origine, esempi, storia dello schema
  logica-scomparse.md     come si decide nuovo/cambiato/scomparso/ricomparso, soglie, casi limite
  fonti/trovacasa.md      struttura del sito, selettori, URL, limiti misurati, anomalie note
  runbook.md              eseguire, rieseguire un giorno, ripristinare lo stato, aggiungere un comune, ruotare le chiavi R2
  decisioni/NNNN-*.md     registro delle decisioni (contesto, decisione, alternative scartate)
  superpowers/            spec e piani di lavoro
```

## 13. Lasciato al costruttore

- Struttura interna del pacchetto, nomi di moduli e funzioni.
- Esatto elenco dei campi parsati oltre a quelli citati (prendere tutto ciò che la pagina espone in modo strutturato).
- Valori finali di concorrenza e soglie, da tarare dopo i primi run da GitHub Actions (partendo dai default sopra).
- Orario esatto del cron.
- Come rappresentare i tag/caratteristiche (lista o colonne booleane) purché senza perdita di informazione.
