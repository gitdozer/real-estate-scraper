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

## Aggiornamento 2026-10-30: conta il numero di connessioni in parallelo

Il primo avvio con 3 richieste/s **ma 6 connessioni in parallelo** si è bloccato di nuovo dopo ~710 richieste (minuto 4). Da lì il sito ha risposto a 3–4 richieste al minuto per oltre 2 ore, **anche dopo che il freno era sceso a una sola connessione**: l'IP resta "in penalità". La diagnosi `probe`, con **una connessione** sola, aveva fatto 2.093 richieste fino a ~3/s senza alcun timeout. Conclusione: il sito tollera ~3 richieste/s **in sequenza**; più connessioni simultanee dallo stesso IP fanno scattare una penalità di ore. Da qui `site_concurrency = 1` (e, per prudenza, `image_concurrency = 1`).

## Decisione
- Il client HTTP usa **una sola connessione** verso il sito e verso le foto (`site_concurrency = image_concurrency = 1`) e rispetta un **ritmo massimo**: `site_rate_per_s = 3`, `image_rate_per_s = 4` (limite delle foto non ancora misurato). Con le latenze reali (0,3–0,6 s) il ritmo effettivo è ~2–3 richieste/s.
- **Ogni tentativo fallito** (timeout, 5xx, 429) conta subito nel tasso di errori: se supera il 20%, concorrenza e ritmo si dimezzano (fino a 0,25 richieste/s), poi si apre il circuito.
- Anche la **fase elenchi ha una scadenza** (40% del tempo massimo): le pagine non lette contano come fallite, il segmento risulta incompleto (nessuna scomparsa), ma il run si chiude e scrive quanto raccolto.
- Log di avanzamento per fase e battito ogni minuto durante gli elenchi (richieste, in volo, latenze, codici HTTP).

## Alternative scartate
- **Rotazione di IP o proxy** per superare il limite: è un aggiramento di una protezione del sito (regola 5 di CLAUDE.md).
- **Eseguire dal PC dell'utente**: escluso dai vincoli del progetto.

## Conseguenze
- Run giornaliero stimato: ~1.700 pagine elenco + ~7.000 dettagli ≈ 60 minuti, dentro i 100 minuti.
- Primo avvio: ~35.000 dettagli ≈ 4 ore: si completa in 1–2 run grazie alle scadenze (i dettagli non scaricati restano in coda); le foto mancanti nei giorni seguenti.
- Il ritmo si può alzare con prudenza osservando il battito nei log (timeout = troppo veloce).
