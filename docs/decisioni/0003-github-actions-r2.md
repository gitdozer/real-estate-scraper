# 0003 — Esecuzione su GitHub Actions, dati su Cloudflare R2

Data: 2026-10-25 · Stato: accettata

## Contesto
Vincoli: nessuna macchina dell'utente, solo servizi gratuiti (GitHub Actions, Google Cloud, Cloudflare), un run giornaliero da 20–50 minuti, dati che crescono di ~2–3 GB/anno.

## Decisione
- **Raccolta su GitHub Actions**, cron giornaliero + avvio manuale. Repository **pubblico all'inizio** (minuti illimitati) per misurare i consumi reali; poi eventualmente privato se si sta nei 2.000 minuti/mese gratuiti.
- **Dati su Cloudflare R2** (10 GB gratuiti, nessun costo di download), in file Parquet partizionati per data più un file di stato.
- Il codice non dipende da Actions: gira uguale su qualsiasi macchina con le variabili d'ambiente di R2.

## Alternative scartate
- **VM Google Cloud e2-micro** (sempre gratuita): ottima per la raccolta, ma richiede gestione del server e ha 1 GB/mese di traffico in uscita gratuito. Resta il **piano B** se GitHub Actions viene bloccato dal sito.
- **Cloudflare Workers**: il piano gratuito permette 50 richieste in uscita e 10 ms di CPU per esecuzione. Inadatto.
- **Database SQLite scaricato e ricaricato a ogni run**: rischio di corruzione e crescita incontrollata; i Parquet aggiunti per data sono più robusti e leggibili direttamente da DuckDB.

## Conseguenze
- Repository pubblico ⇒ i log dei workflow sono pubblici: nei log e nel job summary solo numeri aggregati, mai dati degli annunci. I secrets R2 non sono visibili né passati ai fork.
- GitHub disattiva i cron dei repository pubblici dopo 60 giorni senza commit: il comando `status` (e in futuro la dashboard) segnala dati non aggiornati.
- Le condizioni d'uso di Actions riguardano attività legate al software del repository: uno scraping pianificato è una zona grigia, rischio basso per ~30 minuti al giorno. Nessun offuscamento del codice (non riduce il rischio).
