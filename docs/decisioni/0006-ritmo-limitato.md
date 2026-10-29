# 0006 — Ritmo limitato verso il sito (~3 richieste al secondo)

Data: 2026-10-29 · Stato: accettata

## Contesto
Il primo avvio su GitHub Actions (27 ottobre) e i run dei giorni successivi sono stati annullati dal limite del job (350 e poi 120 minuti) senza scrivere nulla. I log di avanzamento hanno mostrato che il run restava bloccato nella **fase elenchi**:

- nel primo minuto ~750 richieste riuscite (≈12 al secondo, 6 in parallelo);
- poi, per tutto il resto del run, **12 timeout al minuto** (le 6 connessioni sempre appese per 30 s) e solo 8–20 risposte al minuto.

Il sito non risponde con 403 o 429: verso gli IP dei datacenter **lascia appese le richieste** quando il ritmo è troppo alto. Dall'IP domestico lo stesso ritmo funziona (1.528 pagine in 1,1 minuti). Il vecchio scraper, più lento (pagine elenco una alla volta con 2,5 s di pausa), non incontrava il problema.

Diagnosi da GitHub con il comando `probe` (workflow "Diagnosi ritmo"), richieste una alla volta:

| Ritmo | Richieste | Riuscite | Timeout | Latenza media |
|---|---|---|---|---|
| 1/s per 10 min | 592 | 592 | 0 | 0,50 s |
| 2/s per 5 min | 577 | 577 | 0 | 0,41 s |
| ~3/s per 5 min | 924 | 924 | 0 | 0,31 s |

È un **limite di frequenza**, non un tetto al numero di richieste.

## Decisione
- Il client HTTP rispetta un **ritmo massimo**: `site_rate_per_s = 3` verso il sito, `image_rate_per_s = 4` verso il server delle foto (limite non ancora misurato).
- **Ogni tentativo fallito** (timeout, 5xx, 429) conta subito nel tasso di errori: se supera il 20%, concorrenza e ritmo si dimezzano (fino a 0,25 richieste/s), poi si apre il circuito.
- Anche la **fase elenchi ha una scadenza** (40% del tempo massimo): le pagine non lette contano come fallite, il segmento risulta incompleto (nessuna scomparsa), ma il run si chiude e scrive quanto raccolto.
- Log di avanzamento per fase e battito ogni minuto durante gli elenchi (richieste, in volo, latenze, codici HTTP).

## Alternative scartate
- **Rotazione di IP o proxy** per superare il limite: è un aggiramento di una protezione del sito (regola 5 di CLAUDE.md).
- **Eseguire dal PC dell'utente**: escluso dai vincoli del progetto.

## Conseguenze
- Run giornaliero stimato: ~1.700 pagine elenco + ~7.000 dettagli ≈ 50 minuti, dentro i 100 minuti.
- Primo avvio: ~35.000 dettagli ≈ 3,2 ore (budget 320 minuti); le foto mancanti si completano nei giorni seguenti.
- Il ritmo si può alzare con prudenza osservando il battito nei log (timeout = troppo veloce).
