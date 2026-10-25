# 0005 — Sparito = venduto, con date separate

Data: 2026-10-25 · Stato: accettata

## Contesto
Non esistono dati pubblici sulle compravendite effettive. L'esperienza diretta dell'utente (che sta cercando casa) è che il tempo di permanenza online di un annuncio approssima bene il tempo di vendita. Le scritte "venduto"/"in trattativa" delle agenzie sono troppo rare per essere usate. Il caso frequente da gestire sono le **ripubblicazioni**: l'annuncio viene tolto e ripubblicato con un nuovo ID per sembrare nuovo.

## Decisione
- Un annuncio si considera **venduto quando sparisce** dal sito.
- Si registrano **tre date distinte**, perché "sparito dagli elenchi" e "pagina rimossa" possono non coincidere:
  - `list_last_seen` — ultimo giorno in cui compariva negli elenchi: **data di fine per il tempo di vendita**;
  - `delisted_date` — primo giorno di assenza confermata;
  - `detail_gone_date` — primo giorno in cui la pagina di dettaglio risponde 404.
- Un'assenza si conferma solo se la raccolta del segmento era completa; un errore di rete non decide mai nulla.
- Si raccolgono fin dal primo giorno i segnali per riconoscere le ripubblicazioni a posteriori (fase 2): riferimento interno dell'agenzia, coordinate, impronte di più foto, descrizione.
- Target del modello di prezzo: il prezzo richiesto nell'annuncio (l'ultimo prima della scomparsa).

## Alternative scartate
- **Usare "venduto"/"in trattativa"**: troppo raro.
- **Considerare scomparso un annuncio alla prima assenza**: la paginazione slitta durante la raccolta (gli annunci nuovi spostano gli altri tra le pagine) e produrrebbe scomparse false.

## Conseguenze
- Il tempo di vendita va trattato come analisi di sopravvivenza con dati censurati (annunci ancora online; annunci già online al primo giorno di raccolta, marcati `first_seen_censored`).
- Dettagli della logica: [logica-scomparse.md](../logica-scomparse.md).
