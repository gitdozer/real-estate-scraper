# 0001 — trovacasa.it come fonte iniziale

Data: 2026-10-25 · Stato: accettata

## Contesto
Servono gli annunci residenziali (vendita e affitto) di 8 comuni, ogni giorno, con il massimo dei dettagli, senza farsi bloccare e senza aggirare protezioni. immobiliare.it e idealista sono esclusi in partenza (bloccano lo scraping).

## Decisione
Si parte da **trovacasa.it**. Ricognizione del 2026-10-25:
- nessuna protezione anti-bot (server IIS/ASP.NET), robots.txt permissivo;
- ~38.000 annunci nei comuni scelti, paginazione completa (24 per pagina);
- 0 blocchi su 710 richieste fino a 31 richieste/s (con 16 connessioni il server inizia a rallentare);
- la pagina di dettaglio espone coordinate, riferimento interno dell'agenzia, descrizione, caratteristiche; le schede dell'elenco espongono l'elenco completo delle foto.

## Alternative scartate
- **casa.it** — protetto da DataDome (vedi [0002](0002-esclusione-casa-it.md)).
- **Scegliere l'aggregatore "più completo" a tavolino** — non serve: casa.it è escluso e trovacasa copre bene; le agenzie si valuteranno in fase 4 misurando la copertura aggiuntiva.

## Conseguenze
- trovacasa.it è di proprietà di Immobiliare.it S.p.A.: potrebbe introdurre protezioni in futuro. Il run segnala un calo anomalo di annunci (> 5%) e i controlli di completezza bloccano le scomparse false.
- Il codice ha un'astrazione "fonte" per aggiungere altri siti senza toccare il resto.
- Gli errori 500 intermittenti del sito (redirect a `/Error/InternalServerError`) richiedono tentativi automatici.
